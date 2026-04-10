from fastapi import APIRouter

from app.api.routes import assets, executor, fills, health, live_runs, market_data, orders, pipeline, positions, services, trade_candidates

api_router = APIRouter()
api_router.include_router(health.router, prefix="/api/v1", tags=["health"])
api_router.include_router(services.router, prefix="/api/v1", tags=["services"])
api_router.include_router(pipeline.router, prefix="/api/v1", tags=["pipeline"])
api_router.include_router(executor.router, prefix="/api/v1", tags=["executor"])
api_router.include_router(assets.router, prefix="/api/v1/assets", tags=["assets"])
api_router.include_router(live_runs.router, prefix="/api/v1/live-runs", tags=["live-runs"])
api_router.include_router(trade_candidates.router, prefix="/api/v1/trade-candidates", tags=["trade-candidates"])
api_router.include_router(positions.router, prefix="/api/v1/positions", tags=["positions"])
api_router.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])
api_router.include_router(fills.router, prefix="/api/v1/fills", tags=["fills"])
api_router.include_router(market_data.router, prefix="/api/v1/market-data", tags=["market-data"])
