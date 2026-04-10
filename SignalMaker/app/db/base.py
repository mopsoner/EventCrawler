from app.db.session import engine
from app.models.base import Base
from app.models.asset_state import AssetStateCurrent
from app.models.live_run import LiveRun
from app.models.trade_candidate import TradeCandidate
from app.models.position import Position
from app.models.market_candle import MarketCandle
from app.models.order import Order
from app.models.fill import Fill


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
