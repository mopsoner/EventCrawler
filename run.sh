#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME/EventCrawler"
cd "$REPO_DIR"

if [ ! -d ".venv" ]; then
  echo "Virtual environment not found. Run ./install_raspberry.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
mkdir -p data exports

python crawler.py
python app.py
