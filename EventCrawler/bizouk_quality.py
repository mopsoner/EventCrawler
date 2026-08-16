"""Bizouk-specific cleanup and validation.

Kept separate from the generic/Kiwol extraction path so that tightening Bizouk's
rules cannot silently change another source's stored data.
"""
from collections import Counter
from datetime import datetime
import re
import unicodedata
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


INVISIBLE_RE = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]")
NAVIGATION_MARKERS = ("log in register", "my tickets", "conditions générales", "cookie policy", "menu principal")


def clean_text(value, multiline=False):
    if value is None:
        return None
    text = unicodedata.normalize("NFC", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    text = INVISIBLE_RE.sub("", text)
    if multiline:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text or None


def clean_subtitle(value):
    value = clean_text(value)
    return None if value and value.casefold() in {"description", "descriptif", "details", "détails"} else value


def _key(value):
    value = clean_text(value) or ""
    value = value.lstrip(".·,;:- ")
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


# Official Guadeloupe communes. Variants are compared accent/tirets/case-free.
GUADELOUPE_COMMUNES = (
    "Les Abymes", "Anse-Bertrand", "Baie-Mahault", "Baillif", "Basse-Terre",
    "Bouillante", "Capesterre-Belle-Eau", "Capesterre-de-Marie-Galante",
    "Deshaies", "La Désirade", "Le Gosier", "Gourbeyre", "Goyave", "Grand-Bourg",
    "Lamentin", "Morne-à-l'Eau", "Le Moule", "Petit-Bourg", "Petit-Canal",
    "Pointe-à-Pitre", "Pointe-Noire", "Port-Louis", "Saint-Claude", "Saint-François",
    "Saint-Louis", "Sainte-Anne", "Sainte-Rose", "Terre-de-Bas", "Terre-de-Haut",
    "Trois-Rivières", "Vieux-Fort", "Vieux-Habitants",
)
CITY_ALIASES = {_key(city): city for city in GUADELOUPE_COMMUNES}
CITY_ALIASES.update({_key("Gosier"): "Le Gosier", _key("Abymes"): "Les Abymes"})


def normalize_guadeloupe_city(value):
    key = _key(value)
    if not key or re.fullmatch(r"\d+\s+sessions?", key) or key in {"guadeloupe", "france"}:
        return None
    return CITY_ALIASES.get(key)


def normalize_phone(value):
    value = clean_text(value)
    if not value:
        return None
    raw = re.sub(r"[\s.()'\"\-]", "", value)
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        normalized = "+" + digits
    elif len(digits) == 10 and digits.startswith("0"):
        normalized = "+33" + digits[1:]
    else:
        return None
    # French numbering plan (metropolitan and overseas mobile/fixed numbers).
    return normalized if re.fullmatch(r"\+33\d{9}", normalized) else None


MONTHS = {name: n for n, names in enumerate(((), ("janvier", "january"), ("février", "fevrier", "february"), ("mars", "march"), ("avril", "april"), ("mai", "may"), ("juin", "june"), ("juillet", "july"), ("août", "aout", "august"), ("septembre", "september"), ("octobre", "october"), ("novembre", "november"), ("décembre", "decembre", "december"))) for name in names}


def normalize_event_date(value, region=None, city=None):
    value = clean_text(value)
    if not value:
        return None
    iso_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        low = value.casefold().replace(",", " ").replace("·", " ")
        month = next(((name, number) for name, number in MONTHS.items() if re.search(rf"\b{re.escape(name)}\b", low)), None)
        day = re.search(r"\b([0-3]?\d)(?:er|st|nd|rd|th)?\b", low)
        year = re.search(r"\b(20\d{2})\b", low)
        time = re.search(r"\b([0-2]?\d)(?::|h)([0-5]\d)?\b|\b([0-1]?\d)\s*(am|pm)\b", low)
        if not (month and day and year):
            return None
        hour = minute = 0
        if time:
            hour = int(time.group(1) or time.group(3))
            minute = int(time.group(2) or 0)
            meridiem = time.group(4) or ("pm" if re.search(r"\bpm\b", low[time.end():time.end() + 4]) else "am" if re.search(r"\bam\b", low[time.end():time.end() + 4]) else None)
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
        try:
            parsed = datetime(int(year.group(1)), month[1], int(day.group(1)), hour, minute)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        region_zones = {"guadeloupe": "America/Guadeloupe", "kiwol_guadeloupe": "America/Guadeloupe", "london": "Europe/London", "rotterdam": "Europe/Amsterdam", "paris": "Europe/Paris"}
        tz_name = "America/Guadeloupe" if normalize_guadeloupe_city(city) else region_zones.get(region, "Europe/Paris")
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed.isoformat(timespec="minutes")


class EventValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_bizouk_event(event):
    errors = []
    parsed_url = urlparse(event.get("event_url") or "")
    if parsed_url.scheme != "https" or parsed_url.hostname not in {"bizouk.com", "www.bizouk.com"} or not re.fullmatch(r"/events/details/[^/]+/\d+", parsed_url.path):
        errors.append("invalid source URL")
    if not re.fullmatch(r"\d+", str(event.get("event_external_id") or "")):
        errors.append("invalid source identifier")
    title = clean_text(event.get("name"))
    if not title or len(title) < 3 or len(title) > 200 or any(x in title.casefold() for x in NAVIGATION_MARKERS):
        errors.append("missing or implausible title")
    try:
        start = datetime.fromisoformat(event.get("event_date") or "")
    except ValueError:
        errors.append("invalid event date")
        start = None
    try:
        end = datetime.fromisoformat(event["event_end_date"]) if event.get("event_end_date") else None
        if start and end and end < start:
            errors.append("end date precedes start date")
    except ValueError:
        errors.append("invalid end date")
    city = event.get("city")
    city_key = _key(city)
    if city and (len(city) > 80 or re.fullmatch(r"\d+\s+sessions?", city_key) or city_key in {"guadeloupe", "france"} or any(x in city.casefold() for x in NAVIGATION_MARKERS)):
        errors.append("implausible city")
    description = clean_text(event.get("description")) or ""
    low_description = description.casefold()
    if "<html" in low_description or any(x in low_description for x in NAVIGATION_MARKERS):
        errors.append("description contains page navigation or HTML")
    if event.get("contact_phone") and not re.fullmatch(r"\+33\d{9}", event["contact_phone"]):
        errors.append("invalid phone")
    if errors:
        raise EventValidationError(errors)
    return event


def page_rejection_reason(soup):
    text = clean_text(soup.get_text(" ", strip=True)) or ""
    low = text.casefold()
    if any(marker in low for marker in ("captcha", "cloudflare", "access denied", "just a moment", "robot check")):
        return "anti-bot or error page"
    if not extract_event_identity(soup):
        return "unexpected HTML: no event identity"
    return None


def extract_event_identity(soup):
    return soup.select_one(".evh-hero h1.evh-hero-title, h1.evh-hero-title, [itemtype$='/Event'] [itemprop='name']")


class QualityReport:
    def __init__(self):
        self.counts = Counter()
        self.reasons = Counter()

    def reject(self, reason):
        self.counts["rejected"] += 1
        self.reasons[str(reason)] += 1

    def as_dict(self):
        return {**self.counts, "rejection_reasons": dict(self.reasons)}
