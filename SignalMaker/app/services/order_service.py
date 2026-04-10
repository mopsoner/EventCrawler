from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order


class OrderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_orders(self, limit: int = 100, status: str | None = None) -> list[Order]:
        stmt = select(Order)
        if status:
            stmt = stmt.where(Order.status == status)
        stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create_order(self, *, candidate_id: str | None, position_id: str | None, symbol: str, side: str, order_type: str, quantity: float, requested_price: float | None, filled_price: float | None, status: str, meta: dict | None = None) -> Order:
        row = Order(order_id=f"ord_{uuid4().hex[:16]}", candidate_id=candidate_id, position_id=position_id, symbol=symbol.upper(), side=side, order_type=order_type, quantity=quantity, requested_price=requested_price, filled_price=filled_price, status=status, meta=meta, updated_at=datetime.now(timezone.utc))
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
