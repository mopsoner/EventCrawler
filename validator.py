def validate_event_payload(data: dict) -> dict:
    issues = []
    if not data.get("event_url"):
        issues.append("missing_event_url")
    if not data.get("name"):
        issues.append("missing_name")
    if not (data.get("city") or data.get("address")):
        issues.append("missing_location")
    products = data.get("products") or []
    if any(p.get("is_free") and p.get("numeric_price") not in (0, 0.0, None) for p in products):
        issues.append("inconsistent_free_price")
    return {"ok": len(issues) <= 2, "issues": issues}
