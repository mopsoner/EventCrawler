#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required on the VM"
  exit 1
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv --system-site-packages
fi

source .venv/bin/activate
.venv/bin/pip install -q -r requirements.txt

mkdir -p logs data

if [ -n "${PGHOST:-}" ] && [ -n "${PGUSER:-}" ] && [ -n "${PGPASSWORD:-}" ] && [ -n "${PGDATABASE:-}" ]; then
  _SSLMODE="${PGSSLMODE:-disable}"
  export DATABASE_URL="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE}?sslmode=${_SSLMODE}"
fi

python -m scripts.init_db

echo "SignalMaker VM deploy complete"
echo "Run next: bash run.sh api"
