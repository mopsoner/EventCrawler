# EventCrawler

An automated event monitoring and booking preparation tool for the [Bizouk](https://www.bizouk.com) platform (Caribbean-themed events).

## Overview

EventCrawler lets users track events across regions (London, Paris, Guadeloupe, Rotterdam), monitor ticket availability and price changes, and automate the initial steps of the booking process.

## Tech Stack

- **Backend:** Python 3 / Flask
- **Scraping:** `requests` + `BeautifulSoup4` for HTML parsing; Node.js + Playwright for booking automation
- **Database:** SQLite3 (stored in `data/eventcrawler.sqlite`)
- **Frontend:** Jinja2 server-side rendered templates + vanilla JS/CSS
- **Package managers:** pip (Python), npm (Node.js)

## Project Structure

```
app.py              - Main Flask app + background scheduler
crawler.py          - Bizouk scraper (run by scheduler or manually)
booking_prepare.js  - Playwright automation for booking flow
config_store.py     - Config load/save (data/config.json)
templates/          - Jinja2 HTML templates
static/             - CSS and JS assets
data/               - Runtime data: SQLite DB, logs, state JSON files
requirements.txt    - Python dependencies
package.json        - Node.js dependencies (Playwright)
```

## Running Locally (Replit)

The app runs via the **Start application** workflow:
```
python app.py
```
It listens on `0.0.0.0:5000`.

## Key Features

- Multi-region event monitoring
- Smart event scoring (keywords, region, free tickets)
- Price history tracking
- Booking automation via Playwright (Chromium)

## Deployment

Deployed as a VM target (always-on) because the app uses a persistent background scheduler thread.
Run command: `gunicorn --bind=0.0.0.0:5000 --reuse-port --workers=1 app:app`
