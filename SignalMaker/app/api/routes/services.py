from fastapi import APIRouter

from app.services.collector_service import CollectorService
from app.services.scheduler_service import SchedulerService
from app.services.signal_engine_service import SignalEngineService
from app.services.planner_service import PlannerService

router = APIRouter()


@router.get("/services")
def services_status() -> dict:
    return {"collector": CollectorService().heartbeat(), "signal_engine": SignalEngineService().heartbeat(), "planner": PlannerService().heartbeat(), "scheduler": SchedulerService().heartbeat()}
