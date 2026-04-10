from datetime import datetime, timezone


class SchedulerService:
    def heartbeat(self) -> dict:
        return {
            "service": "scheduler",
            "status": "ready",
            "last_tick_at": datetime.now(timezone.utc).isoformat(),
            "note": "Use scripts/run_scheduler_loop.py for simple periodic orchestration",
        }
