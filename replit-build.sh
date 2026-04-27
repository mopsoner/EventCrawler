#!/usr/bin/env bash
set -eux

echo "==> [1/4] Creating Python virtual environment..."
python3 -m venv .venv
. .venv/bin/activate
PIP_USER=0 python -m pip install --upgrade pip --quiet
PIP_USER=0 pip install -r EventCrawler/requirements.txt --quiet

echo "==> [2/4] Installing Node.js dependencies and Playwright browser..."
cd EventCrawler
npm install --silent
npx playwright install chromium
cd ..

echo "==> [3/4] Creating required data directories..."
mkdir -p EventCrawler/data
mkdir -p EventCrawler/data/booking_failures
mkdir -p EventCrawler/data/booking_screens

echo "==> [4/4] Verifying Playwright / Chromium launch..."
cd EventCrawler
node -e "
const { chromium } = require('playwright');
chromium.launch({ headless: true }).then(b => {
  console.log('  Chromium OK');
  b.close();
}).catch(e => {
  console.error('  Chromium FAILED:', e.message);
  process.exit(1);
});
"
cd ..

echo "Replit build completed successfully."
