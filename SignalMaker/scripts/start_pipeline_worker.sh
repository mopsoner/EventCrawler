#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
source .venv/bin/activate
exec python -m scripts.run_pipeline_loop
