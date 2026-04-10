import time

from app.db.session import SessionLocal
from app.services.executor_service import ExecutorService


if __name__ == "__main__":
    while True:
        db = SessionLocal()
        try:
            result = ExecutorService(db).execute_open_candidates(limit=10, quantity=1.0)
            print(result)
        finally:
            db.close()
        time.sleep(30)
