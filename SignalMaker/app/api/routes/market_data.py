from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.market_candle import MarketCandleRead
from app.services.market_data_service import MarketDataService

router = APIRouter()


@router.get("/candles", response_model=list[MarketCandleRead])
def list_candles(symbol: str | None = Query(default=None), interval: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=2000), db: Session = Depends(get_db)) -> list[MarketCandleRead]:
    return MarketDataService(db).list_candles(symbol=symbol, interval=interval, limit=limit)
