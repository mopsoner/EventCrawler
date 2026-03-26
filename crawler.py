import asyncio
import re
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from ai_extractor import ai_extract_from_snapshot
from ai_navigator import choose_event_links
from config import REGIONS, BASE_URL, HEADLESS, EXTRACTION_MODE
from confidence import compute_confidence
from db import init_db, upsert_event, save_page_snapshot, log_extraction_run
from page_snapshot import build_page_snapshot
from scoring import compute_score
from validator import validate_event_payload

UNAVAILABLE_WORDS = ["épuisé", "epuise", "sold out", "indisponible", "complet", "closed"]
AVAILABLE_WORDS = ["réserver", "reserver", "acheter", "commander", "ajouter", "prendre", "s'inscrire", "inscription"]


def normalize_text(text: str) -> str:
    return re.sub(r"\\s+", " ", (text or "").strip().lower())


def parse_price(text: str):
    if not text:
        return None
    t = text.strip().lower().replace(",", ".")
    if "gratuit" in t or "free" in t:
        return 0.0
    m = re.search(r'(\\d+(?:\\.\\d+)?)\\s*€', t)
    return float(m.group(1)) if m else None


def extract_email(text: str):
    m = re.search(r'([A-Z0-9._%+\\-]+@[A-Z0-9.\\-]+\\.[A-Z]{2,})', text, re.I)
    return m.group(1) if m else None


def extract_phone(text: str):
    m = re.search(r'(\\+?\\d[\\d\\s().-]{7,}\\d)', text)
    return re.sub(r'\\s+', ' ', m.group(1)).strip() if m else None


async def extract_event_links(page):
    hrefs = await page.locator("a[href*='/events/details/']").evaluate_all("els => els.map(a => a.href).filter(Boolean)")
    if hrefs:
        return sorted(set(hrefs))
    candidates = []
    return sorted(set(choose_event_links(candidates)))


async def extract_flyers(page):
    imgs = page.locator("img")
    flyers = []
    for i in range(await imgs.count()):
        img = imgs.nth(i)
        src = await img.get_attribute("src")
        alt = await img.get_attribute("alt")
        if src:
            full = urljoin(BASE_URL, src)
            ref = ((alt or "") + " " + full).lower()
            if "flyer" in ref or "affiche" in ref:
                flyers.append(full)
    return sorted(set(flyers))


async def extract_products(page):
    products = []
    blocks = page.locator("div, li, article")
    seen = set()
    for i in range(await blocks.count()):
        block = blocks.nth(i)
        try:
            text = await block.inner_text(timeout=600)
        except Exception:
            continue
        norm = normalize_text(text)
        if not text or ("€" not in text and "gratuit" not in norm and "free" not in norm):
            continue
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if not lines:
            continue
        price_text = next((line for line in lines if parse_price(line) is not None or "gratuit" in line.lower() or "free" in line.lower()), None)
        product_name = next((line for line in lines if parse_price(line) is None and len(line) < 120), None)
        if not product_name or not price_text:
            continue
        numeric_price = parse_price(price_text)
        is_free = numeric_price == 0.0
        is_available = None
        availability_text = None
        if any(word in norm for word in UNAVAILABLE_WORDS):
            is_available = False
            availability_text = "unavailable_text"
        elif any(word in norm for word in AVAILABLE_WORDS):
            is_available = True
            availability_text = "available_action_text"
        key = (product_name, price_text)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "product_name": product_name,
            "price_text": price_text,
            "numeric_price": numeric_price,
            "is_free": is_free,
            "is_available": is_available,
            "availability_text": availability_text,
            "details": " | ".join(lines[:10]),
        })
    return products


async def extract_event_rule_based(page, event_url: str, region: str):
    await page.goto(event_url, wait_until="networkidle", timeout=60000)
    snapshot = await build_page_snapshot(page)
    body_text = snapshot["body_text"]
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    title = await page.title()
    name = next((line for line in lines[:10] if len(line) > 4), title)
    city = None
    address = None
    for line in lines[:40]:
        if not city and any(x in line.lower() for x in ["londres", "london", "paris", "rotterdam", "guadeloupe"]):
            city = line
            continue
        if not address and any(ch.isdigit() for ch in line) and len(line) > 8:
            address = line
            break
    event = {
        "event_url": event_url,
        "region": region,
        "name": name,
        "subtitle": lines[1] if len(lines) > 1 else None,
        "event_date": next((line for line in lines[:30] if any(tok in line.lower() for tok in ["2026", "2025", "janvier", "février", "mars", "april", "august", "août"])), None),
        "city": city,
        "address": address,
        "contact_phone": extract_phone(body_text),
        "contact_email": extract_email(body_text),
        "contact_website": None,
        "google_maps_url": None,
        "flyers": await extract_flyers(page),
        "products": await extract_products(page),
        "extraction_mode": "RULES",
    }
    return event, snapshot


async def process_event(page, event_url: str, region: str):
    event, snapshot = await extract_event_rule_based(page, event_url, region)
    confidence = compute_confidence(event)
    validation = validate_event_payload(event)
    if EXTRACTION_MODE in {"HYBRID", "AI_FIRST"} and (confidence < 60 or not validation["ok"]):
        ai_data = ai_extract_from_snapshot(snapshot)
        for key, value in ai_data.items():
            if key == "products" and not event.get("products"):
                event["products"] = value
            elif key == "flyers" and not event.get("flyers"):
                event["flyers"] = value
            elif not event.get(key):
                event[key] = value
        event["extraction_mode"] = ai_data.get("extraction_mode", "AI_FALLBACK")
        confidence = compute_confidence(event)
        validation = validate_event_payload(event)
    event["extraction_confidence"] = confidence
    event["score"] = compute_score(event)
    save_page_snapshot(event_url, "event_detail", snapshot)
    log_extraction_run(event_url, event["extraction_mode"], confidence, validation["ok"], validation["issues"])
    upsert_event(event)


async def run():
    init_db()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        page = await browser.new_page()
        for region, url in REGIONS.items():
            await page.goto(url, wait_until="networkidle", timeout=60000)
            for link in await extract_event_links(page):
                try:
                    event_page = await browser.new_page()
                    await process_event(event_page, link, region)
                    await event_page.close()
                    print(f"[OK] {region} -> {link}")
                except Exception as exc:
                    print(f"[ERROR] {region} -> {link}: {exc}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
