import re
import unicodedata
from statistics import median


VARIANT_WORDS = {
    "early", "bird", "promo", "promotion", "presale", "prevente", "preventes",
    "last", "minute", "phase", "tier", "tarif", "price", "prix",
}


def normalized_words(value):
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+|\d+", text)


def product_identity_key(source, product_name):
    """Stable identity for one named offer; price is deliberately excluded."""
    words = normalized_words(product_name)
    return f"{source}:{'_'.join(words) or 'unknown'}"


def classify_product(product_name):
    words = normalized_words(product_name)
    joined = " ".join(words)
    capacity = None
    match = re.search(r"(?:for|pour|de|x)\s*(\d+)\s*(?:people|persons|personnes|pers)?", joined)
    if not match:
        match = re.search(r"\b(\d+)\s*(?:people|persons|personnes|pers)\b", joined)
    if match:
        capacity = int(match.group(1))

    if any(word in words for word in ("lounge", "table", "deck")):
        kind = "group"
    elif any(word in words for word in ("vip",)):
        kind = "vip_entry"
    elif any(word in words for word in ("entry", "entree", "ticket", "billet", "admission", "pass")):
        kind = "single_entry"
    elif any(word in words for word in ("invitation", "invite")):
        kind = "invitation"
    else:
        core = [word for word in words if word not in VARIANT_WORDS and not word.isdigit()]
        kind = "_".join(core[:5]) or "other"

    family_key = kind
    if kind == "group":
        group_words = [word for word in words if word in {"beach", "deck", "sunset", "sunday", "vip", "lounge", "table"}]
        family_key = "group:" + ("_".join(group_words) or "generic")
    early_markers = {"early", "bird", "presale", "prevente", "promo", "phase", "tier"}
    matched_markers = sorted(early_markers.intersection(words))
    is_early_bird = bool(matched_markers)
    return {
        "family_key": family_key,
        "capacity": capacity,
        "kind": kind,
        "is_early_bird": is_early_bird,
        "early_bird_score": 80 if is_early_bird else 0,
        "early_bird_confidence": "high" if is_early_bird else None,
        "early_bird_reason": ("Marqueurs tarifaires: " + ", ".join(matched_markers)) if is_early_bird else None,
    }


def ensure_opportunity_schema(cur):
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS price_opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            opportunity_type TEXT NOT NULL,
            reference_product_id INTEGER NOT NULL DEFAULT 0,
            reference_price REAL,
            current_price REAL,
            saving_amount REAL,
            saving_percent REAL,
            score INTEGER DEFAULT 0,
            confidence TEXT DEFAULT 'high',
            reason TEXT,
            is_active INTEGER DEFAULT 1,
            first_detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT,
            UNIQUE(event_id, product_id, opportunity_type, reference_product_id)
        );
        CREATE INDEX IF NOT EXISTS idx_price_opportunities_active
        ON price_opportunities(is_active, event_id, score);
    ''')


def _upsert(cur, event_id, product_id, opportunity_type, reference_product_id,
            reference_price, current_price, saving_amount, saving_percent,
            score, confidence, reason):
    cur.execute('''
        INSERT INTO price_opportunities(
            event_id, product_id, opportunity_type, reference_product_id,
            reference_price, current_price, saving_amount, saving_percent,
            score, confidence, reason, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(event_id, product_id, opportunity_type, reference_product_id)
        DO UPDATE SET reference_price=excluded.reference_price,
            current_price=excluded.current_price, saving_amount=excluded.saving_amount,
            saving_percent=excluded.saving_percent, score=excluded.score,
            confidence=excluded.confidence, reason=excluded.reason, is_active=1,
            last_detected_at=CURRENT_TIMESTAMP, resolved_at=NULL
    ''', (event_id, product_id, opportunity_type, reference_product_id,
          reference_price, current_price, saving_amount, saving_percent,
          score, confidence, reason))


def record_price_variation(cur, event_id, product_id, old_price, new_price):
    """Persist every real transition (10→15→20 included), not only discounts."""
    if old_price is None or new_price is None or float(old_price) == float(new_price):
        return
    delta = float(new_price) - float(old_price)
    pct = (abs(delta) / float(old_price) * 100) if old_price else None
    kind = "PRICE_INCREASE" if delta > 0 else "PRICE_DROP"
    score = min(100, int((pct or 0) + min(abs(delta), 30)))
    reason = f"Prix passé de {old_price:g} € à {new_price:g} € ({delta:+g} €)"
    # A transition is an observed signal and remains visible until superseded.
    cur.execute('''UPDATE price_opportunities SET is_active=0, resolved_at=CURRENT_TIMESTAMP
                   WHERE event_id=? AND product_id=? AND opportunity_type IN ('PRICE_INCREASE','PRICE_DROP')''',
                (event_id, product_id))
    _upsert(cur, event_id, product_id, kind, 0, old_price, new_price,
            -delta, pct, score, "high", reason)


def refresh_family_opportunities(cur, event_id):
    cur.execute("""UPDATE price_opportunities SET is_active=0, resolved_at=CURRENT_TIMESTAMP
                   WHERE event_id=? AND opportunity_type='CHEAPER_VARIANT'""", (event_id,))
    rows = [dict(row) for row in cur.execute('''
        SELECT id, product_name, family_key, numeric_price, is_available, capacity
        FROM products WHERE event_id=? AND numeric_price IS NOT NULL AND numeric_price > 0
    ''', (event_id,)).fetchall()]
    families = {}
    for row in rows:
        families.setdefault((row.get("family_key"), row.get("capacity")), []).append(row)
    for family in families.values():
        prices = sorted({float(row["numeric_price"]) for row in family})
        if len(prices) < 2:
            continue
        reference = median(prices)
        for row in family:
            current = float(row["numeric_price"])
            if current >= reference or row.get("is_available") == 0:
                continue
            saving = reference - current
            pct = saving / reference * 100
            if saving < 1 or pct < 5:
                continue
            ref = min((candidate for candidate in family if float(candidate["numeric_price"]) >= reference),
                      key=lambda candidate: float(candidate["numeric_price"]))
            _upsert(cur, event_id, row["id"], "CHEAPER_VARIANT", ref["id"], reference,
                    current, saving, pct, min(100, int(pct + saving)), "medium",
                    f"{saving:g} € moins cher que le tarif médian comparable ({reference:g} €)")
