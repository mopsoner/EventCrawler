from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.position import Position


class PositionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_positions(self, limit: int = 100, status: str | None = None) -> list[Position]:
        stmt = select(Position)
        if status:
            stmt = stmt.where(Position.status == status)
        stmt = stmt.order_by(Position.opened_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create_position(self, *, symbol: str, side: str, quantity: float, entry_price: float | None, mark_price: float | None, stop_price: float | None, target_price: float | None, meta: dict | None) -> Position:
        row = Position(position_id=f"pos_{uuid4().hex[:16]}", symbol=symbol.upper(), side=side, quantity=quantity, entry_price=entry_price, mark_price=mark_price, stop_price=stop_price, target_price=target_price, status="open", meta=meta)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def close_position(self, position_id: str, *, mark_price: float | None, unrealized_pnl: float | None = None) -> Position | None:
        row = self.db.get(Position, position_id)
        if row is None:
            return None
        row.status = "closed"
        row.mark_price = mark_price
        row.unrealized_pnl = unrealized_pnl
        row.closed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return row
