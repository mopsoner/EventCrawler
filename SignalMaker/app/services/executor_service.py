from sqlalchemy.orm import Session

from app.services.fill_service import FillService
from app.services.order_service import OrderService
from app.services.position_service import PositionService
from app.services.trade_candidate_service import TradeCandidateService


class ExecutorService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.orders = OrderService(db)
        self.fills = FillService(db)
        self.positions = PositionService(db)
        self.candidates = TradeCandidateService(db)

    def execute_open_candidates(self, limit: int = 10, quantity: float = 1.0) -> dict:
        executed = []
        skipped = []
        for candidate in self.candidates.get_open_candidates(limit=limit):
            if candidate.entry_price is None:
                skipped.append({"candidate_id": candidate.candidate_id, "reason": "missing_entry_price"})
                continue
            position = self.positions.create_position(symbol=candidate.symbol, side=candidate.side, quantity=quantity, entry_price=candidate.entry_price, mark_price=candidate.entry_price, stop_price=candidate.stop_price, target_price=candidate.target_price, meta={"candidate_id": candidate.candidate_id, "mode": "paper"})
            order = self.orders.create_order(candidate_id=candidate.candidate_id, position_id=position.position_id, symbol=candidate.symbol, side=candidate.side, order_type="market", quantity=quantity, requested_price=candidate.entry_price, filled_price=candidate.entry_price, status="filled", meta={"mode": "paper"})
            fill = self.fills.create_fill(order_id=order.order_id, position_id=position.position_id, symbol=candidate.symbol, side=candidate.side, quantity=quantity, price=candidate.entry_price)
            self.candidates.mark_executed(candidate.candidate_id)
            executed.append({"candidate_id": candidate.candidate_id, "position_id": position.position_id, "order_id": order.order_id, "fill_id": fill.fill_id})
        return {"executed": executed, "skipped": skipped}
