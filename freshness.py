from datetime import datetime, timedelta


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def is_recent(first_seen_at: str | None, hours: int = 24) -> bool:
    dt = parse_dt(first_seen_at)
    if not dt:
        return False
    return datetime.utcnow() - dt <= timedelta(hours=hours)
