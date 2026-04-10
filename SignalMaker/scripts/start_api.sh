#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
source .venv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8080}
