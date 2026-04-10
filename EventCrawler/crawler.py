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

from ai_automation import enrich_event_labels
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
AI_ENRICH_ENABLED = os.getenv("AI_ENRICH_ENABLED", "1") != "0"


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
            description TEXT,
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
        CREATE TABLE IF NOT EXISTS product_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            product_name TEXT,
            change_type TEXT,
            old_price REAL,
            new_price REAL,
            old_is_free INTEGER,
            new_is_free INTEGER,
            old_is_available INTEGER,
            new_is_available INTEGER,
            observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT,
            regions TEXT,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT,
            events_queued INTEGER DEFAULT 0,
            events_processed INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS crawl_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_run_id INTEGER,
            scope TEXT,
            target TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_ai_labels (
            event_id INTEGER PRIMARY KEY,
            language TEXT,
            summary_short TEXT,
            event_type TEXT,
            genres_json TEXT,
            audience_tags_json TEXT,
            confidence REAL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        '''
    )
    ensure_column(cur, "events", "event_external_id", "event_external_id TEXT")
    ensure_column(cur, "events", "event_slug", "event_slug TEXT")
    ensure_column(cur, "events", "contact_website", "contact_website TEXT")
    ensure_column(cur, "events", "event_image", "event_image TEXT")
    ensure_column(cur, "events", "subtitle", "subtitle TEXT")
    ensure_column(cur, "events", "description", "description TEXT")
    ensure_column(cur, "events", "manual_status", "manual_status TEXT")
    ensure_column(cur, "events", "private_note", "private_note TEXT")
    ensure_column(cur, "events", "is_watchlisted", "is_watchlisted INTEGER DEFAULT 0")
    c.commit()
    c.close()


def save_event_ai_label(event_id, event):
    if not AI_ENRICH_ENABLED:
        return
    try:
        labels = enrich_event_labels(event)
    except Exception:
        return
    c = conn()
    try:
        c.execute(
            "INSERT OR REPLACE INTO event_ai_labels(event_id, language, summary_short, event_type, genres_json, audience_tags_json, confidence, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                event_id,
                labels.get("language"),
                labels.get("summary_short"),
                labels.get("event_type"),
                json.dumps(labels.get("genres_json") or [], ensure_ascii=False),
                json.dumps(labels.get("audience_tags_json") or [], ensure_ascii=False),
                float(labels.get("confidence") or 0),
            ),
        )
        c.commit()
    finally:
        c.close()


def create_crawl_run(regions):
    c = conn(); cur = c.cursor(); cur.execute("INSERT INTO crawl_runs(mode, regions, status) VALUES (?, ?, ?)", ("manual", ",".join(regions), "running")); run_id = cur.lastrowid; c.commit(); c.close(); return run_id


def update_crawl_run(run_id, **fields):
    if not fields: return
    c = conn(); keys = list(fields.keys()); sql = "UPDATE crawl_runs SET " + ", ".join([f"{k}=?" for k in keys]) + " WHERE id=?"; c.execute(sql, [fields[k] for k in keys] + [run_id]); c.commit(); c.close()


def log_crawl_error(run_id, scope, target, error_text):
    c = conn(); c.execute("INSERT INTO crawl_errors(crawl_run_id, scope, target, error_text) VALUES (?, ?, ?, ?)", (run_id, scope, target, str(error_text)[:2000])); c.commit(); c.close()


def normalize_text(text): return re.sub(r"\s+", " ", (text or "").strip())

def digits_only_count(text): return len(re.sub(r"\D", "", text or ""))

def parse_price(text):
    if not text: return None
    t = text.strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t: return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*€", t)
    return float(m.group(1)) if m else None

def extract_email(text):
    m = re.search(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", text or "", re.I)
    return m.group(1) if m else None

def extract_phone(text):
    candidates = re.findall(r"(\+?\d[\d\s().-]{7,}\d)", text or "")
    for cand in candidates:
        if digits_only_count(cand) >= 9: return re.sub(r"\s+", "", cand).strip()
    return None

def extract_website(text):
    for url in URL_RE.findall(text or ""):
        cleaned = url.rstrip(').,;]')
        if "bizouk.com" not in cleaned.lower(): return cleaned
    return None

def extract_event_image(soup):
    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and meta.get("content"): return urljoin(BASE_URL, meta.get("content"))
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src: continue
        full = urljoin(BASE_URL, src); low = full.lower()
        if any(k in low for k in ["flyer", "affiche", "uploads", "/img/"]): return full
    return None

def extract_description(soup, lines):
    for i, line in enumerate(lines):
        low = line.lower()
        if low in {"description", "descriptif", "about", "details"}:
            block = []
            for nxt in lines[i + 1:i + 30]:
                nxt_low = nxt.lower()
                if nxt_low in {"contact", "tickets", "produits", "products", "location", "lieu"}: break
                if len(nxt) > 2: block.append(nxt)
            text = normalize_text(" ".join(block))
            if len(text) >= 30: return text[:4000]
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        text = normalize_text(meta.get("content"))
        if text: return text[:4000]
    return None

def score_event(name, region, products, contact, has_image, event_date):
    score = 0; low = (name or "").lower()
    if any(k in low for k in ["carnaval", "carnival", "jouvert", "boat", "pre-registration", "pré-inscription", "dreamland"]): score += 30
    if region in {"london", "rotterdam", "paris"}: score += 15
    if any(p.get("is_free") for p in products): score += 15
    if any(p.get("is_free") and p.get("is_available") is True for p in products): score += 25
    if contact.get("contact_phone") or contact.get("contact_email") or contact.get("contact_website"): score += 10
    if has_image: score += 5
    if event_date: score += 5
    return min(score, 100)

def fetch_html(url, session=None):
    client = session or requests; r = client.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT); r.raise_for_status(); return r.text

def parse_event_ref(href):
    m = EVENT_URL_RE.search(href or "")
    if not m: return None
    return {"slug": m.group(1), "external_id": m.group("id")}

def extract_event_links(html):
    soup = BeautifulSoup(html, "html.parser"); out = {}
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "/events/details/" not in href: continue
        full = urljoin(BASE_URL, href); ref = parse_event_ref(full)
        if not ref: continue
        out[ref["external_id"]] = {"url": full, **ref}
    return list(out.values())

def remove_noise(soup):
    for tag in soup(["script", "style", "noscript"]): tag.decompose()
    return soup

def lines_from_node(node):
    if not node: return []
    return [normalize_text(x) for x in node.get_text("\n", strip=True).splitlines() if normalize_text(x)]

def lines_from_soup(soup): return [normalize_text(x) for x in soup.get_text("\n", strip=True).splitlines() if normalize_text(x)]

def looks_like_date_line(text):
    if not text: return False
    low = text.lower()
    return bool(re.search(r"\b20\d{2}\b", text)) and any(k in low for k in ["am", "pm", " at ", " à ", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"])

def extract_header_fields(soup):
    h1 = soup.find("h1"); h2 = soup.find("h2"); name = normalize_text(h1.get_text(" ", strip=True)) if h1 else None; subtitle = normalize_text(h2.get_text(" ", strip=True)) if h2 else None; date_text = None; city = None; address = None; search_root = None
    if h1:
        parent = h1.parent
        for _ in range(4):
            if not parent: break
            if hasattr(parent, "get_text") and len(parent.get_text(" ", strip=True)) > 20: search_root = parent; break
            parent = parent.parent
    lines = lines_from_node(search_root) if search_root else lines_from_soup(soup); start = 0
    if name and name in lines: start = lines.index(name) + 1
    if subtitle and subtitle in lines[start:]: start = lines.index(subtitle, start) + 1
    for i in range(start, min(start + 12, len(lines))):
        line = lines[i]
        if not date_text and looks_like_date_line(line): date_text = line; continue
        if date_text and not city and digits_only_count(line) < 6 and "view my" not in line.lower() and "contact" not in line.lower(): city = line; continue
        if date_text and city and not address and "view my" not in line.lower() and "contact" not in line.lower(): address = line; break
    return {"name": name, "subtitle": subtitle, "event_date": date_text, "city": city, "address": address}

def extract_contact_info(soup, lines):
    candidate_lines = []
    for i, line in enumerate(lines):
        low = line.lower()
        if low == "contact" or low.startswith("contact ") or "contact organizer" in low: candidate_lines.extend(lines[i:i + 25])
    if not candidate_lines:
        for i, line in enumerate(lines):
            low = line.lower()
            if "infoline" in low or "whatsapp" in low or low.startswith("site") or low.startswith("website"): start = max(0, i - 2); candidate_lines.extend(lines[start:i + 8])
    seen = set(); candidate_lines = [x for x in candidate_lines if not (x in seen or seen.add(x))]
    contact_block_text = "\n".join(candidate_lines); contact_phone = None; contact_email = None; contact_website = None
    for line in candidate_lines:
        low = line.lower()
        if ("infoline" in low or "whatsapp" in low or low.startswith("phone")) and not contact_phone: contact_phone = extract_phone(line)
        if (low.startswith("site") or low.startswith("website")) and not contact_website: contact_website = extract_website(line)
        if not contact_email: contact_email = extract_email(line)
    if not contact_phone: contact_phone = extract_phone(contact_block_text)
    if not contact_email: contact_email = extract_email(contact_block_text)
    if not contact_website: contact_website = extract_website(contact_block_text)
    return {"contact_phone": contact_phone, "contact_email": contact_email, "contact_website": contact_website}

def is_non_product_name(line):
    low = (line or "").lower()
    return any(x in low for x in ["total amount", "montant total", "tickets", "billets", "transportation", "pay with friends", "details", "sold out", "upcoming", "contact organizer", "view my itenary", "view my itinerary", "log in", "register now", "starting from", "conditions", "cgv", "contact", "share", "location"])

def normalize_product_key(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

def product_name_score(name):
    low = (name or "").lower()
    score = 0
    if 3 <= len(name or "") <= 80: score += 2
    if any(k in low for k in ["entry", "ticket", "pass", "free", "single", "general", "admission", "prévente", "reservation", "réservation"]): score += 3
    if any(k in low for k in ["total", "details", "contact", "share", "location", "description"]): score -= 3
    return score

def dedupe_products(products):
    best = {}
    for p in products:
        norm_name = normalize_product_key(p.get("product_name"))
        price = p.get("numeric_price")
        key = (norm_name, price)
        candidate_score = product_name_score(p.get("product_name"))
        if key not in best or candidate_score > best[key][0] or (candidate_score == best[key][0] and len(p.get("product_name") or "") < len(best[key][1].get("product_name") or "")):
            best[key] = (candidate_score, p)
    return [item[1] for item in best.values()]

def extract_products_from_dom(soup):
    products = []
    raw_seen = set()
    for div in soup.find_all(["div", "section", "article", "li"]):
        text = normalize_text(div.get_text(" ", strip=True))
        if not text or "€" not in text or len(text) > 650:
            continue
        lines = [normalize_text(x) for x in div.get_text("\n", strip=True).splitlines() if normalize_text(x)]
        if not lines or len(lines) > 12:
            continue
        price_lines = [x for x in lines if parse_price(x) is not None and not is_non_product_name(x)]
        if len(price_lines) != 1:
            continue
        price_line = price_lines[0]
        price = parse_price(price_line)
        price_idx = lines.index(price_line)
        name = None
        search_before = lines[max(0, price_idx - 3):price_idx]
        for line in reversed(search_before):
            if parse_price(line) is None and len(line) < 120 and not is_non_product_name(line):
                name = line
                break
        if not name:
            continue
        if name.lower() == price_line.lower():
            continue
        blob = " ".join(lines).lower()
        is_available = True
        if any(w in blob for w in ["sold out", "épuisé", "indisponible", "complet"]):
            is_available = False
        elif any(w in blob for w in ["upcoming", "à venir"]):
            is_available = None
        key = (normalize_product_key(name), price_line)
        if key in raw_seen:
            continue
        raw_seen.add(key)
        products.append({"product_name": name, "price_text": price_line, "numeric_price": price, "is_free": price == 0.0, "is_available": is_available})
    products = dedupe_products(products)
    products.sort(key=lambda p: (not p["is_free"], p["numeric_price"] if p["numeric_price"] is not None else 999999, -(product_name_score(p.get("product_name")))))
    return products

def build_event_from_item(item, session=None):
    url = item["url"]; region = item["region"]; slug = item.get("slug"); external_id = item.get("external_id"); html = fetch_html(url, session=session); soup = remove_noise(BeautifulSoup(html, "html.parser")); lines = lines_from_soup(soup); header = extract_header_fields(soup); contact = extract_contact_info(soup, lines); products = extract_products_from_dom(soup); title = soup.title.get_text(" ", strip=True) if soup.title else url; name = header["name"] or normalize_text(title); image = extract_event_image(soup); description = extract_description(soup, lines)
    return {"event_url": url, "event_slug": slug, "event_external_id": external_id, "region": region, "name": name, "subtitle": header.get("subtitle"), "description": description, "event_date": header.get("event_date"), "city": header.get("city"), "address": header.get("address"), "contact_phone": contact["contact_phone"], "contact_email": contact["contact_email"], "contact_website": contact["contact_website"], "event_image": image, "products": products, "score": score_event(name, region, products, contact, bool(image), header.get("event_date"))}

def worker(item):
    session = requests.Session()
    try: return build_event_from_item(item, session=session)
    finally: session.close()

def record_product_change(cur, event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available):
    cur.execute("INSERT INTO product_history(event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available))

def upsert_event(event):
    c = conn(); cur = c.cursor(); cur.execute("SELECT id FROM events WHERE event_url = ?", (event["event_url"],)); row = cur.fetchone()
    if row:
        event_id = row["id"]; cur.execute("UPDATE events SET event_external_id=?, event_slug=?, region=?, name=?, subtitle=?, description=?, event_date=?, city=?, address=?, contact_phone=?, contact_email=?, contact_website=?, event_image=?, score=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("description"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0), event_id))
    else:
        cur.execute("INSERT INTO events(event_url, event_external_id, event_slug, region, name, subtitle, description, event_date, city, address, contact_phone, contact_email, contact_website, event_image, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event["event_url"], event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("description"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0))); event_id = cur.lastrowid
    for p in event.get("products", []):
        cur.execute("SELECT id, numeric_price, is_free, is_available FROM products WHERE event_id=? AND product_name=? AND price_text=?", (event_id, p.get("product_name"), p.get("price_text"))); old = cur.fetchone(); avail = 1 if p.get("is_available") is True else 0 if p.get("is_available") is False else None
        if old:
            old_price = old["numeric_price"]; old_is_free = old["is_free"]; old_is_available = old["is_available"]; cur.execute("UPDATE products SET numeric_price=?, is_free=?, is_available=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (p.get("numeric_price"), 1 if p.get("is_free") else 0, avail, old["id"]))
            if old_price != p.get("numeric_price") or old_is_free != (1 if p.get("is_free") else 0) or old_is_available != avail:
                change_type = "STATUS_CHANGE"
                if old_price != p.get("numeric_price"): change_type = "PRICE_CHANGE"
                elif old_is_available != avail: change_type = "AVAILABILITY_CHANGE"
                elif old_is_free != (1 if p.get("is_free") else 0): change_type = "FREE_CHANGE"
                record_product_change(cur, event_id, p.get("product_name"), change_type, old_price, p.get("numeric_price"), old_is_free, 1 if p.get("is_free") else 0, old_is_available, avail)
        else:
            cur.execute("INSERT INTO products(event_id, product_name, price_text, numeric_price, is_free, is_available) VALUES (?, ?, ?, ?, ?, ?)", (event_id, p.get("product_name"), p.get("price_text"), p.get("numeric_price"), 1 if p.get("is_free") else 0, avail)); record_product_change(cur, event_id, p.get("product_name"), "NEW_PRODUCT", None, p.get("numeric_price"), None, 1 if p.get("is_free") else 0, None, avail)
    c.commit(); c.close(); return event_id

def run():
    init_db(); regions = enabled_regions(); selected = list(regions.keys()); crawl_run_id = create_crawl_run(selected); save_status({"running": True, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": datetime.utcnow().isoformat(), "finished_at": None, "last_error": None}); all_items = []; processed = 0; errors = 0
    try:
        for region, start_url in regions.items():
            try:
                html = fetch_html(start_url); region_items = extract_event_links(html)
                for item in region_items: item["region"] = region
                all_items.extend(region_items)
            except Exception as exc:
                errors += 1; log_crawl_error(crawl_run_id, "region", region, exc)
        update_crawl_run(crawl_run_id, events_queued=len(all_items))
        if not all_items:
            update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="empty", errors_count=errors, notes="No events found"); save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": "No events found"}); return
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(worker, item): item for item in all_items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    event = future.result(); event_id = upsert_event(event); save_event_ai_label(event_id, event); processed += 1
                except Exception as exc:
                    errors += 1; log_crawl_error(crawl_run_id, "event", item.get("url"), exc)
        update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="success", events_processed=processed, errors_count=errors); save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": None})
    except Exception as exc:
        errors += 1; log_crawl_error(crawl_run_id, "run", "global", exc); update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="failed", events_processed=processed, errors_count=errors, notes=str(exc)[:500]); save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": str(exc)}); raise


if __name__ == "__main__":
    run()
