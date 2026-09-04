import json
import os
import re
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ai_automation import enrich_event_labels
from config_store import load_config
from source_profiles import SOURCE_PROFILES, detect_source, normalize_event_url, parse_event_ref
from security import validate_external_url
from storage import atomic_write_json, connect_sqlite
from opportunity_scoring import (classify_product, ensure_opportunity_schema,
                                 product_identity_key, record_price_variation,
                                 refresh_family_opportunities)
from bizouk_quality import (
    EventValidationError,
    QualityReport,
    clean_subtitle,
    clean_text,
    normalize_event_date,
    normalize_guadeloupe_city,
    normalize_phone,
    page_rejection_reason,
    validate_bizouk_event,
)
from booking_jobs import ensure_booking_jobs_schema

DB_PATH = "data/eventcrawler.sqlite"
BIZOUK_BASE_URL = "https://www.bizouk.com"
KIWOL_BASE_URL = "https://www.kiwol.com"
URL_RE = re.compile(r"https?://[^\s]+", re.I)
STATUS_PATH = Path("data/crawl_status.json")
CONFIG = load_config()
HEADERS = {"User-Agent": CONFIG.get("user_agent", "Mozilla/5.0")}
MAX_WORKERS = int(CONFIG.get("max_workers", 6))
REQUEST_TIMEOUT = int(CONFIG.get("request_timeout", 45))
AI_ENRICH_ENABLED = os.getenv("AI_ENRICH_ENABLED", "1") != "0"


def save_status(data):
    atomic_write_json(STATUS_PATH, data)


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
    return connect_sqlite(DB_PATH)


def ensure_column(cur, table, column, ddl):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def stable_text_key(value):
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unknown"


def stable_product_key(source, product_name, numeric_price):
    return product_identity_key(source, product_name)


def normalize_text(text):
    return clean_text(text) or ""


def digits_only_count(text):
    return len(re.sub(r"\D", "", text or ""))


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
    ensure_opportunity_schema(cur)
    ensure_booking_jobs_schema(cur)
    for col, ddl in [
        ("event_external_id", "event_external_id TEXT"),
        ("event_slug", "event_slug TEXT"),
        ("event_end_date", "event_end_date TEXT"),
        ("contact_website", "contact_website TEXT"),
        ("event_image", "event_image TEXT"),
        ("subtitle", "subtitle TEXT"),
        ("description", "description TEXT"),
        ("manual_status", "manual_status TEXT"),
        ("private_note", "private_note TEXT"),
        ("is_watchlisted", "is_watchlisted INTEGER DEFAULT 0"),
        ("source", "source TEXT DEFAULT 'bizouk'"),
        ("event_url_normalized", "event_url_normalized TEXT"),
    ]:
        ensure_column(cur, "events", col, ddl)
    for col, ddl in [
        ("source", "source TEXT DEFAULT 'bizouk'"),
        ("product_key", "product_key TEXT"),
        ("family_key", "family_key TEXT"),
        ("early_bird_score", "early_bird_score INTEGER DEFAULT 0"),
        ("is_early_bird", "is_early_bird INTEGER DEFAULT 0"),
        ("early_bird_confidence", "early_bird_confidence TEXT"),
        ("early_bird_reason", "early_bird_reason TEXT"),
        ("capacity", "capacity INTEGER"),
        ("product_kind", "product_kind TEXT"),
        ("unit_price", "unit_price REAL"),
    ]:
        ensure_column(cur, "products", col, ddl)

    rows = cur.execute("SELECT id, event_url, COALESCE(source, '') AS source FROM events").fetchall()
    for row in rows:
        source = row["source"] or detect_source(row["event_url"])
        cur.execute(
            "UPDATE events SET source=?, event_url_normalized=? WHERE id=?",
            (source, normalize_event_url(row["event_url"], source), row["id"]),
        )
    products = cur.execute("SELECT id, event_id, product_name, numeric_price, COALESCE(source, '') AS source FROM products").fetchall()
    for row in products:
        source = row["source"]
        if not source:
            ev = cur.execute("SELECT COALESCE(source, 'bizouk') AS source FROM events WHERE id=?", (row["event_id"],)).fetchone()
            source = ev["source"] if ev else "bizouk"
        product_key = stable_product_key(source, row["product_name"], row["numeric_price"])
        classification = classify_product(row["product_name"])
        unit_price = (row["numeric_price"] / classification["capacity"]) if row["numeric_price"] is not None and classification["capacity"] else row["numeric_price"]
        cur.execute("UPDATE products SET source=?, product_key=?, family_key=?, capacity=?, product_kind=?, unit_price=?, is_early_bird=?, early_bird_score=?, early_bird_confidence=?, early_bird_reason=? WHERE id=?",
                    (source, product_key, classification["family_key"], classification["capacity"], classification["kind"], unit_price, classification["is_early_bird"], classification["early_bird_score"], classification["early_bird_confidence"], classification["early_bird_reason"], row["id"]))

    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_source_external_id ON events(source, event_external_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_source_normalized_url ON events(source, event_url_normalized)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_event_product_key ON products(event_id, product_key)")
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
    c = conn()
    cur = c.cursor()
    cur.execute("INSERT INTO crawl_runs(mode, regions, status) VALUES (?, ?, ?)", ("manual", ",".join(regions), "running"))
    run_id = cur.lastrowid
    c.commit()
    c.close()
    return run_id


def update_crawl_run(run_id, **fields):
    if not fields:
        return
    c = conn()
    keys = list(fields.keys())
    sql = "UPDATE crawl_runs SET " + ", ".join([f"{k}=?" for k in keys]) + " WHERE id=?"
    c.execute(sql, [fields[k] for k in keys] + [run_id])
    c.commit()
    c.close()


def log_crawl_error(run_id, scope, target, error_text):
    c = conn()
    c.execute(
        "INSERT INTO crawl_errors(crawl_run_id, scope, target, error_text) VALUES (?, ?, ?, ?)",
        (run_id, scope, target, str(error_text)[:2000]),
    )
    c.commit()
    c.close()


def parse_price(text):
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:€|eur|euro)?", t)
    return float(m.group(1)) if m else None


def price_text_from_value(value, currency="EUR"):
    price = parse_price(value)
    if price is None:
        return normalize_text(str(value or "")) or None
    suffix = "€" if str(currency or "").upper() == "EUR" else str(currency or "").upper()
    if price == 0:
        return f"0 {suffix}".strip()
    if float(price).is_integer():
        return f"{int(price)} {suffix}".strip()
    return f"{price:.2f} {suffix}".strip()


def extract_email(text):
    m = re.search(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", text or "", re.I)
    return m.group(1) if m else None


def extract_phone(text):
    candidates = re.findall(r"(['\"]?(?:\+|00)?\d[\d\s().'\"-]{7,}\d)", text or "")
    for cand in candidates:
        normalized = normalize_phone(cand)
        if normalized:
            return normalized
    return None


def extract_website(text):
    for url in URL_RE.findall(text or ""):
        cleaned = url.rstrip(').,;]')
        if "bizouk.com" not in cleaned.lower() and "kiwol.com" not in cleaned.lower():
            return cleaned
    return None


def extract_event_image(soup, base_url=BIZOUK_BASE_URL):
    # Bizouk exposes the exact flyer displayed by the event page in this
    # stable hero container. Store that ``src`` as-is instead of substituting
    # a social preview, a thumbnail, or a reconstructed URL.
    hero_flyer = soup.select_one("#evh-hero-flyer img[src], .evh-hero-flyer img[src]")
    if hero_flyer:
        return urljoin(base_url, hero_flyer.get("src"))

    # Prefer links explicitly exposed as the original/full-size asset.  The
    # regular ``src`` often points at a thumbnail generated for the page and
    # can therefore already be cropped before we ever store it.
    original_attributes = ("data-original", "data-full", "data-full-src", "data-image")
    for img in soup.find_all("img"):
        src = next((img.get(attr) for attr in original_attributes if img.get(attr)), "")
        if not src:
            continue
        return urljoin(base_url, src)

    # Social metadata normally references the source flyer rather than a
    # responsive display derivative.  Keep its URL byte-for-byte (apart from
    # resolving a relative URL): query parameters are intentionally retained.
    for selector in (
        {"property": "og:image:secure_url"},
        {"property": "og:image"},
        {"name": "twitter:image"},
    ):
        meta = soup.find("meta", attrs=selector)
        if meta and meta.get("content"):
            return urljoin(base_url, meta.get("content"))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        full = urljoin(base_url, src)
        low = full.lower()
        if any(k in low for k in ["flyer", "affiche", "uploads", "/img/", "cloudfront", "thumbnail"]):
            return full
    return None


def extract_description(soup, lines):
    # The meta/JSON-LD description is shortened by Bizouk.  The complete,
    # server-rendered event copy lives in this stable container.
    description_node = soup.select_one("#party_description")
    if description_node:
        text = clean_text(description_node.get_text("\n", strip=True), multiline=True)
        if text:
            return text[:4000]
    for i, line in enumerate(lines):
        low = line.lower()
        if low in {"description", "descriptif", "about", "details"}:
            block = []
            for nxt in lines[i + 1:i + 30]:
                nxt_low = nxt.lower()
                if nxt_low in {"contact", "tickets", "billets", "produits", "products", "location", "lieu", "organisateur"}:
                    break
                if len(nxt) > 2:
                    block.append(nxt)
            text = normalize_text(" ".join(block))
            if len(text) >= 30:
                return text[:4000]
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        text = normalize_text(meta.get("content"))
        if text:
            return text[:4000]
    return None


def score_event(name, region, products, contact, has_image, event_date):
    score = 0
    low = (name or "").lower()
    if any(k in low for k in ["carnaval", "carnival", "jouvert", "boat", "pre-registration", "pré-inscription", "dreamland"]):
        score += 30
    if region in {"london", "rotterdam", "paris", "guadeloupe", "kiwol_guadeloupe"}:
        score += 15
    if any(p.get("is_free") for p in products):
        score += 15
    if any(p.get("is_free") and p.get("is_available") is True for p in products):
        score += 25
    if contact.get("contact_phone") or contact.get("contact_email") or contact.get("contact_website"):
        score += 10
    if has_image:
        score += 5
    if event_date:
        score += 5
    return min(score, 100)


def fetch_html(url, session=None):
    client = session or requests
    current = validate_external_url(url)
    for _ in range(5):
        response = client.get(current, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                response.raise_for_status()
            current = validate_external_url(urljoin(current, location))
            continue
        response.raise_for_status()
        return response.text
    raise requests.TooManyRedirects("trop de redirections")


def fetch_rendered_bizouk_html(url):
    safe_url = validate_external_url(url)
    helper = Path(__file__).with_name("render_event_page.js")
    result = subprocess.run(
        ["node", str(helper), safe_url],
        capture_output=True,
        text=True,
        timeout=max(REQUEST_TIMEOUT, 60),
        check=True,
    )
    return result.stdout


def bizouk_page_needs_rendering(soup):
    profile = SOURCE_PROFILES["bizouk"]
    has_header = bool(soup.select_one("h1, [itemprop='name'], [class*='event-title']"))
    has_products = any(soup.select_one(selector) for selector in profile.product_selectors)
    structured_event = extract_jsonld_event(soup)
    has_structured_products = bool(structured_event and offers_to_list(structured_event.get("offers")))
    return not has_header or (not has_products and not has_structured_products)


def extract_event_links(html, start_url=None):
    source = detect_source(start_url or "")
    profile = SOURCE_PROFILES[source]
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    selector = ", ".join(profile.event_link_selectors)
    for a in soup.select(selector):
        href = a.get("href") or ""
        if profile.event_path_marker not in href:
            continue
        full = normalize_event_url(urljoin(profile.base_url, href), source)
        ref = parse_event_ref(full, source=source)
        if not ref:
            continue
        item = {"url": full, **ref}
        if source == "kiwol":
            title_el = a.select_one(".ticketing-card-title")
            date_el = a.select_one(".ticketing-card-date")
            location_el = a.select_one(".ticketing-card-location")
            item.update({
                "list_title": normalize_text(title_el.get_text(" ", strip=True)) if title_el else None,
                "list_date": normalize_text(date_el.get_text(" ", strip=True)) if date_el else None,
                "list_location": normalize_text(location_el.get_text(" ", strip=True)) if location_el else None,
            })
        out[f"{source}:{ref['external_id']}"] = item
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
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "janvier", "février", "fevrier", "mars", "avril", "mai", "juin", "juillet", "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre"]
    has_month = any(month in low for month in months)
    has_day = bool(re.search(r"\b(?:[0-2]?\d|3[01])(?:er|st|nd|rd|th)?\b", low))
    has_time = bool(re.search(r"\b\d{1,2}(?::\d{2}|\s*h(?:\s*\d{2})?|\s*(?:am|pm))\b", low))
    return has_month and (has_day or has_time)


def extract_header_fields(soup):
    h1 = soup.select_one(".evh-hero h1.evh-hero-title, h1.evh-hero-title, [itemtype$='/Event'] [itemprop='name']") or soup.find("h1")
    h2 = soup.select_one(".evh-hero .evh-hero-subtitle, .evh-hero-subtitle") or soup.find("h2")
    name = normalize_text(h1.get_text(" ", strip=True)) if h1 else None
    subtitle = clean_subtitle(h2.get_text(" ", strip=True)) if h2 else None
    hero_meta = soup.select_one(".evh-hero-meta")
    date_node = soup.select_one("time[datetime], [itemprop='startDate']")
    if not date_node and hero_meta:
        date_node = next((node for node in hero_meta.select(".evh-hero-meta-item") if node.select_one(".fa-calendar")), None)
    date_node = date_node or soup.select_one("[class*='event-date'], [class*='date'], [class*='time']")
    location_node = soup.select_one("[itemprop='addressLocality']")
    location_node = location_node or soup.select_one("[itemprop='location']")
    if not location_node and hero_meta:
        location_node = next((node for node in hero_meta.select(".evh-hero-meta-item") if node.select_one(".fa-map-marker")), None)
    location_node = location_node or soup.select_one(".evh-hero [class*='event-location'], [itemtype$='/Event'] [class*='location']")
    address_node = soup.select_one("[itemprop='streetAddress'], address, [class*='event-address'], [class*='address']")
    date_text = normalize_text(date_node.get_text(" ", strip=True)) if date_node else None
    city = normalize_text(location_node.get_text(" ", strip=True)) if location_node else None
    address = normalize_text(address_node.get_text(" ", strip=True)) if address_node else None
    if city and "·" in city:
        # Current Bizouk hero renders "venue · commune". Keep the venue apart.
        venue, city = [normalize_text(part) for part in city.rsplit("·", 1)]
        address = venue or address
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


def extract_contact_info(soup, lines):
    panel = soup.select_one(".evh-contact-panel")
    if panel:
        phone_row = panel.select_one(".fa-phone")
        email_link = panel.select_one("a[href^='mailto:']")
        website_link = panel.select_one(".fa-globe")
        phone_text = phone_row.parent.get_text(" ", strip=True) if phone_row and phone_row.parent else ""
        website_anchor = website_link.parent.select_one("a[href]") if website_link and website_link.parent else None
        return {
            "contact_phone": extract_phone(phone_text),
            "contact_email": (email_link.get("href") or "").removeprefix("mailto:") or None if email_link else None,
            "contact_website": website_anchor.get("href") if website_anchor else None,
        }
    candidate_lines = []
    for i, line in enumerate(lines):
        low = line.lower()
        if low == "contact" or low.startswith("contact ") or "contact organizer" in low:
            candidate_lines.extend(lines[i:i + 25])
    if not candidate_lines:
        for i, line in enumerate(lines):
            low = line.lower()
            if "infoline" in low or "whatsapp" in low or low.startswith("site") or low.startswith("website"):
                candidate_lines.extend(lines[max(0, i - 2):i + 8])
    seen = set()
    candidate_lines = [x for x in candidate_lines if not (x in seen or seen.add(x))]
    contact_block_text = "\n".join(candidate_lines)
    contact_phone = None
    contact_email = None
    contact_website = None
    for line in candidate_lines:
        low = line.lower()
        if ("infoline" in low or "whatsapp" in low or low.startswith("phone")) and not contact_phone:
            contact_phone = extract_phone(line)
        if (low.startswith("site") or low.startswith("website")) and not contact_website:
            contact_website = extract_website(line)
        if not contact_email:
            contact_email = extract_email(line)
    return {
        "contact_phone": contact_phone or extract_phone(contact_block_text),
        "contact_email": contact_email or extract_email(contact_block_text),
        "contact_website": contact_website or extract_website(contact_block_text),
    }


def is_non_product_name(line):
    low = (line or "").lower()
    return any(x in low for x in ["total amount", "montant total", "tickets", "billets", "transportation", "pay with friends", "details", "sold out", "upcoming", "contact organizer", "view my itenary", "view my itinerary", "log in", "register now", "starting from", "conditions", "cgv", "contact", "share", "location"])


def product_name_score(name):
    low = (name or "").lower()
    score = 0
    if 3 <= len(name or "") <= 80:
        score += 2
    if any(k in low for k in ["entry", "ticket", "billet", "pass", "free", "gratuit", "single", "general", "admission", "prévente", "reservation", "réservation"]):
        score += 3
    if any(k in low for k in ["total", "details", "contact", "share", "location", "description"]):
        score -= 3
    return score


def dedupe_products(products, source="bizouk"):
    best = {}
    for p in products:
        p["source"] = p.get("source") or source
        p["product_key"] = p.get("product_key") or stable_product_key(p["source"], p.get("product_name"), p.get("numeric_price"))
        candidate_score = product_name_score(p.get("product_name"))
        key = p["product_key"]
        if key not in best or candidate_score > best[key][0] or (candidate_score == best[key][0] and len(p.get("product_name") or "") < len(best[key][1].get("product_name") or "")):
            best[key] = (candidate_score, p)
    return [item[1] for item in best.values()]


def availability_from_node(node, blob):
    low = blob.lower()
    # Quantity minus buttons are disabled while the cart quantity is zero; it
    # does not mean that a Bizouk tariff is unavailable.
    disabled = node.has_attr("disabled") or str(node.get("aria-disabled", "")).lower() == "true" or bool(node.select_one("[aria-disabled='true'], input[disabled], button.qty-plus[disabled]"))
    if disabled or any(word in low for word in ["sold out", "épuisé", "epuise", "indisponible", "complet"]):
        return False
    if any(word in low for word in ["upcoming", "à venir", "a venir"]):
        return None
    return True


def product_from_node(node, source, profile=None):
    lines = lines_from_node(node)
    blob = " ".join(lines)
    price_node = None
    if profile:
        for selector in profile.price_selectors:
            price_node = node.select_one(selector)
            if price_node:
                break
    price_value = None
    if price_node:
        price_value = price_node.get("data-base-price")
        if price_value is None:
            price_value = price_node.get("data-price")
    price_text = normalize_text(price_node.get_text(" ", strip=True)) if price_node else None
    price = parse_price(price_value if price_value is not None else price_text)
    if price is None:
        candidates = [line for line in lines if re.search(r"(?:€|\beur\b|\beuros?\b|\bgratuit\b|\bfree\b)", line, re.I)]
        if candidates:
            price_text = candidates[0]
            price = parse_price(price_text)
    if price is None:
        return None
    name = None
    if source == "bizouk":
        # The label is the span immediately before Bizouk's details control.
        # Names often contain a time ("avant 17H") or a capacity
        # ("4 personnes"), so the generic ``parse_price`` name filter cannot
        # safely be used for these explicit labels.
        detail = node.select_one(".priceDetail[product]")
        label = detail.find_previous_sibling("span") if detail else None
        if label:
            name = normalize_text(label.get_text(" ", strip=True))
    if profile:
        for selector in profile.product_name_selectors if not name else ():
            name_node = node.select_one(selector)
            if name_node:
                candidate = normalize_text(name_node.get_text(" ", strip=True))
                if candidate and parse_price(candidate) is None and not is_non_product_name(candidate):
                    name = candidate
                    break
    if not name:
        for line in lines:
            if line != price_text and parse_price(line) is None and len(line) < 120 and not is_non_product_name(line):
                name = line
                break
    if not name:
        return None
    return {"source": source, "product_key": stable_product_key(source, name, price), "product_name": name, "price_text": price_text_from_value(price, "EUR") or price_text, "numeric_price": price, "is_free": price == 0.0, "is_available": availability_from_node(node, blob)}


def extract_products_from_dom(soup, source="bizouk"):
    products = []
    raw_seen = set()
    profile = SOURCE_PROFILES.get(source)
    targeted_nodes = []
    if profile:
        for selector in profile.product_selectors:
            targeted_nodes.extend(soup.select(selector))
    # Prefer leaf-most ticket cards: parents commonly aggregate several prices.
    targeted_ids = {id(node) for node in targeted_nodes}
    leaf_nodes = [node for node in targeted_nodes if not any(id(child) in targeted_ids for child in node.find_all())]
    if source == "bizouk":
        ticket_nodes = []
        for price_node in soup.select(".produit_prix[data-product-price]"):
            card = price_node.find_parent(class_="panel-body") or price_node.parent
            if card and card not in ticket_nodes:
                ticket_nodes.append(card)
        leaf_nodes = ticket_nodes or leaf_nodes
    for node in leaf_nodes:
        product = product_from_node(node, source, profile)
        if product and product["product_key"] not in raw_seen:
            raw_seen.add(product["product_key"])
            products.append(product)
    # Never infer products from arbitrary price-looking content on the event
    # page. Menus, transport, parking and promotional copy can all contain a
    # price even when the event has no tickets. A DOM product must therefore
    # live inside one of the source profile's explicit product selectors;
    # structured Event offers are handled separately by the JSON-LD extractor.
    products = dedupe_products(products, source)
    products.sort(key=lambda p: (not p["is_free"], p["numeric_price"] if p["numeric_price"] is not None else 999999, -(product_name_score(p.get("product_name")))))
    return products


def extract_jsonld_event(soup):
    def walk(value):
        if isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, dict):
            types = value.get("@type") or []
            types = types if isinstance(types, list) else [types]
            if any(str(item).lower().endswith("event") for item in types):
                yield value
            for key, child in value.items():
                if key != "@context":
                    yield from walk(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.get_text(strip=True)
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        for item in walk(data):
            return item
    return None


def format_kiwol_event_date(json_event, fallback=None):
    if not json_event:
        return fallback
    schedule = json_event.get("eventSchedule") or {}
    start_date = schedule.get("startDate") or json_event.get("startDate")
    end_date = schedule.get("endDate") or json_event.get("endDate")
    start_time = schedule.get("startTime")
    end_time = schedule.get("endTime")
    parts = []
    if start_date:
        parts.append(str(start_date))
    if end_date and end_date != start_date:
        parts.append(f"au {end_date}")
    if start_time:
        time_part = str(start_time)[:5]
        if end_time:
            time_part += f"-{str(end_time)[:5]}"
        parts.append(time_part)
    return " ".join(parts) or fallback


def offers_to_list(offers):
    if not offers:
        return []
    if isinstance(offers, list):
        return offers
    nested = offers.get("offers") if isinstance(offers, dict) else None
    if isinstance(nested, list):
        return nested
    if isinstance(offers, dict) and offers.get("@type") == "Offer":
        return [offers]
    return []


def extract_products_from_jsonld(json_event, source="kiwol"):
    products = []
    aggregate = json_event.get("offers") if isinstance(json_event, dict) else None
    default_currency = aggregate.get("priceCurrency") if isinstance(aggregate, dict) else "EUR"
    for offer in offers_to_list(aggregate):
        if not isinstance(offer, dict):
            continue
        currency = offer.get("priceCurrency") or default_currency or "EUR"
        price = parse_price(offer.get("price"))
        product_name = normalize_text(offer.get("name")) or "Billet"
        availability = str(offer.get("availability") or "").lower()
        is_available = True
        if availability:
            is_available = "instock" in availability or "in_stock" in availability
            if any(k in availability for k in ["soldout", "outofstock", "discontinued"]):
                is_available = False
        products.append({
            "source": source,
            "product_key": stable_product_key(source, product_name, price),
            "product_name": product_name,
            "price_text": price_text_from_value(offer.get("price"), currency),
            "numeric_price": price,
            "is_free": price == 0.0 or "free" in product_name.lower() or "gratuit" in product_name.lower(),
            "is_available": is_available,
        })
    return dedupe_products(products, source)


def jsonld_event_fields(json_event):
    if not isinstance(json_event, dict):
        return {}
    location = json_event.get("location") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address") if isinstance(location, dict) else {}
    if isinstance(address, str):
        address = {"streetAddress": address}
    organizer = json_event.get("organizer") or {}
    if isinstance(organizer, list):
        organizer = organizer[0] if organizer else {}
    image = json_event.get("image")
    if isinstance(image, list):
        # Schema.org permits several renditions. Prefer an explicitly named
        # original/full-size rendition, then the largest declared rendition,
        # instead of blindly keeping the first (often a cropped thumbnail).
        def image_rank(candidate):
            if not isinstance(candidate, dict):
                return (0, 0)
            label = " ".join(str(candidate.get(key) or "") for key in ("name", "caption", "@id")).lower()
            original = int(any(word in label for word in ("original", "full", "source")))
            try:
                area = int(candidate.get("width") or 0) * int(candidate.get("height") or 0)
            except (TypeError, ValueError):
                area = 0
            return (original, area)

        image = max(image, key=image_rank) if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    return {
        "name": normalize_text(json_event.get("name")),
        "description": normalize_text(json_event.get("description"))[:4000] or None,
        "event_date": clean_text(json_event.get("startDate")) or format_kiwol_event_date(json_event),
        "event_end_date": clean_text(json_event.get("endDate")),
        "subtitle": normalize_text(organizer.get("name")) if isinstance(organizer, dict) else None,
        "city": normalize_text(address.get("addressLocality")) if isinstance(address, dict) else None,
        "address": normalize_text(address.get("streetAddress")) if isinstance(address, dict) else None,
        "venue": normalize_text(location.get("name")) if isinstance(location, dict) else None,
        "image": image,
    }


def build_kiwol_event_from_item(item, session=None):
    source = "kiwol"
    url = normalize_event_url(item["url"], source)
    region = item["region"]
    slug = item.get("slug")
    external_id = item.get("external_id")
    html = fetch_html(url, session=session)
    raw_soup = BeautifulSoup(html, "html.parser")
    json_event = extract_jsonld_event(raw_soup)
    soup = remove_noise(raw_soup)
    lines = lines_from_soup(soup)
    h1 = soup.find("h1")
    name = normalize_text(h1.get_text(" ", strip=True)) if h1 else None
    if not name and json_event:
        name = normalize_text(str(json_event.get("name") or "").replace("| Kiwol", ""))
    description = normalize_text(json_event.get("description"))[:4000] if json_event and json_event.get("description") else extract_description(soup, lines)
    location = json_event.get("location") if isinstance(json_event, dict) else {}
    address_data = location.get("address") if isinstance(location, dict) else {}
    venue_name = normalize_text(location.get("name")) if isinstance(location, dict) else None
    street = normalize_text(address_data.get("streetAddress")) if isinstance(address_data, dict) else None
    city = normalize_text(address_data.get("addressLocality")) if isinstance(address_data, dict) else None
    organizer = json_event.get("organizer") if isinstance(json_event, dict) else {}
    organizer_name = normalize_text(organizer.get("name")) if isinstance(organizer, dict) else None
    products = extract_products_from_jsonld(json_event or {}, source) or extract_products_from_dom(soup, source)
    event_date = format_kiwol_event_date(json_event or {}, item.get("list_date"))
    image = extract_event_image(soup, base_url=KIWOL_BASE_URL)
    all_text = "\n".join(lines)
    contact = {"contact_phone": extract_phone(all_text), "contact_email": extract_email(all_text), "contact_website": None}
    return {"source": source, "event_url": url, "event_url_normalized": normalize_event_url(url, source), "event_slug": slug, "event_external_id": external_id, "region": region, "name": name or item.get("list_title") or url, "subtitle": organizer_name or item.get("list_location"), "description": description, "event_date": event_date, "city": city or item.get("list_location"), "address": street or venue_name, "contact_phone": contact["contact_phone"], "contact_email": contact["contact_email"], "contact_website": contact["contact_website"], "event_image": image, "products": products, "score": score_event(name, region, products, contact, bool(image), event_date)}


def build_event_from_item(item, session=None):
    if item.get("source") == "kiwol" or detect_source(item.get("url")) == "kiwol":
        return build_kiwol_event_from_item(item, session=session)
    source = "bizouk"
    url = normalize_event_url(item["url"], source)
    region = item["region"]
    slug = item.get("slug")
    external_id = item.get("external_id")
    html = fetch_html(url, session=session)
    raw_soup = BeautifulSoup(html, "html.parser")
    if bizouk_page_needs_rendering(raw_soup):
        try:
            raw_soup = BeautifulSoup(fetch_rendered_bizouk_html(url), "html.parser")
        except (subprocess.SubprocessError, OSError):
            pass
    rejection = page_rejection_reason(raw_soup)
    if rejection:
        raise EventValidationError([rejection])
    json_event = extract_jsonld_event(raw_soup)
    structured = jsonld_event_fields(json_event)
    soup = remove_noise(raw_soup)
    lines = lines_from_soup(soup)
    header = extract_header_fields(soup)
    contact = extract_contact_info(soup, lines)
    # The DOM contains base prices and sold-out tariffs. Bizouk's JSON-LD
    # instead exposes fee-inclusive prices and omits unavailable products.
    products = extract_products_from_dom(soup, source) or extract_products_from_jsonld(json_event or {}, source)
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    name = structured.get("name") or header["name"] or normalize_text(title)
    # The hero's <img src> is Bizouk's canonical displayed flyer. JSON-LD can
    # point to a differently cropped social rendition, so use it only if the
    # page does not contain the hero flyer.
    image = extract_event_image(soup, base_url=BIZOUK_BASE_URL) or structured.get("image")
    description = extract_description(soup, lines) or structured.get("description")
    raw_city = structured.get("city") or header.get("city")
    city = normalize_guadeloupe_city(raw_city)
    if not city and region not in {"guadeloupe", "kiwol_guadeloupe"}:
        city = clean_text(raw_city)
    event_date = normalize_event_date(structured.get("event_date") or header.get("event_date"), region=region, city=city)
    event_end_date = normalize_event_date(structured.get("event_end_date"), region=region, city=city)
    address = structured.get("address") or structured.get("venue") or header.get("address")
    subtitle = clean_subtitle(header.get("subtitle") or structured.get("subtitle"))
    event = {"source": source, "event_url": url, "event_url_normalized": normalize_event_url(url, source), "event_slug": slug, "event_external_id": external_id, "region": region, "name": clean_text(name), "subtitle": subtitle, "description": clean_text(description, multiline=True), "event_date": event_date, "event_end_date": event_end_date, "city": city, "address": clean_text(address), "contact_phone": normalize_phone(contact["contact_phone"]), "contact_email": contact["contact_email"], "contact_website": contact["contact_website"], "event_image": image, "products": products, "score": score_event(name, region, products, contact, bool(image), event_date)}
    return validate_bizouk_event(event)


def worker(item):
    session = requests.Session()
    try:
        return build_event_from_item(item, session=session)
    finally:
        session.close()


def record_product_change(cur, event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available):
    cur.execute("INSERT INTO product_history(event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (event_id, product_name, change_type, old_price, new_price, old_is_free, new_is_free, old_is_available, new_is_available))


def find_existing_event(cur, event):
    source = event.get("source") or detect_source(event.get("event_url"))
    normalized_url = event.get("event_url_normalized") or normalize_event_url(event.get("event_url"), source)
    if event.get("event_external_id"):
        row = cur.execute("SELECT id FROM events WHERE COALESCE(source, 'bizouk')=? AND event_external_id=? ORDER BY id ASC LIMIT 1", (source, event.get("event_external_id"))).fetchone()
        if row:
            return row
    row = cur.execute("SELECT id FROM events WHERE COALESCE(source, 'bizouk')=? AND COALESCE(event_url_normalized, event_url)=? ORDER BY id ASC LIMIT 1", (source, normalized_url)).fetchone()
    if row:
        return row
    return cur.execute("SELECT id FROM events WHERE event_url=? ORDER BY id ASC LIMIT 1", (event.get("event_url"),)).fetchone()


def upsert_event(event):
    if (event.get("source") or detect_source(event.get("event_url"))) == "bizouk":
        validate_bizouk_event(event)
    c = conn()
    cur = c.cursor()
    source = event.get("source") or detect_source(event.get("event_url"))
    event["event_url_normalized"] = event.get("event_url_normalized") or normalize_event_url(event.get("event_url"), source)
    row = find_existing_event(cur, event)
    if row:
        event_id = row["id"]
        cur.execute("UPDATE events SET source=?, event_url=?, event_url_normalized=?, event_external_id=?, event_slug=?, region=?, name=?, subtitle=?, description=?, event_date=?, event_end_date=?, city=?, address=?, contact_phone=?, contact_email=?, contact_website=?, event_image=?, score=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (source, event.get("event_url"), event.get("event_url_normalized"), event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("description"), event.get("event_date"), event.get("event_end_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0), event_id))
    else:
        cur.execute("INSERT INTO events(source, event_url, event_url_normalized, event_external_id, event_slug, region, name, subtitle, description, event_date, event_end_date, city, address, contact_phone, contact_email, contact_website, event_image, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (source, event.get("event_url"), event.get("event_url_normalized"), event.get("event_external_id"), event.get("event_slug"), event.get("region"), event.get("name"), event.get("subtitle"), event.get("description"), event.get("event_date"), event.get("event_end_date"), event.get("city"), event.get("address"), event.get("contact_phone"), event.get("contact_email"), event.get("contact_website"), event.get("event_image"), event.get("score", 0)))
        event_id = cur.lastrowid
    for p in event.get("products", []):
        product_name = p.get("product_name") or "Billet"
        numeric_price = p.get("numeric_price")
        product_key = p.get("product_key") or stable_product_key(source, product_name, numeric_price)
        price_text = p.get("price_text") or price_text_from_value(numeric_price, "EUR")
        avail = 1 if p.get("is_available") is True else 0 if p.get("is_available") is False else None
        is_free = 1 if p.get("is_free") else 0
        classification = classify_product(product_name)
        unit_price = (numeric_price / classification["capacity"]) if numeric_price is not None and classification["capacity"] else numeric_price
        old = cur.execute("SELECT id, numeric_price, is_free, is_available FROM products WHERE event_id=? AND product_key=? ORDER BY id ASC LIMIT 1", (event_id, product_key)).fetchone()
        if not old:
            old = cur.execute("SELECT id, numeric_price, is_free, is_available FROM products WHERE event_id=? AND product_name=? AND price_text=? ORDER BY id ASC LIMIT 1", (event_id, product_name, price_text)).fetchone()
        if old:
            old_price = old["numeric_price"]
            old_is_free = old["is_free"]
            old_is_available = old["is_available"]
            cur.execute("UPDATE products SET source=?, product_key=?, product_name=?, price_text=?, numeric_price=?, is_free=?, is_available=?, family_key=?, capacity=?, product_kind=?, unit_price=?, is_early_bird=?, early_bird_score=?, early_bird_confidence=?, early_bird_reason=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (source, product_key, product_name, price_text, numeric_price, is_free, avail, classification["family_key"], classification["capacity"], classification["kind"], unit_price, classification["is_early_bird"], classification["early_bird_score"], classification["early_bird_confidence"], classification["early_bird_reason"], old["id"]))
            if old_price != numeric_price or old_is_free != is_free or old_is_available != avail:
                change_type = "STATUS_CHANGE"
                if old_price != numeric_price:
                    change_type = "PRICE_CHANGE"
                elif old_is_available != avail:
                    change_type = "AVAILABILITY_CHANGE"
                elif old_is_free != is_free:
                    change_type = "FREE_CHANGE"
                record_product_change(cur, event_id, product_name, change_type, old_price, numeric_price, old_is_free, is_free, old_is_available, avail)
                if old_price != numeric_price:
                    record_price_variation(cur, event_id, old["id"], old_price, numeric_price)
        else:
            try:
                cur.execute("INSERT INTO products(event_id, source, product_key, product_name, price_text, numeric_price, is_free, is_available, family_key, capacity, product_kind, unit_price, is_early_bird, early_bird_score, early_bird_confidence, early_bird_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event_id, source, product_key, product_name, price_text, numeric_price, is_free, avail, classification["family_key"], classification["capacity"], classification["kind"], unit_price, classification["is_early_bird"], classification["early_bird_score"], classification["early_bird_confidence"], classification["early_bird_reason"]))
                product_id = cur.lastrowid
                record_product_change(cur, event_id, product_name, "NEW_PRODUCT", None, numeric_price, None, is_free, None, avail)
                if (CONFIG.get("booking_profile", {}).get("auto_book_new_free_products")
                        and numeric_price == 0 and is_free == 1 and avail == 1):
                    cur.execute("""INSERT OR IGNORE INTO booking_jobs
                                   (event_id, product_id, product_key, product_name)
                                   VALUES (?, ?, ?, ?)""",
                                (event_id, product_id, product_key, product_name))
            except sqlite3.IntegrityError:
                cur.execute("UPDATE products SET source=?, product_key=?, numeric_price=?, is_free=?, is_available=?, last_seen_at=CURRENT_TIMESTAMP WHERE event_id=? AND product_name=? AND price_text=?", (source, product_key, numeric_price, is_free, avail, event_id, product_name, price_text))
        if avail == 0:
            current = cur.execute(
                "SELECT id FROM products WHERE event_id=? AND product_key=? ORDER BY id LIMIT 1",
                (event_id, product_key),
            ).fetchone()
            if current:
                cur.execute(
                    """UPDATE price_opportunities
                       SET is_active=0, resolved_at=CURRENT_TIMESTAMP
                       WHERE event_id=? AND product_id=? AND is_active=1""",
                    (event_id, current["id"]),
                )
    refresh_family_opportunities(cur, event_id)
    c.commit()
    c.close()
    return event_id


def run():
    init_db()
    regions = enabled_regions()
    selected = list(regions.keys())
    crawl_run_id = create_crawl_run(selected)
    save_status({"running": True, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": datetime.utcnow().isoformat(), "finished_at": None, "last_error": None})
    all_items = []
    processed = 0
    errors = 0
    report = QualityReport()
    try:
        for region, start_url in regions.items():
            try:
                html = fetch_html(start_url)
                region_items = extract_event_links(html, start_url=start_url)
                for item in region_items:
                    item["region"] = region
                all_items.extend(region_items)
            except Exception as exc:
                errors += 1
                report.counts["http_errors"] += 1
                log_crawl_error(crawl_run_id, "region", region, exc)
        report.counts["duplicates"] = len(all_items) - len({(item.get("source"), item.get("external_id")) for item in all_items})
        report.counts["pages_processed"] = len(all_items)
        update_crawl_run(crawl_run_id, events_queued=len(all_items))
        if not all_items:
            update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="empty", errors_count=errors, notes="No events found")
            save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": "No events found"})
            return
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(worker, item): item for item in all_items}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    event = future.result()
                    event_id = upsert_event(event)
                    save_event_ai_label(event_id, event)
                    processed += 1
                    report.counts["valid_events"] += 1
                    report.counts["missing_fields"] += sum(not event.get(field) for field in ("subtitle", "description", "city", "contact_phone", "contact_website"))
                except Exception as exc:
                    errors += 1
                    report.reject(exc)
                    if isinstance(exc, requests.RequestException):
                        report.counts["http_errors"] += 1
                    if isinstance(exc, EventValidationError):
                        report.counts["unrecognized_cities"] += sum("city" in reason for reason in exc.errors)
                        report.counts["invalid_dates"] += sum("date" in reason for reason in exc.errors)
                    log_crawl_error(crawl_run_id, "event", item.get("url"), exc)
        update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="success", events_processed=processed, errors_count=errors, notes=json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
        save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": None})
    except Exception as exc:
        errors += 1
        log_crawl_error(crawl_run_id, "run", "global", exc)
        update_crawl_run(crawl_run_id, finished_at=datetime.utcnow().isoformat(), status="failed", events_processed=processed, errors_count=errors, notes=str(exc)[:500])
        save_status({"running": False, "regions": selected, "max_workers": MAX_WORKERS, "request_timeout": REQUEST_TIMEOUT, "started_at": None, "finished_at": datetime.utcnow().isoformat(), "last_error": str(exc)})
        raise


if __name__ == "__main__":
    run()
