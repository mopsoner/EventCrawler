from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MarketCandleRead(BaseModel):
    candle_id: str
    symbol: str
    interval: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    ingested_at: datetime

    model_config = ConfigDict(from_attributes=True)
