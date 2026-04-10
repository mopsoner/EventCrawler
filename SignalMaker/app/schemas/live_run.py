from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LiveRunRead(BaseModel):
    run_id: str
    mode: str
    status: str
    symbols_total: int
    symbols_scanned: int
    stats: dict | None = None
    started_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
