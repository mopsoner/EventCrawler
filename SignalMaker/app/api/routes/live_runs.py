from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.live_run import LiveRunRead
from app.services.live_run_service import LiveRunService

router = APIRouter()


@router.get("", response_model=list[LiveRunRead])
def list_live_runs(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)) -> list[LiveRunRead]:
    return LiveRunService(db).list_runs(limit=limit)
