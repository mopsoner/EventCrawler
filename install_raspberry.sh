#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME/EventCrawler"
PYTHON_BIN="python3"

printf '\n[1/8] Installing system packages...\n'
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

printf '\n[2/8] Cloning or updating repository...\n'
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone https://github.com/mopsoner/EventCrawler.git "$REPO_DIR"
fi

cd "$REPO_DIR"

printf '\n[3/8] Creating virtual environment...\n'
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

printf '\n[4/8] Upgrading pip...\n'
pip install --upgrade pip

printf '\n[5/8] Installing Python dependencies...\n'
pip install -r requirements.txt

printf '\n[6/8] Installing Playwright browser...\n'
python -m playwright install chromium

printf '\n[7/8] Installing Playwright system dependencies...\n'
python -m playwright install-deps chromium

printf '\n[8/8] Preparing directories...\n'
mkdir -p data exports
chmod +x crawler.py app.py || true

cat <<'EOF'

Installation complete.

Next commands:
  cd ~/EventCrawler
  source .venv/bin/activate
  python crawler.py
  python app.py

Then open:
  http://<RASPBERRY_IP>:8000

EOF
