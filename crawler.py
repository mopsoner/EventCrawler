import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config_store import load_config

DB_PATH = "data/eventcrawler.sqlite"
BASE_URL = "https://www.bizouk.com"
EVENT_URL_RE = re.compile(r"/events/details/([^/]+)/(?P<id>\d+)")
URL_RE = re.compile(r"https?://[^\s]+", re.I)
STATUS_PATH = Path("data/crawl_status.json")
CONFIG = load_config()
HEADERS = {"User-Agent": CONFIG.get("user_agent", "Mozilla/5.0")}
MAX_WORKERS = int(CONFIG.get("max_workers", 6))
REQUEST_TIMEOUT = int(CONFIG.get("request_timeout", 45))


def save_status(data):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def enabled_regions():
    regions = {}
    for name, region in CONFIG.get("regions", {}).items():
        if region.get("enabled") and region.get("url"):
            regions[name] = region["url"]
    selected = os.getenv("EVENTCRAWLER_SELECTED_REGIONS", "").strip()
    if selected:
        wanted = {x.strip() for x in selected.split(",") if x.strip()}
        regions = {k: v for k, v in regions.items() if k in wanted}
    return regions


def conn():
    Path("data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ensure_column(cur, table, column, ddl):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    c = conn()
    cur = c.cursor()
    cur.executescript(
        '''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_url TEXT UNIQUE NOT NULL,
            region TEXT,
            name TEXT,
            subtitle TEXT,
            event_date TEXT,
            city TEXT,
            address TEXT,
            contact_phone TEXT,
            contact_email TEXT,
            score INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price_text TEXT,
            numeric_price REAL,
            is_free INTEGER DEFAULT 0,
            is_available INTEGER,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(event_id, product_name, price_text)
        );
        '''
    )
    ensure_column(cur, "events", "event_external_id", "event_external_id TEXT")
    ensure_column(cur, "events", "event_slug", "event_slug TEXT")
    ensure_column(cur, "events", "contact_website", "contact_website TEXT")
    ensure_column(cur, "events", "event_image", "event_image TEXT")
    ensure_column(cur, "events", "subtitle", "subtitle TEXT")
    c.commit()
    c.close()


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def digits_only_count(text):
    return len(re.sub(r"\D", "", text or ""))


def parse_price(text):
    if not text:
        return None
    t = text.strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*€", t)
    return float(m.group(1)) if m else None


def extract_email(text):
    m = re.search(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", text or "", re.I)
    return m.group(1) if m else None


def extract_phone(text):
    candidates = re.findall(r"(\+?\d[\d\s().-]{7,}\d)", text or "")
    for cand in candidates:
        if digits_only_count(cand) >= 9:
            return re.sub(r"\s+", "", cand).strip()
    return None


def extract_website(text):
    for url in URL_RE.findall(text or ""):
        cleaned = url.rstrip(').,;]')
        if "bizouk.com" not in cleaned.lower():
            return cleaned
    return None


def extract_event_image(soup):
    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and meta.get("content"):
        return urljoin(BASE_URL, meta.get("content"))
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src:
            continue
        full = urljoin(BASE_URL, src)
        low = full.lower()
        if any(k in low for k in ["flyer", "affiche", "uploads", "/img/"]):
            return full
    return None


def score_event(name, region, products):
    score = 0
    low = (name or "").lower()
    if "carnaval" in low or "carnival" in low:
        score += 30
    if region in {"london", "rotterdam", "paris"}:
        score += 20
    if any(p.get("is_free") for p in products):
        score += 15
    if any(p.get("is_free") and p.get("is_available") is True for p in products):
        score += 25
    return min(score, 100)


def fetch_html(url, session=None):
    client = session or requests
    r = client.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text


def parse_event_ref(href):
    m = EVENT_URL_RE.search(href or "")
    if not m:
        return None
    return {"slug": m.group(1), "external_id": m.group("id")}


def extract_event_links(html):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "/events/details/" not in href:
            continue
        full = urljoin(BASE_URL, href)
        ref = parse_event_ref(full)
        if not ref:
            continue
        out[ref["external_id"]] = {"url": full, **ref}
    return list(out.values())


def remove_noise(soup):
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


def lines_from_node(node):
    if not node:
        return []
    return [normalize_text(x) for x in node.get_text("\n", strip=True).splitlines() if normalize_text(x)]


def lines_from_soup(soup):
    return [normalize_text(x) for x in soup.get_text("\n", strip=True).splitlines() if normalize_text(x)]


def looks_like_date_line(text):
    if not text:
        return False
    low = text.lower()
    return bool(re.search(r"\b20\d{2}\b", text)) and any(k in low for k in ["am", "pm", " at ", " à ", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"])


def extract_header_fields(soup):
    h1 = soup.find("h1")
    h2 = soup.find("h2")
    name = normalize_text(h1.get_text(" ", strip=True)) if h1 else None
    subtitle = normalize_text(h2.get_text(" ", strip=True)) if h2 else None
    date_text = None
    city = None
    address = None
    search_root = None
    if h1:
        parent = h1.parent
        for _ in range(4):
            if not parent:
                break
            if hasattr(parent, "get_text") and len(parent.get_text(" ", strip=True)) > 20:
                search_root = parent
                break
            parent = parent.parent
    lines = lines_from_node(search_root) if search_root else lines_from_soup(soup)
    start = 0
    if name and name in lines:
        start = lines.index(name) + 1
    if subtitle and subtitle in lines[start:]:
        start = lines.index(subtitle, start) + 1
    for i in range(start, min(start + 12, len(lines))):
        line = lines[i]
        if not date_text and looks_like_date_line(line):
            date_text = line
            continue
        if date_text and not city and digits_only_count(line) < 6 and "view my" not in line.lower() and "contact" not in line.lower():
            city = line
            continue
        if date_text and city and not address and "view my" not in line.lower() and "contact" not in line.lower():
            address = line
            break
    return {"name": name, "subtitle": subtitle, "event_date": date_text, "city": city, "address": address}


def extract_contact_info(lines):
    contact_lines = []
    for i, line in enumerate(lines):
        if line.lower() == "contact":
            contact_lines = lines[i + 1:i + 12]
            break
    contact_phone = None
    contact_email = None
    contact_website = None
    for line in contact_lines:
        low = line.lower()
        if low.startswith("infoline"):
            contact_phone = extract_phone(line)
        elif low.startswith("site") or low.startswith("website"):
            contact_website = extract_website(line)
        elif not contact_email:
            contact_email = extract_email(line)
    if not (contact_phone or contact_email or contact_website):
        contact_text = "\n".join(contact_lines) if contact_lines else "\n".join(lines)
        contact_phone = extract_phone(contact_text)
        contact_email = extract_email(contact_text)
        contact_website = extract_website(contact_text)
    return {"contact_phone": contact_phone, "contact_email": contact_email, "contact_website": contact_website}


def is_non_product_name(line):
    low = (line or "").lower()
    return any(x in low for x in [
        "total amount", "montant total", "tickets", "billets", "transportation",
        "pay with friends", "details", "sold out", "upcoming", "contact organizer",
        "view my itenary", "view my itinerary", "log in", "register now", "starting from"
    ])


def extract_products_from_dom(soup):
    products = []
    seen = set()
    for div in soup.find_all(["div", "section", "article"]):
        text = normalize_text(div.get_text(" ", strip=True))
        if not text or "€" not in text or len(text) > 2200:
            continue
        lines = [normalize_text(x) for x in div.get_text("\n", strip=True).splitlines() if normalize_text(x)]
        price_line = next((x for x in lines if parse_price(x) is not None and not is_non_product_name(x)), None)
        if not price_line:
            continue
        price = parse_price(price_line)
        name = None
        for line in lines:
            if line == price_line:
                break
            if parse_price(line) is None and len(line) < 120 and not is_non_product_name(line):
                name = line
                break
        if not name:
            continue
        blob = " ".join(lines).lower()
        is_available = True
        if any(w in blob for w in ["sold out", "épuisé", "indisponible", "complet"]):
            is_available = False
        elif any(w in blob for w in ["upcoming", "à venir"]):
            is_available = None
        key = (name, price_line)
        if key in seen:
            continue
        seen.add(key)
        products.append({"product_name": name, "price_text": price_line, "numeric_price": price, "is_free": price == 0.0, "is_available": is_available})
    products.sort(key=lambda p: (not p["is_free"], p["numeric_price"] if p["numeric_price"] is not None else 999999))
    return products


def build_event_from_item(item, session=None):
    url = item["url"]
    region = item["region"]
    slug = item.get("slug")
    external_id = item.get("external_id")
    html = fetch_html(url, session=session)
    soup = remove_noise(BeautifulSoup(html, "html.parser"))
    lines = lines_from_soup(soup)
    header = extract_header_fields(soup)
    contact = extract_contact_info(lines)
    products = extract_products_from_dom(soup)
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    name = header["name"] or normalize_text(title)
    return {"event_url": url, "event_slug": slug, "event_external_id": external_id, "region": region, "name": name, "subtitle": header.get("subtitle"), "event_date": header.get("event_date"), "city": header.get("city"), "address": header.get("address"), "contact_phone": contact["contact_phone"], "contact_email": contact["contact_email"], "contact_website": contact["contact_website"], "event_image": extract_event_image(soup), "products": products, "score": score_event(name, region, products)}


def worker(item):
    session = requests.Session()
    try:
        return build_event_from_item(item, session=session)
    finally:
        session.close()


def upsert_event(event):
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT id FROM events WHERE event_url = ?", (event["event_url"],))
    row = cur.fetchone()
    if row:
        event_id = row["id"]
        cur.execute("UPDATE events SET event_external_id=?, event_slug=?, region=?, name=?, subtitle=?, event_date=?, city=?, address=?, contact_phone=?, contact_email=?, contact_website=?, event_image=?, score=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0), event_id))
    else:
        cur.execute("INSERT INTO events(event_url, event_external_id, event_slug, region, name, subtitle, event_date, city, address, contact_phone, contact_email, contact_website, event_image, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event["event_url"], event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0)))
        event_id = cur.lastrowid
    for p in event.get("products", []):
        cur.execute("SELECT id FROM products WHERE event_id=? AND product_name=? AND price_text=?", (event_id, p.get("product_name"), p.get("price_text")))
        old = cur.fetchone()
        avail = 1 if p.get("is_available") is True else 0 if p.get("is_available") is False else None
        if old:
            cur.execute("UPDATE products SET numeric_price=?, is_free=?, is_available=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (p.get("numeric_price"), 1 if p.get("is_free") else 0, avail, old["id"]))
        else:
            cur.execute("INSERT INTO products(event_id, product_name, price_text, numeric_price, is_free, is_available) VALUES (?, ?, ?, ?, ?, ?)", (event_id, p.get("product_name"), p.get("price_text"), p.get("numeric_price"), 1 if p.get("is_free") else 0, avail))
    c.commit()
    c.close()


def run():
    init_db()
    regions = enabled_regions()
    selected = list(regions.keys())
    save_status({"running": True, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": datetime.utcnow().isoformat(), "finished_at": None, "last_error": None})
    all_items = []
    try:
        for region, start_url in regions.items():
            try:
                html = fetch_html(start_url)
                region_items = extract_event_links(html)
                for item in region_items:
                    item["region"] = region
                all_items.extend(region_items)
            except Exception as exc:
                print(f"[ERROR] region {region}: {exc}")
        if not all_items:
            save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": "No events found"})
            return
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(worker, item): item for item in all_items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    event = future.result()
                    upsert_event(event)
                    print(f"[OK] {item['region']} -> {item['external_id']} -> {item['url']}")
                except Exception as exc:
                    print(f"[ERROR] event {item['url']}: {exc}")
        save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": None})
    except Exception as exc:
        save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": str(exc)})
        raise


if __name__ == "__main__":
    run()
