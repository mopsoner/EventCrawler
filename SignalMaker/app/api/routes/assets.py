from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.asset_state import AssetStateRead, AssetStateUpsert
from app.services.asset_state_service import AssetStateService

router = APIRouter()


@router.get("", response_model=list[AssetStateRead])
def list_assets(
    limit: int = Query(default=100, ge=1, le=1000),
    min_score: float | None = Query(default=None),
    stage: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AssetStateRead]:
    return AssetStateService(db).list_assets(limit=limit, min_score=min_score, stage=stage)


@router.get("/{symbol}", response_model=AssetStateRead)
def get_asset(symbol: str, db: Session = Depends(get_db)) -> AssetStateRead:
    asset = AssetStateService(db).get_by_symbol(symbol)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.post("/{symbol}", response_model=AssetStateRead)
def upsert_asset(symbol: str, payload: AssetStateUpsert, db: Session = Depends(get_db)) -> AssetStateRead:
    return AssetStateService(db).upsert(symbol=symbol, payload=payload)
