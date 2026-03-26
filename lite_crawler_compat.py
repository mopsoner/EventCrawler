import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REGIONS, BASE_URL
from confidence import compute_confidence
from db import init_db, upsert_event, save_page_snapshot, log_extraction_run
from scoring import compute_score
from validator import validate_event_payload

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def parse_price(text: str):
    if not text:
        return None
    t = text.strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*€", t)
    return float(m.group(1)) if m else None


def extract_email(text: str):
    m = re.search(r"([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})", text, re.I)
    return m.group(1) if m else None


def extract_phone(text: str):
    m = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.text


def extract_event_links(html: str):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "/events/details/" in href:
            links.append(urljoin(BASE_URL, href))
    return sorted(set(links))


def extract_flyers(soup):
    flyers = []
    for img in soup.select("img[src]"):
        src = img.get("src") or ""
        alt = (img.get("alt") or "").lower()
        full = urljoin(BASE_URL, src)
        ref = f"{alt} {full}".lower()
        if "flyer" in ref or "affiche" in ref:
            flyers.append(full)
    return sorted(set(flyers))


def extract_products_from_text(text: str):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    products = []
    seen = set()
    for i, line in enumerate(lines):
        price = parse_price(line)
        if price is None:
            continue
        name = None
        for back in range(1, 5):
            if i - back >= 0 and parse_price(lines[i - back]) is None and len(lines[i - back]) < 120:
                name = lines[i - back]
                break
        if not name:
            continue
        low_window = normalize_text(" ".join(lines[i:i+6]))
        is_available = None
        if any(w in low_window for w in ["épuisé", "epuise", "sold out", "indisponible", "complet"]):
            is_available = False
        elif any(w in low_window for w in ["réserver", "reserver", "acheter", "ajouter", "inscription", "prendre"]):
            is_available = True
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "product_name": name,
            "price_text": line,
            "numeric_price": price,
            "is_free": price == 0.0,
            "is_available": is_available,
            "availability_text": None,
            "buy_link": None,
            "details": " | ".join(lines[max(0, i-2):i+5]),
        })
    return products


def extract_event(url: str, region: str):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    name = None
    for cand in lines[:20]:
        if len(cand) > 4 and "bizouk" not in cand.lower():
            name = cand
            break
    city = None
    address = None
    for cand in lines[:60]:
        low = cand.lower()
        if not city and any(k in low for k in ["londres", "london", "paris", "rotterdam", "guadeloupe"]):
            city = cand
            continue
        if not address and any(ch.isdigit() for ch in cand) and len(cand) > 8:
            address = cand
    event = {
        "event_url": url,
        "region": region,
        "name": name or title,
        "subtitle": lines[1] if len(lines) > 1 else None,
        "event_date": next((line for line in lines[:40] if any(tok in line.lower() for tok in ["2026", "2025", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre", "am", "pm"])), None),
        "city": city,
        "address": address,
        "contact_phone": extract_phone(text),
        "contact_email": extract_email(text),
        "contact_website": None,
        "google_maps_url": None,
        "flyers": extract_flyers(soup),
        "products": extract_products_from_text(text),
        "extraction_mode": "LITE_HTML_COMPAT",
    }
    event["extraction_confidence"] = compute_confidence(event)
    event["score"] = compute_score(event)
    save_page_snapshot(url, "event_detail_lite_compat", {"title": title, "body_text": text[:16000], "links": [], "images": []})
    validation = validate_event_payload(event)
    log_extraction_run(url, event["extraction_mode"], event["extraction_confidence"], validation["ok"], validation["issues"])
    upsert_event(event)


def run():
    init_db()
    for region, start_url in REGIONS.items():
        try:
            html = fetch_html(start_url)
            links = extract_event_links(html)
            for link in links:
                try:
                    extract_event(link, region)
                    print(f"[OK] {region} -> {link}")
                except Exception as exc:
                    print(f"[ERROR] event {link}: {exc}")
        except Exception as exc:
            print(f"[ERROR] region {region}: {exc}")


if __name__ == "__main__":
    run()
