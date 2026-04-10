from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OrderRead(BaseModel):
    order_id: str
    candidate_id: str | None = None
    position_id: str | None = None
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    requested_price: float | None = None
    filled_price: float | None = None
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
