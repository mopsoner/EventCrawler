from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssetStateCurrent(Base):
    __tablename__ = "asset_state_current"
    __table_args__ = (
        Index("ix_asset_state_current_stage", "stage"),
        Index("ix_asset_state_current_score", "score"),
        Index("ix_asset_state_current_updated_at", "updated_at"),
    )

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), default="collect", nullable=False)
    bias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    session: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    planner_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
