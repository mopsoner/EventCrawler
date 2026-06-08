const DEFAULT_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 EventCrawlerPlaywright/1.1';

function envBoolean(name, defaultValue = false) {
  const raw = process.env[name];
  if (typeof raw === 'undefined' || raw === '') return defaultValue;
  const value = String(raw).trim().toLowerCase();
  if (['1', 'true', 'yes', 'y', 'on'].includes(value)) return true;
  if (['0', 'false', 'no', 'n', 'off'].includes(value)) return false;
  return defaultValue;
}

function envNumber(name, defaultValue) {
  const raw = process.env[name];
  if (typeof raw === 'undefined' || raw === '') return defaultValue;
  const value = Number(raw);
  return Number.isFinite(value) ? value : defaultValue;
}

function headlessFromEnv(name = 'PLAYWRIGHT_HEADLESS', defaultValue = true) {
  return envBoolean(name, defaultValue);
}

function buildLaunchOptions({ headless = true, slowMo = 0 } = {}) {
  return {
    headless,
    slowMo,
    args: [
      '--disable-dev-shm-usage',
      '--no-sandbox',
      '--disable-blink-features=AutomationControlled',
    ],
  };
}

function buildContextOptions(options = {}) {
  return {
    userAgent: options.userAgent || DEFAULT_USER_AGENT,
    locale: options.locale || 'fr-FR',
    timezoneId: options.timezoneId || 'America/Guadeloupe',
    viewport: options.viewport || { width: 1366, height: 900 },
    extraHTTPHeaders: {
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.7,en;q=0.6',
      ...(options.extraHTTPHeaders || {}),
    },
  };
}

async function newBrowserPage(chromium, options = {}) {
  const browser = await chromium.launch(buildLaunchOptions(options));
  const context = await browser.newContext(buildContextOptions(options));
  const page = await context.newPage();
  return { browser, context, page };
}

module.exports = {
  DEFAULT_USER_AGENT,
  buildContextOptions,
  buildLaunchOptions,
  envBoolean,
  envNumber,
  headlessFromEnv,
  newBrowserPage,
};
