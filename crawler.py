import re
import sqlite3
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DB_PATH = "data/eventcrawler.sqlite"
BASE_URL = "https://www.bizouk.com"
REGIONS = {
    "london": "https://www.bizouk.com/?region=london",
    "guadeloupe": "https://www.bizouk.com/?region=guadeloupe",
    "paris": "https://www.bizouk.com/?region=paris",
    "rotterdam": "https://www.bizouk.com/?region=rotterdam",
}
HEADERS = {"User-Agent": "Mozilla/5.0"}

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = conn()
    c.executescript(
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
    c.commit()
    c.close()

def normalize_text(text):
    return re.sub(r"\\s+", " ", (text or "").strip().lower())

def parse_price(text):
    if not text:
        return None
    t = text.strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t:
        return 0.0
    m = re.search(r"(\\d+(?:\\.\\d+)?)\\s*€", t)
    return float(m.group(1)) if m else None

def extract_email(text):
    m = re.search(r"([A-Z0-9._%+\\-]+@[A-Z0-9.\\-]+\\.[A-Z]{2,})", text, re.I)
    return m.group(1) if m else None

def extract_phone(text):
    m = re.search(r"(\\+?\\d[\\d\\s().-]{7,}\\d)", text)
    return re.sub(r"\\s+", " ", m.group(1)).strip() if m else None

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

def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.text

def extract_event_links(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "/events/details/" in href:
            out.append(urljoin(BASE_URL, href))
    return sorted(set(out))

def extract_products(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    out, seen = [], set()
    for i, line in enumerate(lines):
        price = parse_price(line)
        if price is None:
            continue
        name = None
        for back in range(1, 5):
            if i - back >= 0:
                cand = lines[i - back]
                if parse_price(cand) is None and len(cand) < 120:
                    name = cand
                    break
        if not name:
            continue
        around = normalize_text(" ".join(lines[i:i+6]))
        is_available = None
        if any(w in around for w in ["épuisé", "epuise", "sold out", "indisponible", "complet"]):
            is_available = False
        elif any(w in around for w in ["réserver", "reserver", "acheter", "ajouter", "inscription", "prendre"]):
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

def upsert_event(event):
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT id FROM events WHERE event_url = ?", (event["event_url"],))
    row = cur.fetchone()
    if row:
        event_id = row["id"]
        cur.execute(
            "UPDATE events SET region=?, name=?, event_date=?, city=?, address=?, contact_phone=?, contact_email=?, score=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?",
            (event.get("region"), event.get("name"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("score", 0), event_id),
        )
    else:
        cur.execute(
            "INSERT INTO events(event_url, region, name, event_date, city, address, contact_phone, contact_email, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event["event_url"], event.get("region"), event.get("name"), event.get("event_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("score", 0)),
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

def extract_event(url, region):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    name = next((x for x in lines[:20] if len(x) > 4 and "bizouk" not in x.lower()), title)
    city, address = None, None
    for cand in lines[:60]:
        low = cand.lower()
        if not city and any(k in low for k in ["londres", "london", "paris", "rotterdam", "guadeloupe"]):
            city = cand
            continue
        if not address and any(ch.isdigit() for ch in cand) and len(cand) > 8:
            address = cand
    products = extract_products(text)
    event = {
        "event_url": url,
        "region": region,
        "name": name,
        "event_date": next((x for x in lines[:40] if any(tok in x.lower() for tok in ["2026", "2025", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre", "am", "pm"])), None),
        "city": city,
        "address": address,
        "contact_phone": extract_phone(text),
        "contact_email": extract_email(text),
        "products": products,
        "score": score_event(name, region, products),
    }
    upsert_event(event)

def run():
    init_db()
    for region, start_url in REGIONS.items():
        try:
            html = fetch_html(start_url)
            for link in extract_event_links(html):
                try:
                    extract_event(link, region)
                    print(f"[OK] {region} -> {link}")
                except Exception as exc:
                    print(f"[ERROR] event {link}: {exc}")
        except Exception as exc:
            print(f"[ERROR] region {region}: {exc}")

if __name__ == "__main__":
    run()
