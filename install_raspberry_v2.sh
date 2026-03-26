#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME/EventCrawler"
PYTHON_BIN="python3"
ARCH="$(uname -m)"
DEB_ARCH="$(dpkg --print-architecture 2>/dev/null || true)"

printf '\n[1/10] Installing system packages...\n'
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-dev git curl

printf '\n[2/10] Cloning or updating repository...\n'
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone https://github.com/mopsoner/EventCrawler.git "$REPO_DIR"
fi

cd "$REPO_DIR"

printf '\n[3/10] Checking Raspberry architecture...\n'
echo "uname -m: $ARCH"
echo "dpkg arch: ${DEB_ARCH:-unknown}"
if [ "$ARCH" != "aarch64" ] && [ "$DEB_ARCH" != "arm64" ]; then
  echo
  echo "ERROR: Playwright Python on Raspberry Pi needs a 64-bit OS (aarch64 / arm64)."
  echo "Your current system appears to be 32-bit."
  echo "Please install Raspberry Pi OS 64-bit, then run this script again."
  exit 1
fi

printf '\n[4/10] Creating virtual environment...\n'
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

printf '\n[5/10] Upgrading pip tooling...\n'
python -m pip install --upgrade pip setuptools wheel

printf '\n[6/10] Installing Python dependencies except Playwright...\n'
python -m pip install Flask==3.1.0 pydantic==2.10.6 python-dateutil==2.9.0.post0

printf '\n[7/10] Installing Playwright separately...\n'
python -m pip install playwright

printf '\n[8/10] Installing Chromium browser for Playwright...\n'
python -m playwright install chromium

printf '\n[9/10] Installing Playwright system dependencies...\n'
python -m playwright install-deps chromium

printf '\n[10/10] Preparing directories and permissions...\n'
mkdir -p data exports
chmod +x crawler.py app.py run.sh || true

cat <<'EOF'

Installation complete.

Run with:
  cd ~/EventCrawler
  chmod +x run.sh
  ./run.sh

Or manually:
  cd ~/EventCrawler
  source .venv/bin/activate
  python crawler.py
  python app.py

Then open:
  http://<RASPBERRY_IP>:8000

EOF
