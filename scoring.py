def compute_score(event: dict) -> int:
    score = 0
    name = (event.get("name") or "").lower()
    city = (event.get("city") or "").lower()
    region = (event.get("region") or "").lower()
    products = event.get("products") or []

    if any(k in name for k in ["carnaval", "carnival"]):
        score += 40
    if any(k in name for k in ["boat", "jouvert", "party", "soca", "dancehall", "afro"]):
        score += 10
    if city in ["londres", "london", "rotterdam", "paris"] or region in ["london", "rotterdam", "paris"]:
        score += 25
    if any(p.get("is_free") and p.get("is_available") is True for p in products):
        score += 20
    if any(p.get("is_free") for p in products):
        score += 10
    return min(score, 100)
