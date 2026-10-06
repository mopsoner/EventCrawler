# EventCrawler

Bizouk/Kiwol event monitor for Raspberry.

EventCrawler crawls event listing pages, stores events/products in SQLite, and records product history so you can spot price, free-ticket, and availability changes over time.

## Install
Python 3.10 or newer is supported.

```bash
curl -fsSL https://raw.githubusercontent.com/mopsoner/EventCrawler/main/install.sh -o install.sh && chmod +x install.sh && ./install.sh
```

## Run
```bash
cd ~/EventCrawler && chmod +x run.sh && ./run.sh
```

`./run.sh` lance ensemble le serveur web, le planificateur et le consommateur
de la file persistante `booking_jobs`. L'arrêt du script arrête également le
planificateur afin de ne pas laisser de processus orphelin.

Au premier lancement, un mot de passe administrateur aléatoire est créé dans
`data/admin_password` (permissions `0600`). Connectez-vous avec l'utilisateur
`admin` et ce mot de passe. Par défaut, le serveur écoute uniquement sur
`127.0.0.1:5080`; utilisez
un tunnel SSH ou un reverse proxy HTTPS authentifié pour un accès distant.

Les variables `EVENTCRAWLER_ADMIN_USERNAME`, `EVENTCRAWLER_ADMIN_PASSWORD`,
`EVENTCRAWLER_SECRET_KEY`, `EVENTCRAWLER_HOST` et `EVENTCRAWLER_HTTPS` permettent
de fournir les paramètres depuis un gestionnaire de secrets. Ne publiez jamais
directement le port Flask.

Pour une installation de production, le serveur web et le planificateur restent
disponibles comme services systemd séparés. Le planificateur exécute les parcours
planifiés et traite également la file persistante `booking_jobs` :

```bash
cd ~/EventCrawler
.venv/bin/python scheduler.py
```

`install_startup_service.sh` installe les services web et planificateur séparément.
Le worker de réservation démarre uniquement dans le processus planificateur ;
les éventuels workers multiples du serveur web ne consomment donc pas cette file
en parallèle.

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

### Agenda Kiwol

Dans `/config`, ajoutez une région `kiwol_agenda` avec l'URL
`https://www.kiwol.com/agenda`, puis activez-la et lancez un parcours depuis le
tableau de bord. Les nouvelles configurations proposent déjà cette entrée,
désactivée. Les configurations existantes sont conservées. Pour limiter la
collecte à un territoire, utilisez par exemple
`https://www.kiwol.com/agenda?location=GP`.

Le parcours Kiwol utilise `render_kiwol_page.js` et Playwright pour actionner les
contrôles « Afficher plus de résultat », « Charger plus » ou « Voir tous les événements ». Il conserve les lots
précédents, déduplique les liens `/billetterie/<id>` et signale une erreur si le
chargement reste bloqué ou dépasse sa limite. Les pages détaillées sont lues en
HTML, avec rendu navigateur lorsque les données de billetterie manquent. Les
offres structurées alimentent les mêmes tables, historique de prix, pages de
billets gratuits, opportunités et file de réservation que les autres sources.
Un stock non précisé reste inconnu ; il ne déclenche pas une réservation
automatique. Le parcours de collecte ne clique pas sur les boutons de réservation.

Installez Chromium avec `npm ci` et assurez-vous que les processus Python/Node
utilisent le même `PLAYWRIGHT_BROWSERS_PATH` si cette variable est définie.
L'environnement réseau doit permettre `www.kiwol.com`, `api.kiwol.com` (chargement
de l'agenda), `d27w5wcpsj3982.cloudfront.net` (affiches), ainsi que les
téléchargements Playwright. Le navigateur doit faire confiance au certificat
CA du proxy lorsqu'un proxy HTTPS est utilisé ; ne désactivez pas la vérification TLS.

Tests locaux de l'intégration :

```bash
.venv/bin/python -m pytest tests/test_kiwol_source.py -q
node --test tests/kiwol_agenda.test.js
```

Ces tests utilisent des extraits publics capturés sur l'agenda et l'événement
13402, ainsi que des pages contrôlées pour tester les chargements asynchrones
dans un vrai navigateur. La vérification du chargement complet sur le site
nécessite l'accès à son API.

## HTML/page analysis helper

Use Playwright to inspect current Bizouk/Kiwol pages and save the selectors, headings, event links, body excerpt, and JSON-LD blocks found on each page:

```bash
npm run analyze:pages -- --url "https://www.kiwol.com/" --url "https://www.bizouk.com/?region=paris" --out data/page_analysis.json
```

You can pass event detail pages too, for example:

```bash
npm run analyze:pages -- --url "https://www.kiwol.com/billetterie/12636" --url "https://www.bizouk.com/events/details/black-xs-edition-dark-carnival/114847"
```

The generated JSON is useful before changing crawler selectors or booking Playwright scripts.

## Playwright booking scripts

The Bizouk and Kiwol booking helpers now share the same Playwright launch/context defaults through `playwright_helpers.js`: headless mode is controlled by `PLAYWRIGHT_HEADLESS`, slow motion by `PLAYWRIGHT_SLOWMO`, and every run uses a French locale, Antilles timezone, browser-like headers, and container-safe Chromium flags.

## Bizouk data quality

Bizouk event pages are accepted only when their event identity and required fields
pass validation. Text, Guadeloupe communes, French/Guadeloupe phone numbers and
local wall times are normalized before persistence; rejected pages remain in
`crawl_errors`. The JSON quality summary for each run is stored in
`crawl_runs.notes`. The additive `events.event_end_date` column stores an ISO 8601
end date when Bizouk supplies one and is created automatically by `init_db()`.
Local mobile numbers beginning with `0690` are stored with Guadeloupe's `+590`
country code; other French local numbers use `+33`. Existing international
`+590` and `+33` numbers are kept in E.164 form.

```bash
npm run book:bizouk -- --event-url "https://www.bizouk.com/events/details/<slug>/<id>" --ticket-count 1 --email "client@example.com" --product-name "Nom du billet"
npm run book:kiwol -- --event-url "https://www.kiwol.com/billetterie/<id>" --ticket-count 1 --email "client@example.com" --product-name "Nom du billet"
```

For local debugging, use `PLAYWRIGHT_HEADLESS=0 PLAYWRIGHT_SCREENSHOTS=1` to open the browser and save step screenshots under `data/booking_screens/`.
