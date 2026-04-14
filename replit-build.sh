#!/usr/bin/env bash
set -eux

python3 -m venv .venv
. .venv/bin/activate

python -m pip install --upgrade pip
pip install -r EventCrawler/requirements.txt

npm install
npx playwright install chromium

mkdir -p EventCrawler/data

echo "Replit build completed successfully."
