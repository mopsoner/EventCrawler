from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.live_run import LiveRun


class LiveRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_runs(self, limit: int = 50) -> list[LiveRun]:
        stmt = select(LiveRun).order_by(LiveRun.started_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def start_run(self, run_id: str, mode: str, symbols_total: int) -> LiveRun:
        row = LiveRun(run_id=run_id, mode=mode, status="running", symbols_total=symbols_total, symbols_scanned=0)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def complete_run(self, run_id: str, *, symbols_scanned: int, stats: dict) -> LiveRun | None:
        row = self.db.get(LiveRun, run_id)
        if row is None:
            return None
        row.status = "completed"
        row.symbols_scanned = symbols_scanned
        row.stats = stats
        row.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return row
