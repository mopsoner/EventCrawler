from datetime import datetime, timezone

from app.core.config import settings


class PlannerService:
    def heartbeat(self) -> dict:
        return {
            "service": "planner",
            "status": "ready",
            "last_tick_at": datetime.now(timezone.utc).isoformat(),
            "min_score": settings.planner_min_score,
            "min_rr": settings.planner_min_rr,
        }

    def build_candidate_from_signal(self, signal: dict) -> dict | None:
        trade = signal.get("trade", {}) or {}
        side = trade.get("side")
        entry = trade.get("entry")
        stop = trade.get("stop")
        target = trade.get("target")
        score = float(signal.get("score", 0.0))
        if not side or entry is None or stop is None or target is None:
            return None
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = reward / risk if risk > 0 else None
        if score < settings.planner_min_score:
            return None
        if rr is None or rr < settings.planner_min_rr:
            return None
        stage = "trade" if signal.get("pipeline", {}).get("trade") else signal.get("state", "collect")
        return {
            "symbol": signal["symbol"],
            "side": side,
            "stage": stage,
            "score": score,
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "rr_ratio": rr,
            "execution_target": signal.get("execution_target"),
            "liquidity_context": signal.get("liquidity_context"),
            "notes": signal.get("confirm_source") or signal.get("trigger"),
            "payload": signal,
        }
