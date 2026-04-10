from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FillRead(BaseModel):
    fill_id: str
    order_id: str
    position_id: str | None = None
    symbol: str
    side: str
    quantity: float
    price: float
    filled_at: datetime

    model_config = ConfigDict(from_attributes=True)
