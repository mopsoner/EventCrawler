from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.executor_service import ExecutorService

router = APIRouter()


@router.post("/executor/run-once")
def execute_candidates(limit: int = Query(default=10, ge=1, le=100), quantity: float = Query(default=1.0, gt=0), db: Session = Depends(get_db)) -> dict:
    return ExecutorService(db).execute_open_candidates(limit=limit, quantity=quantity)
