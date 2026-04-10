from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.position import PositionRead
from app.services.position_service import PositionService

router = APIRouter()


@router.get("", response_model=list[PositionRead])
def list_positions(
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PositionRead]:
    return PositionService(db).list_positions(limit=limit, status=status)
