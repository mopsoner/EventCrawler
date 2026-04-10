from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.fill import FillRead
from app.services.fill_service import FillService

router = APIRouter()


@router.get("", response_model=list[FillRead])
def list_fills(limit: int = Query(default=100, ge=1, le=1000), db: Session = Depends(get_db)) -> list[FillRead]:
    return FillService(db).list_fills(limit=limit)
