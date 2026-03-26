def compute_confidence(event: dict) -> int:
    confidence = 0
    if event.get("name"):
        confidence += 20
    if event.get("event_date"):
        confidence += 15
    if event.get("address") or event.get("city"):
        confidence += 15
    if event.get("contact_phone") or event.get("contact_email"):
        confidence += 10
    products = event.get("products") or []
    flyers = event.get("flyers") or []
    if products:
        confidence += 20
    if any(p.get("price_text") for p in products):
        confidence += 10
    if flyers:
        confidence += 10
    return min(confidence, 100)
