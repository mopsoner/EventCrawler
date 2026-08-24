#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -d .git ]; then
  git pull --ff-only || true
fi

. .venv/bin/activate
python app.py
