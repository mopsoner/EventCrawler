# EventCrawler

Bizouk/Kiwol event monitor for Raspberry.

EventCrawler crawls event listing pages, stores events/products in SQLite, and records product history so you can spot price, free-ticket, and availability changes over time.

## Install
```bash
curl -fsSL https://raw.githubusercontent.com/mopsoner/EventCrawler/main/install.sh -o install.sh && chmod +x install.sh && ./install.sh
```

## Run
```bash
cd ~/EventCrawler && chmod +x run.sh && ./run.sh
```

Au premier lancement, un mot de passe administrateur aléatoire est créé dans
`data/admin_password` (permissions `0600`). Connectez-vous avec l'utilisateur
`admin` et ce mot de passe. Le serveur écoute uniquement sur `127.0.0.1`; utilisez
un tunnel SSH ou un reverse proxy HTTPS authentifié pour un accès distant.

Les variables `EVENTCRAWLER_ADMIN_USERNAME`, `EVENTCRAWLER_ADMIN_PASSWORD`,
`EVENTCRAWLER_SECRET_KEY`, `EVENTCRAWLER_HOST` et `EVENTCRAWLER_HTTPS` permettent
de fournir les paramètres depuis un gestionnaire de secrets. Ne publiez jamais
directement le port Flask.

Le planificateur est prévu comme processus séparé :

```bash
cd ~/EventCrawler
.venv/bin/python scheduler.py
```

`install_startup_service.sh` installe les services web et planificateur séparément.

## Pages
- `/`
- `/events`
- `/free`
- `/opportunities`
- `/config`

## Supported sources

Source-specific URL parsing is centralized in `source_profiles.py`:

- Bizouk event URLs: `https://www.bizouk.com/events/details/<slug>/<id>`
- Kiwol event URLs: `https://www.kiwol.com/billetterie/<id>`

The crawler uses those profiles to normalize event URLs, deduplicate events by source/id, and extract links from listing pages.

## HTML/page analysis helper

Use Playwright to inspect current Bizouk/Kiwol pages and save the selectors, headings, event links, body excerpt, and JSON-LD blocks found on each page:

```bash
cd EventCrawler
npm run analyze:pages -- --url "https://www.kiwol.com/" --url "https://www.bizouk.com/?region=paris" --out data/page_analysis.json
```

You can pass event detail pages too, for example:

```bash
npm run analyze:pages -- --url "https://www.kiwol.com/billetterie/12636" --url "https://www.bizouk.com/events/details/black-xs-edition-dark-carnival/114847"
```

The generated JSON is useful before changing crawler selectors or booking Playwright scripts.

## Playwright booking scripts

The Bizouk and Kiwol booking helpers now share the same Playwright launch/context defaults through `playwright_helpers.js`: headless mode is controlled by `PLAYWRIGHT_HEADLESS`, slow motion by `PLAYWRIGHT_SLOWMO`, and every run uses a French locale, Antilles timezone, browser-like headers, and container-safe Chromium flags.

```bash
cd EventCrawler
npm run book:bizouk -- --event-url "https://www.bizouk.com/events/details/<slug>/<id>" --ticket-count 1 --email "client@example.com" --product-name "Nom du billet"
npm run book:kiwol -- --event-url "https://www.kiwol.com/billetterie/<id>" --ticket-count 1 --email "client@example.com" --product-name "Nom du billet"
```

For local debugging, use `PLAYWRIGHT_HEADLESS=0 PLAYWRIGHT_SCREENSHOTS=1` to open the browser and save step screenshots under `data/booking_screens/`.
