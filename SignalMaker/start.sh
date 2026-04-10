#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export DATABASE_URL="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE}?sslmode=disable"
source .venv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
