from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market_candle import MarketCandle


class MarketDataService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_candles(self, *, symbol: str | None = None, interval: str | None = None, limit: int = 200) -> list[MarketCandle]:
        stmt = select(MarketCandle)
        if symbol:
            stmt = stmt.where(MarketCandle.symbol == symbol.upper())
        if interval:
            stmt = stmt.where(MarketCandle.interval == interval)
        stmt = stmt.order_by(MarketCandle.close_time.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def upsert_candles(self, symbol: str, interval: str, candles: list[dict]) -> int:
        count = 0
        for candle in candles:
            candle_id = f"{symbol.upper()}-{interval}-{int(candle['open_time'])}"
            row = self.db.get(MarketCandle, candle_id)
            if row is None:
                row = MarketCandle(candle_id=candle_id, symbol=symbol.upper(), interval=interval)
                self.db.add(row)
            row.open_time = int(candle["open_time"])
            row.close_time = int(candle["close_time"])
            row.open = float(candle["open"])
            row.high = float(candle["high"])
            row.low = float(candle["low"])
            row.close = float(candle["close"])
            row.volume = float(candle["volume"])
            row.ingested_at = datetime.now(timezone.utc)
            count += 1
        self.db.commit()
        return count
