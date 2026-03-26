#!/usr/bin/env bash
set -euo pipefail
. .venv/bin/activate
mkdir -p data exports
python crawler.py
python app.py
