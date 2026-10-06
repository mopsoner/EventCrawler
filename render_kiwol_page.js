const { chromium } = require('playwright');
const { newBrowserPage } = require('./playwright_helpers');

const EVENT_LINKS = 'a[href*="/billetterie/"]';
const MORE_LABEL = /^(?:(?:voir|afficher|charger)\s+(?:plus|tout|tous|toutes)(?:\s+(?:les\s+|des\s+|de\s+|d['’])?(?:événements?|evenements?|résultats?|resultats?))?|tout voir|load more|show (?:more|all))\s*[.!…]*$/i;

function validateKiwolUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['kiwol.com', 'www.kiwol.com'].includes(url.hostname)
      || url.port || url.username || url.password
      || !/^\/(?:agenda\/?|billetterie\/\d+\/?)$/.test(url.pathname)) {
    throw new Error('URL Kiwol non autorisée');
  }
  return url;
}

async function eventCards(page) {
  return page.locator(EVENT_LINKS).evaluateAll(anchors => anchors.flatMap(anchor => {
    const url = new URL(anchor.href);
    const match = url.pathname.match(/^\/billetterie\/(\d+)\/?$/);
    return match && ['kiwol.com', 'www.kiwol.com'].includes(url.hostname)
      ? [{ id: match[1], html: anchor.outerHTML }] : [];
  }));
}

// This only clicks listing controls, never ticket/checkout controls.
async function collectAgenda(page, { maxLoads = 100, progressTimeout = 15000 } = {}) {
  const collected = new Map();
  for (let load = 0; ; load++) {
    for (const card of await eventCards(page)) collected.set(card.id, card.html);
    const controls = page.getByRole('button', { name: MORE_LABEL })
      .or(page.getByRole('link', { name: MORE_LABEL }));
    let more = null;
    for (let index = 0; index < await controls.count(); index++) {
      const candidate = controls.nth(index);
      if (await candidate.isVisible() && await candidate.isEnabled()) {
        more = candidate;
        break;
      }
    }
    if (!more) break;
    if (load >= maxLoads) throw new Error('Agenda Kiwol incomplet : limite de chargement atteinte');
    const known = [...collected.keys()];
    await more.click();
    // Wait for actual new events, rather than a fixed delay or an open socket.
    await page.waitForFunction(ids => [...document.querySelectorAll('a[href*="/billetterie/"]')].some(a => {
      const url = new URL(a.href);
      const match = url.pathname.match(/^\/billetterie\/(\d+)\/?$/);
      return match && ['kiwol.com', 'www.kiwol.com'].includes(url.hostname) && !ids.includes(match[1]);
    }), known, { timeout: progressTimeout });
  }
  // Retain cards from earlier batches even if the site replaces the list.
  return `${await page.content()}\n<section data-kiwol-collected-events>${[...collected.values()].join('\n')}</section>`;
}

async function renderKiwolPage(value) {
  const url = validateKiwolUrl(value);
  const { browser, page } = await newBrowserPage(chromium, { headless: true });
  try {
    await page.route('**/*', route => {
      if (route.request().isNavigationRequest() && route.request().frame() === page.mainFrame()) {
        try { validateKiwolUrl(route.request().url()); } catch { return route.abort(); }
      }
      return route.continue();
    });
    const response = await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    if (!response || !response.ok()) throw new Error(`Kiwol HTTP ${response?.status()}`);
    validateKiwolUrl(page.url());
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    return url.pathname.startsWith('/agenda') ? await collectAgenda(page) : await page.content();
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  renderKiwolPage(process.argv[2]).then(html => process.stdout.write(html)).catch(error => {
    process.stderr.write(error.message);
    process.exitCode = 1;
  });
}

module.exports = { collectAgenda, validateKiwolUrl };
