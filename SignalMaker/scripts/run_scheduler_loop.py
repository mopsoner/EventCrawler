import time

from app.db.session import SessionLocal
from app.services.executor_service import ExecutorService
from app.services.pipeline_service import PipelineService


if __name__ == "__main__":
    tick = 0
    while True:
        db = SessionLocal()
        try:
            if tick % 2 == 0:
                print(PipelineService(db).run_once(limit=10))
            print(ExecutorService(db).execute_open_candidates(limit=10, quantity=1.0))
        finally:
            db.close()
        tick += 1
        time.sleep(30)
