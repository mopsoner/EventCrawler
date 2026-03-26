import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config_store import load_config

DB_PATH = "data/eventcrawler.sqlite"
BASE_URL = "https://www.bizouk.com"
EVENT_URL_RE = re.compile(r"/events/details/([^/]+)/(?P<id>\d+)")
DATE_HINT_RE = re.compile(r"(\b20\d{2}\b|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|january|february|march|april|may|june|july|august|september|october|november|december|\bam\b|\bpm\b)", re.I)
URL_RE = re.compile(r"https?://[^\s]+", re.I)
CONFIG = load_config()
HEADERS = {"User-Agent": CONFIG.get("user_agent", "Mozilla/5.0")}
MAX_WORKERS = int(CONFIG.get("max_workers", 6))
REQUEST_TIMEOUT = int(CONFIG.get("request_timeout", 45))


def enabled_regions():
    regions = {}
    for name, region in CONFIG.get("regions", {}).items():
        if region.get("enabled") and region.get("url"):
            regions[name] = region["url"]
    return regions


def conn():
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
            return re.sub(r"\s+", " ", cand).strip()
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
    for node in soup.find_all(string=lambda s: s and "Votre panier" in s):
        parent = node.parent
        for _ in range(5):
            if not parent:
                break
            classes = " ".join(parent.get("class", [])) if hasattr(parent, "get") else ""
            text = parent.get_text(" ", strip=True) if hasattr(parent, "get_text") else ""
            if "panier" in classes.lower() or "Votre panier" in text:
                parent.decompose()
                break
            parent = parent.parent
    return soup


def lines_from_soup(soup):
    return [normalize_text(x) for x in soup.get_text("\n", strip=True).splitlines() if normalize_text(x)]


def extract_billet_lines(lines):
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.lower() == "billets":
            start = i + 1
            break
    if start is None:
        return []
    for j in range(start, len(lines)):
        low = lines[j].lower()
        if low.startswith("montant total") or low.startswith("description") or low == "contact":
            end = j
            break
    return lines[start:end] if end else lines[start:]


def extract_products(lines):
    billet_lines = extract_billet_lines(lines)
    out = []
    seen = set()
    for i, line in enumerate(billet_lines):
        price = parse_price(line)
        if price is None:
            continue
        name = None
        for back in range(1, 5):
            if i - back >= 0:
                cand = billet_lines[i - back]
                if parse_price(cand) is None and cand.lower() not in {"billets", "montant total:"} and len(cand) < 140:
                    name = cand
                    break
        if not name:
            continue
        window = " ".join(billet_lines[i:i+6]).lower()
        if any(w in window for w in ["épuisé", "epuise", "sold out", "indisponible", "complet", "a venir"]):
            is_available = False if any(w in window for w in ["épuisé", "epuise", "sold out", "indisponible", "complet"]) else None
        else:
            is_available = True
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "product_name": name,
            "price_text": line,
            "numeric_price": price,
            "is_free": price == 0.0,
            "is_available": is_available,
        })
    return out


def extract_event_core(lines, title):
    name = next((x for x in lines[:12] if len(x) > 4 and "bizouk" not in x.lower() and x.lower() != "évènements"), title)
    event_date = next((x for x in lines[:25] if DATE_HINT_RE.search(x)), None)
    venue = None
    address = None
    if event_date and event_date in lines:
        idx = lines.index(event_date)
        for j in range(idx + 1, min(idx + 12, len(lines))):
            cand = lines[j]
            low = cand.lower()
            if not venue and "voir le plan d'accès" not in low and digits_only_count(cand) < 8:
                venue = cand
                continue
            if not address and digits_only_count(cand) >= 5 and "voir le plan d'accès" not in low:
                address = cand
                break
    city = None
    if address:
        m = re.search(r"\b\d{4,5}\s+(.+)$", address)
        if m:
            city = m.group(1).strip()
    return name, event_date, venue, address, city


def extract_contact_info(lines):
    contact_lines = []
    for i, line in enumerate(lines):
        if line.lower() == "contact":
            contact_lines = lines[i + 1:i + 10]
            break
    contact_text = "\n".join(contact_lines) if contact_lines else "\n".join(lines)
    return {
        "contact_phone": extract_phone(contact_text),
        "contact_email": extract_email(contact_text),
        "contact_website": extract_website(contact_text),
    }


def build_event_from_item(item, session=None):
    url = item["url"]
    region = item["region"]
    slug = item.get("slug")
    external_id = item.get("external_id")
    html = fetch_html(url, session=session)
    soup = remove_noise(BeautifulSoup(html, "html.parser"))
    h1 = soup.find("h1")
    title = normalize_text(h1.get_text(" ", strip=True)) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else url)
    lines = lines_from_soup(soup)
    name, event_date, venue, address, city = extract_event_core(lines, title)
    products = extract_products(lines)
    contact = extract_contact_info(lines)
    return {
        "event_url": url,
        "event_slug": slug,
        "event_external_id": external_id,
        "region": region,
        "name": name,
        "event_date": event_date,
        "city": city,
        "address": address or venue,
        "contact_phone": contact["contact_phone"],
        "contact_email": contact["contact_email"],
        "contact_website": contact["contact_website"],
        "event_image": extract_event_image(soup),
        "products": products,
        "score": score_event(name, region, products),
    }


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
        cur.execute(
            "UPDATE events SET event_external_id=?, event_slug=?, region=?, name=?, event_date=?, city=?, address=?, contact_phone=?, contact_email=?, contact_website=?, event_image=?, score=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?",
            (event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0), event_id),
        )
    else:
        cur.execute(
            "INSERT INTO events(event_url, event_external_id, event_slug, region, name, event_date, city, address, contact_phone, contact_email, contact_website, event_image, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event["event_url"], event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0)),
        )
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
    all_items = []
    for region, start_url in regions.items():
        try:
            html = fetch_html(start_url)
            region_items = extract_event_links(html)
            for item in region_items:
                item["region"] = region
            all_items.extend(region_items)
            print(f"[INFO] {region}: {len(region_items)} events queued")
        except Exception as exc:
            print(f"[ERROR] region {region}: {exc}")

    if not all_items:
        print("[INFO] No events found")
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


if __name__ == "__main__":
    run()
