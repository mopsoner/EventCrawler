const { chromium } = require('playwright');
const { newBrowserPage } = require('./playwright_helpers');

const allowedHosts = new Set(['bizouk.com', 'www.bizouk.com']);

async function main() {
  const rawUrl = process.argv[2];
  const url = new URL(rawUrl);
  if (url.protocol !== 'https:' || !allowedHosts.has(url.hostname) || url.port) {
    throw new Error('URL Bizouk non autorisee');
  }

  const { browser, page } = await newBrowserPage(chromium, { headless: true });
  try {
    await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.locator('h1, main, [class*="event"]').first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.locator('[class*="ticket"], [class*="billet"], [data-ticket-id], [data-product-id]').first()
      .waitFor({ timeout: 8000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    process.stdout.write(await page.content());
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(String(error && error.message ? error.message : error));
  process.exit(1);
});
