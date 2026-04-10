from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssetStateBase(BaseModel):
    stage: str = Field(default="collect")
    bias: str | None = None
    session: str | None = None
    score: float = 0.0
    price: float | None = None
    rsi_1h: float | None = None
    rsi_5m: float | None = None
    liquidity_context: dict | None = None
    execution_target: dict | None = None
    planner_notes: str | None = None
    state_payload: dict | None = None


class AssetStateUpsert(AssetStateBase):
    pass


class AssetStateRead(AssetStateBase):
    symbol: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
