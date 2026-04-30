#!/bin/bash
set -e

echo "=== Post-merge setup ==="

# Install Python dependencies
if [ ! -d ".venv" ]; then
    echo "Creating Python venv..."
    python3 -m venv .venv
fi

echo "Installing Python dependencies..."
.venv/bin/pip install -q --no-user -r EventCrawler/requirements.txt

# Install Node dependencies in EventCrawler/
echo "Installing Node dependencies..."
cd EventCrawler
npm install --no-fund --no-audit 2>&1
cd ..

# Install Playwright Chromium if needed
echo "Verifying Playwright Chromium..."
cd EventCrawler
node -e "
const { chromium } = require('playwright');
chromium.executablePath().then(p => {
    const fs = require('fs');
    if (!fs.existsSync(p)) {
        console.log('Chromium not found, installing...');
        const { execSync } = require('child_process');
        execSync('npx playwright install chromium', { stdio: 'inherit' });
    } else {
        console.log('Chromium OK:', p);
    }
}).catch(() => {
    const { execSync } = require('child_process');
    execSync('npx playwright install chromium', { stdio: 'inherit' });
});
" 2>/dev/null || npx playwright install chromium
cd ..

echo "=== Post-merge setup complete ==="
