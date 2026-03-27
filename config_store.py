import json
from pathlib import Path

CONFIG_PATH = Path("data/config.json")

DEFAULT_CONFIG = {
    "max_workers": 6,
    "request_timeout": 45,
    "user_agent": "Mozilla/5.0",
    "regions": {
        "london": {"enabled": True, "url": "https://www.bizouk.com/?region=london"},
        "guadeloupe": {"enabled": True, "url": "https://www.bizouk.com/?region=guadeloupe"},
        "paris": {"enabled": True, "url": "https://www.bizouk.com/?region=paris"},
        "rotterdam": {"enabled": True, "url": "https://www.bizouk.com/?region=rotterdam"},
    },
}


def _merge_defaults(data: dict) -> dict:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(data, dict):
        return merged
    for key in ("max_workers", "request_timeout", "user_agent"):
        if key in data:
            merged[key] = data[key]
    if isinstance(data.get("regions"), dict):
        for name, region in merged["regions"].items():
            incoming = data["regions"].get(name)
            if isinstance(incoming, dict):
                if "enabled" in incoming:
                    region["enabled"] = bool(incoming["enabled"])
                if incoming.get("url"):
                    region["url"] = str(incoming["url"]).strip()
    return merged


def load_config() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = DEFAULT_CONFIG
    merged = _merge_defaults(data)
    if merged != data:
        save_config(merged)
    return merged


def save_config(data: dict) -> dict:
    merged = _merge_defaults(data)
    try:
        merged["max_workers"] = max(1, min(32, int(merged.get("max_workers", 6))))
    except Exception:
        merged["max_workers"] = 6
    try:
        merged["request_timeout"] = max(5, min(180, int(merged.get("request_timeout", 45))))
    except Exception:
        merged["request_timeout"] = 45
    merged["user_agent"] = str(merged.get("user_agent") or "Mozilla/5.0").strip() or "Mozilla/5.0"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
