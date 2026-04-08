#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-$HOME/Desktop/EventCrawler}"
SERVICE_NAME="eventcrawler"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER")"
WORKING_DIR="$APP_DIR"
VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
NODE_BIN="$(command -v node || true)"
NPM_BIN="$(command -v npm || true)"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.cache/ms-playwright"

if [[ ! -d "$APP_DIR" ]]; then
  echo "App directory not found: $APP_DIR"
  exit 1
fi

if [[ -z "$NODE_BIN" || -z "$NPM_BIN" ]]; then
  echo "Node.js and npm are required before running this installer."
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install -r "$APP_DIR/requirements.txt"

cd "$APP_DIR"
npm install

export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH"
npx playwright install chromium

if command -v sudo >/dev/null 2>&1; then
  if npx playwright install-deps chromium >/dev/null 2>&1; then
    echo "Playwright system dependencies installed."
  else
    echo "Playwright install-deps skipped or not available on this host."
  fi
fi

sudo tee "$SERVICE_PATH" >/dev/null <<EOF
[Unit]
Description=EventCrawler web app
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$WORKING_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH
Environment=PLAYWRIGHT_HEADLESS=1
Environment=PLAYWRIGHT_SLOWMO=0
ExecStart=/bin/bash -lc 'cd "$WORKING_DIR" && git pull --ff-only && "$PYTHON_BIN" app.py'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo
echo "Installed and started: $SERVICE_NAME"
echo "Check status with: sudo systemctl status $SERVICE_NAME"
echo "View logs with: journalctl -u $SERVICE_NAME -f"
