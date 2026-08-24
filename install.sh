#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv || true
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
chmod 700 data
if command -v npm >/dev/null 2>&1; then
  npm ci
fi
