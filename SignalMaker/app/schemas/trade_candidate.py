from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TradeCandidateRead(BaseModel):
    candidate_id: str
    symbol: str
    side: str
    stage: str
    status: str
    score: float
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    rr_ratio: float | None = None
    execution_target: dict | None = None
    liquidity_context: dict | None = None
    notes: str | None = None
    payload: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
