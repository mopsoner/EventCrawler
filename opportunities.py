from freshness import is_recent


def build_opportunity_rows(events: list[dict], free_products: list[dict]) -> list[dict]:
    event_map = {e["id"]: e for e in events if e.get("id") is not None}
    rows = []
    for product in free_products:
        event = event_map.get(product.get("event_id"))
        if not event:
            continue
        recent = is_recent(event.get("first_seen_at"), hours=24)
        early = bool(product.get("is_free")) and product.get("is_available") in (1, True) and recent
        rows.append(
            {
                "event_id": event.get("id"),
                "event_name": event.get("name"),
                "event_url": event.get("event_url"),
                "region": event.get("region"),
                "score": event.get("score", 0),
                "first_seen_at": event.get("first_seen_at"),
                "is_recent": recent,
                "product_name": product.get("product_name"),
                "price_text": product.get("price_text"),
                "is_free": product.get("is_free"),
                "is_available": product.get("is_available"),
                "is_early_free_opportunity": early,
            }
        )
    rows.sort(key=lambda r: (r["is_early_free_opportunity"], r["score"], r["first_seen_at"] or ""), reverse=True)
    return rows
