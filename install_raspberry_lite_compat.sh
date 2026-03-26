#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME/EventCrawler"

printf '\n[1/7] Installing system packages...\n'
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-dev git curl

printf '\n[2/7] Cloning or updating repository...\n'
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone https://github.com/mopsoner/EventCrawler.git "$REPO_DIR"
fi

cd "$REPO_DIR"

printf '\n[3/7] Creating virtual environment...\n'
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

printf '\n[4/7] Upgrading pip tooling...\n'
python -m pip install --upgrade pip setuptools wheel

printf '\n[5/7] Installing lite compat Python dependencies...\n'
python -m pip install -r requirements_lite_compat.txt

printf '\n[6/7] Preparing directories...\n'
mkdir -p data exports
chmod +x lite_crawler_compat.py app.py run_lite_compat.sh || true

printf '\n[7/7] Done.\n'
cat <<'EOF'

Run with:
  cd ~/EventCrawler
  chmod +x run_lite_compat.sh
  ./run_lite_compat.sh

This 32-bit lite compat mode does not use Playwright or lxml.
It crawls HTML directly and may miss JS-rendered content.

EOF
