#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

bash scripts/deploy_vm.sh

echo "Bootstrap complete"
echo "Start API:        bash scripts/start_api.sh"
echo "Start pipeline:   bash scripts/start_pipeline_worker.sh"
echo "Start executor:   bash scripts/start_executor_worker.sh"
echo "Start scheduler:  bash scripts/start_scheduler_worker.sh"
