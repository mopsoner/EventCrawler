#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv --system-site-packages
fi

source .venv/bin/activate
.venv/bin/pip install -q -r requirements.txt

if [ -n "${PGHOST:-}" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGPASSWORD:-}" ] && [ -n "${PGDATABASE:-}" ]; then
  _SSLMODE="${PGSSLMODE:-disable}"
  export DATABASE_URL="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE}?sslmode=${_SSLMODE}"
fi

MODE="${1:-api}"

case "$MODE" in
  api)
    uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8080}
    ;;
  dev)
    uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8080} --reload
    ;;
  init-db)
    python -m scripts.init_db
    ;;
  pipeline-once)
    python - <<'PY'
from app.db.session import SessionLocal
from app.services.pipeline_service import PipelineService

db = SessionLocal()
try:
    print(PipelineService(db).run_once(limit=5))
finally:
    db.close()
PY
    ;;
  executor-once)
    python - <<'PY'
from app.db.session import SessionLocal
from app.services.executor_service import ExecutorService

db = SessionLocal()
try:
    print(ExecutorService(db).execute_open_candidates(limit=10, quantity=1.0))
finally:
    db.close()
PY
    ;;
  pipeline-loop)
    python -m scripts.run_pipeline_loop
    ;;
  executor-loop)
    python -m scripts.run_executor_loop
    ;;
  scheduler-loop)
    python -m scripts.run_scheduler_loop
    ;;
  *)
    echo "Usage: bash run.sh [api|dev|init-db|pipeline-once|executor-once|pipeline-loop|executor-loop|scheduler-loop]"
    exit 1
    ;;
esac
