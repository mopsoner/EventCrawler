#!/usr/bin/env bash
set -euo pipefail
. .venv/bin/activate
mkdir -p data exports
python app.py
