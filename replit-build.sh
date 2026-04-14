#!/usr/bin/env bash
set -eux

python3 -m venv .venv
. .venv/bin/activate

PIP_USER=0 python -m pip install --upgrade pip
PIP_USER=0 pip install -r EventCrawler/requirements.txt

cd EventCrawler
npm install
npx playwright install chromium
cd ..

mkdir -p EventCrawler/data

echo "Replit build completed successfully."
