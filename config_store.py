import json
import re
from pathlib import Path

CONFIG_PATH = Path("data/config.json")

DEFAULT_CONFIG = {
    "max_workers": 6,
    "request_timeout": 45,
    "region_scan_frequency_minutes": 60,
    "free_product_refresh_frequency_hours": 24,
    "user_agent": "Mozilla/5.0",
    "regions": {
        "london": {"enabled": True, "url": "https://www.bizouk.com/?region=london"},
        "guadeloupe": {"enabled": True, "url": "https://www.bizouk.com/?region=guadeloupe"},
        "paris": {"enabled": True, "url": "https://www.bizouk.com/?region=paris"},
        "rotterdam": {"enabled": True, "url": "https://www.bizouk.com/?region=rotterdam"},
    },
}


def slugify_region_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower())
    return value.strip("_")


def _normalized_regions(regions_data: dict, fallback_to_defaults: bool) -> dict:
    source = regions_data if isinstance(regions_data, dict) else (DEFAULT_CONFIG["regions"] if fallback_to_defaults else {})
    clean_regions = {}
    for raw_name, region in source.items():
        if not isinstance(region, dict):
            continue
        name = slugify_region_name(raw_name)
        if not name:
            continue
        url = str(region.get("url") or "").strip()
        if not url:
            continue
        clean_regions[name] = {
            "enabled": bool(region.get("enabled")),
            "url": url,
        }
    return clean_regions


def _merge_defaults(data: dict) -> dict:
    merged = {
        "max_workers": DEFAULT_CONFIG["max_workers"],
        "request_timeout": DEFAULT_CONFIG["request_timeout"],
        "region_scan_frequency_minutes": DEFAULT_CONFIG["region_scan_frequency_minutes"],
        "free_product_refresh_frequency_hours": DEFAULT_CONFIG["free_product_refresh_frequency_hours"],
        "user_agent": DEFAULT_CONFIG["user_agent"],
        "regions": {},
    }
    if not isinstance(data, dict):
        merged["regions"] = _normalized_regions({}, True)
        return merged
    for key in (
        "max_workers",
        "request_timeout",
        "region_scan_frequency_minutes",
        "free_product_refresh_frequency_hours",
        "user_agent",
    ):
        if key in data:
            merged[key] = data[key]
    has_regions_key = "regions" in data
    merged["regions"] = _normalized_regions(data.get("regions"), fallback_to_defaults=not has_regions_key)
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
    try:
        merged["region_scan_frequency_minutes"] = max(5, min(10080, int(merged.get("region_scan_frequency_minutes", 60))))
    except Exception:
        merged["region_scan_frequency_minutes"] = 60
    try:
        merged["free_product_refresh_frequency_hours"] = max(1, min(720, int(merged.get("free_product_refresh_frequency_hours", 24))))
    except Exception:
        merged["free_product_refresh_frequency_hours"] = 24
    merged["user_agent"] = str(merged.get("user_agent") or "Mozilla/5.0").strip() or "Mozilla/5.0"
    merged["regions"] = _normalized_regions(merged.get("regions"), fallback_to_defaults=False)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged
