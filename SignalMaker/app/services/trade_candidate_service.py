from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.trade_candidate import TradeCandidate


class TradeCandidateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_candidates(self, limit: int = 100, status: str | None = None) -> list[TradeCandidate]:
        stmt = select(TradeCandidate)
        if status:
            stmt = stmt.where(TradeCandidate.status == status)
        stmt = stmt.order_by(TradeCandidate.score.desc(), TradeCandidate.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def get_open_candidates(self, limit: int = 100) -> list[TradeCandidate]:
        stmt = select(TradeCandidate).where(TradeCandidate.status == "open").order_by(TradeCandidate.score.desc(), TradeCandidate.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def upsert_open_candidate(self, *, symbol: str, side: str, stage: str, score: float, entry_price: float | None, stop_price: float | None, target_price: float | None, rr_ratio: float | None, execution_target: dict | None, liquidity_context: dict | None, notes: str | None, payload: dict | None) -> TradeCandidate:
        candidate_id = f"{symbol.upper()}-open"
        row = self.db.get(TradeCandidate, candidate_id)
        if row is None:
            row = TradeCandidate(candidate_id=candidate_id, symbol=symbol.upper(), created_at=datetime.now(timezone.utc))
            self.db.add(row)
        row.side = side
        row.stage = stage
        row.status = "open"
        row.score = score
        row.entry_price = entry_price
        row.stop_price = stop_price
        row.target_price = target_price
        row.rr_ratio = rr_ratio
        row.execution_target = execution_target
        row.liquidity_context = liquidity_context
        row.notes = notes
        row.payload = payload
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_executed(self, candidate_id: str) -> TradeCandidate | None:
        row = self.db.get(TradeCandidate, candidate_id)
        if row is None:
            return None
        row.status = "executed"
        self.db.commit()
        self.db.refresh(row)
        return row
