from confidence import compute_confidence


def ai_extract_from_snapshot(snapshot: dict) -> dict:
    body = snapshot.get("body_text") or ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]

    name = snapshot.get("title")
    if lines:
        first = lines[0]
        if len(first) > 4:
            name = first

    products = []
    for idx, line in enumerate(lines[:300]):
        low = line.lower()
        if "0.00€" in low or "gratuit" in low or "free" in low:
            product_name = lines[idx - 1] if idx > 0 else "Unknown product"
            products.append(
                {
                    "product_name": product_name,
                    "price_text": line,
                    "numeric_price": 0.0,
                    "is_free": True,
                    "is_available": None,
                    "availability_text": "ai_fallback_detected",
                }
            )

    payload = {
        "name": name,
        "products": products,
        "flyers": [],
        "extraction_mode": "AI_FALLBACK",
    }
    payload["extraction_confidence"] = compute_confidence(payload)
    return payload
