from datetime import datetime, timezone
from typing import Any

import requests

from app.core.config import settings


class CollectorService:
    def __init__(self) -> None:
        self.base_url = settings.binance_rest_base.rstrip("/")
        self.session = requests.Session()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        res = self.session.get(f"{self.base_url}{path}", params=params or {}, timeout=15)
        res.raise_for_status()
        return res.json()

    def heartbeat(self) -> dict:
        return {
            "service": "collector",
            "status": "ready",
            "last_tick_at": datetime.now(timezone.utc).isoformat(),
            "base_url": self.base_url,
        }

    def discover_symbols(self, limit: int | None = None) -> list[str]:
        info = self._get("/api/v3/exchangeInfo")
        out: list[str] = []
        for row in info.get("symbols", []):
            if row.get("status") != settings.binance_symbol_status:
                continue
            if row.get("quoteAsset") not in settings.quote_assets_list:
                continue
            if not row.get("isSpotTradingAllowed", False):
                continue
            out.append(row["symbol"])
        out = sorted(set(out))
        return out[: (limit or settings.binance_max_symbols)]

    def fetch_klines(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        raw = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return [{"open_time": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]), "close_time": int(r[6])} for r in raw]

    def collect_symbol_bundle(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "1m": self.fetch_klines(symbol, "1m", settings.binance_lookback_1m),
            "5m": self.fetch_klines(symbol, "5m", settings.binance_lookback_5m),
            "1h": self.fetch_klines(symbol, "1h", settings.binance_lookback_1h),
            "4h": self.fetch_klines(symbol, "4h", settings.binance_lookback_4h),
        }
