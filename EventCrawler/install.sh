#!/usr/bin/env bash
set -e
python3 -m venv .venv || true
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
