const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { headlessFromEnv, newBrowserPage } = require('./playwright_helpers');

const DEFAULT_URLS = [
  'https://www.bizouk.com/?region=paris',
  'https://www.kiwol.com/',
];

function parseArgs(argv) {
  const args = { urls: [], out: path.join('data', 'page_analysis.json'), headless: headlessFromEnv('PLAYWRIGHT_HEADLESS', true) };
  for (let i = 2; i < argv.length; i++) {
    const value = argv[i];
    if (value === '--url' && argv[i + 1]) args.urls.push(argv[++i]);
    else if (value === '--out' && argv[i + 1]) args.out = argv[++i];
    else if (value === '--headed') args.headless = false;
  }
  if (!args.urls.length) args.urls = DEFAULT_URLS;
  return args;
}

function detectSource(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes('kiwol.com')) return 'kiwol';
  } catch {}
  return 'bizouk';
}

async function safeText(locator, max = 500) {
  try {
    const text = (await locator.textContent({ timeout: 1500 })) || '';
    return text.replace(/\s+/g, ' ').trim().slice(0, max);
  } catch {
    return null;
  }
}

async function countSelector(page, selector) {
  try { return await page.locator(selector).count(); } catch { return 0; }
}

async function collectJsonLd(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map((node) => {
    try { return JSON.parse(node.textContent || '{}'); } catch { return null; }
  }).filter(Boolean));
}

async function analyzeUrl(page, url) {
  const source = detectSource(url);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

  const eventLinkSelector = source === 'kiwol'
    ? "a.ticketing-card-search-container[href], a[href*='/billetterie/']"
    : "a[href*='/events/details/']";
  const ticketSelectors = [
    "button:has-text('Réserver')",
    "a:has-text('Réserver')",
    "button:has-text('Continuer')",
    "button:has-text('+')",
    ".qty-plus",
    ".ticketing-card-search-container",
    "[class*='ticket']",
    "[class*='billet']",
  ];

  const links = await page.locator(eventLinkSelector).evaluateAll((nodes) => nodes.slice(0, 20).map((node) => ({
    href: node.href || node.getAttribute('href'),
    text: (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240),
    classes: node.getAttribute('class') || '',
  }))).catch(() => []);

  const headings = await page.locator('h1, h2, h3').evaluateAll((nodes) => nodes.slice(0, 30).map((node) => ({
    tag: node.tagName.toLowerCase(),
    text: (node.textContent || '').replace(/\s+/g, ' ').trim(),
    classes: node.getAttribute('class') || '',
  }))).catch(() => []);

  const selectors = {};
  for (const selector of [eventLinkSelector, ...ticketSelectors]) selectors[selector] = await countSelector(page, selector);

  return {
    source,
    url,
    finalUrl: page.url(),
    title: await page.title(),
    eventLinkSelector,
    eventLinks: links,
    selectors,
    headings,
    bodyExcerpt: await safeText(page.locator('body'), 1200),
    jsonLd: await collectJsonLd(page),
  };
}

async function main() {
  const args = parseArgs(process.argv);
  const { browser, page } = await newBrowserPage(chromium, {
    headless: args.headless,
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 EventCrawlerAnalyzer/1.1',
  });
  const results = [];
  try {
    for (const url of args.urls) {
      try { results.push(await analyzeUrl(page, url)); }
      catch (error) { results.push({ url, source: detectSource(url), error: String(error && error.message ? error.message : error) }); }
    }
  } finally {
    await browser.close();
  }
  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.writeFileSync(args.out, JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2));
  console.log(`Wrote ${args.out} (${results.length} page(s))`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
