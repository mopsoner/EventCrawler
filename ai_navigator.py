def choose_event_links(candidate_links: list[dict]) -> list[str]:
    ranked = []
    for item in candidate_links:
        href = item.get("href") or ""
        text = (item.get("text") or "").lower()
        score = 0
        if "/events/details/" in href:
            score += 100
        if any(k in text for k in ["carnaval", "carnival", "soirée", "party", "boat", "event"]):
            score += 10
        ranked.append((score, href))
    ranked.sort(reverse=True)
    return [href for score, href in ranked if href]
