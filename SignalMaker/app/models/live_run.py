from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LiveRun(Base):
    __tablename__ = "live_runs"
    __table_args__ = (
        Index("ix_live_runs_started_at", "started_at"),
        Index("ix_live_runs_status", "status"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="paper", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    symbols_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    symbols_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
