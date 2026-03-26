# EventCrawler

Clean Raspberry-friendly Bizouk monitor.

This version uses a universal HTML crawler with `requests + BeautifulSoup`, so it works on 32-bit and 64-bit systems without Playwright.

## Install
```bash
curl -fsSL https://raw.githubusercontent.com/mopsoner/EventCrawler/main/install.sh -o install.sh && chmod +x install.sh && ./install.sh
```

## Run
```bash
cd ~/EventCrawler && chmod +x run.sh && ./run.sh
```

## Pages
- `/`
- `/events`
- `/free`
- `/opportunities`

## Notes
Some JavaScript-rendered content may be missed.
