from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PositionRead(BaseModel):
    position_id: str
    symbol: str
    side: str
    status: str
    quantity: float
    entry_price: float | None = None
    mark_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    unrealized_pnl: float | None = None
    meta: dict | None = None
    opened_at: datetime
    closed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
