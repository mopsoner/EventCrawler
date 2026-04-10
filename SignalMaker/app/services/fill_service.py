from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fill import Fill


class FillService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_fills(self, limit: int = 100) -> list[Fill]:
        stmt = select(Fill).order_by(Fill.filled_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create_fill(self, *, order_id: str, position_id: str | None, symbol: str, side: str, quantity: float, price: float) -> Fill:
        row = Fill(fill_id=f"fill_{uuid4().hex[:16]}", order_id=order_id, position_id=position_id, symbol=symbol.upper(), side=side, quantity=quantity, price=price)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
