import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.pipeline_service import PipelineService


if __name__ == "__main__":
    while True:
        db = SessionLocal()
        try:
            result = PipelineService(db).run_once(limit=settings.binance_max_symbols)
            print(result)
        finally:
            db.close()
        time.sleep(60)
