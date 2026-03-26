#!/usr/bin/env bash
set -euo pipefail

ARCH="$(uname -m)"
DEB_ARCH="$(dpkg --print-architecture 2>/dev/null || true)"

if [ "$ARCH" = "aarch64" ] || [ "$DEB_ARCH" = "arm64" ]; then
  echo "64-bit system detected -> installing full Playwright version"
  curl -fsSL https://raw.githubusercontent.com/mopsoner/EventCrawler/main/install_raspberry_v2.sh -o /tmp/install_eventcrawler.sh
else
  echo "32-bit system detected -> installing lite version without Playwright"
  curl -fsSL https://raw.githubusercontent.com/mopsoner/EventCrawler/main/install_raspberry_lite.sh -o /tmp/install_eventcrawler.sh
fi

chmod +x /tmp/install_eventcrawler.sh
/tmp/install_eventcrawler.sh
