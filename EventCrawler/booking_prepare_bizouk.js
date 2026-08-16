const fs = require('fs');
const path = require('path');
const { envNumber, headlessFromEnv, newBrowserPage } = require('./playwright_helpers');
const { chromium } = require('playwright');

const DATA_DIR = path.join(process.cwd(), 'data');
const STATE_PATH = path.join(DATA_DIR, 'booking_state.json');
const LOG_PATH = path.join(DATA_DIR, 'booking.log');
const SCREEN_DIR = path.join(DATA_DIR, 'booking_screens');
const FAILURE_DIR = path.join(DATA_DIR, 'booking_failures');

const DEFAULT_FIRST_NAME = (process.env.BOOKING_FIRST_NAME || 'Prénom').trim() || 'Prénom';
const DEFAULT_LAST_NAME = (process.env.BOOKING_LAST_NAME || 'Nom').trim() || 'Nom';
const DEFAULT_FULL_NAME = (process.env.BOOKING_FULL_NAME || `${DEFAULT_FIRST_NAME} ${DEFAULT_LAST_NAME}`).trim() || `${DEFAULT_FIRST_NAME} ${DEFAULT_LAST_NAME}`;
const DEFAULT_PHONE = (process.env.BOOKING_PHONE || '0600000000').trim() || '0600000000';
const DEFAULT_GENDER = (process.env.BOOKING_GENDER || 'Homme').trim() || 'Homme';
const DEFAULT_HEADLESS = headlessFromEnv('PLAYWRIGHT_HEADLESS', true);
const DEFAULT_SLOWMO = envNumber('PLAYWRIGHT_SLOWMO', 200);
const SCREENSHOTS_ENABLED = process.env.PLAYWRIGHT_SCREENSHOTS === '1';
const SUCCESS_POLL_ATTEMPTS = Number(process.env.BOOKING_SUCCESS_POLL_ATTEMPTS || '8');
const SUCCESS_POLL_DELAY_MS = Number(process.env.BOOKING_SUCCESS_POLL_DELAY_MS || '2500');
const SELECTOR_RULES = (() => { try { return JSON.parse(process.env.BOOKING_SELECTOR_RULES_JSON || '{}'); } catch { return {}; } })();

function ensureDir(dir) { fs.mkdirSync(dir, { recursive: true }); }
function defaultState() {
  return {
    running: false,
    status: 'idle',
    mode: 'human_approved',
    event_url: null,
    product_name: null,
    ticket_count: 0,
    email: null,
    started_at: null,
    finished_at: null,
    last_error: null,
    log_path: LOG_PATH,
    confirmation_text: null,
  };
}
function atomicWriteJson(filePath, value) {
  ensureDir(path.dirname(filePath));
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporary, filePath);
}

function writeState(fields = {}) {
  ensureDir(DATA_DIR);
  let state = defaultState();
  if (fs.existsSync(STATE_PATH)) {
    try { state = { ...state, ...JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) }; } catch {}
  }
  state = { ...state, ...fields };
  atomicWriteJson(STATE_PATH, state);
}
function logLine(message) {
  ensureDir(DATA_DIR);
  fs.appendFileSync(LOG_PATH, `[${new Date().toISOString()}] ${message}\n`, 'utf8');
}
function slugify(text) {
  return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'booking';
}
function selectorsFor(intent, defaults) {
  const extra = Array.isArray(SELECTOR_RULES[intent]) ? SELECTOR_RULES[intent] : [];
  return [...extra, ...defaults].filter(Boolean).filter((v, i, arr) => arr.indexOf(v) === i);
}
async function screenshot(page, name) {
  if (!SCREENSHOTS_ENABLED) return;
  try {
    ensureDir(SCREEN_DIR);
    await page.screenshot({ path: path.join(SCREEN_DIR, `${name}.png`), fullPage: true });
  } catch {}
}
async function clickFirstVisible(page, selectors, timeout = 4000) {
  for (const selector of selectors) {
    try {
      const locator = page.locator(selector);
      const count = await locator.count();
      for (let i = 0; i < count; i++) {
        const item = locator.nth(i);
        if (await item.isVisible()) {
          await item.click({ timeout });
          return true;
        }
      }
    } catch {}
  }
  return false;
}
async function acceptCookies(page) {
  try {
    const btn = page.locator("button:has-text('Tout accepter'), button:has-text('Accept all'), button:has-text('Accept cookies')").first();
    if (await btn.isVisible({ timeout: 4000 })) {
      await btn.click();
      await page.waitForTimeout(600);
    }
  } catch {}
}
async function saveFailureReport(page, report) {
  try {
    ensureDir(FAILURE_DIR);
    let visibleText = '';
    let htmlExcerpt = '';
    let pageTitle = '';
    let pageUrl = '';
    try { visibleText = ((await page.locator('body').innerText()).trim() || '').slice(0, 4000); } catch {}
    try { htmlExcerpt = (await page.content()).slice(0, 12000); } catch {}
    try { pageTitle = await page.title(); } catch {}
    try { pageUrl = page.url(); } catch {}
    const payload = {
      failure_key: `${report.booking_started_at || Date.now()}-${slugify(report.step_name || report.intent || 'failure')}`,
      booking_started_at: report.booking_started_at || null,
      event_url: report.event_url || null,
      product_name: report.product_name || null,
      step_name: report.step_name || null,
      intent: report.intent || null,
      error_text: String(report.error_text || ''),
      page_url: pageUrl,
      page_title: pageTitle,
      html_excerpt: htmlExcerpt,
      visible_text_excerpt: visibleText,
      tried_selectors: report.tried_selectors || [],
      detected_product_candidates: report.detected_product_candidates || [],
      matched_container_text: report.matched_container_text || null,
      created_at: new Date().toISOString(),
    };
    const name = `${Date.now()}-${slugify(report.step_name || report.intent || 'failure')}.json`;
    fs.writeFileSync(path.join(FAILURE_DIR, name), JSON.stringify(payload, null, 2), 'utf8');
  } catch {}
}
const IGNORED_PRODUCT_WORDS = new Set(['entry', 'entrance', 'entree', 'ticket', 'billet', 'invitation', 'valid', 'valable', 'until', 'jusqu', 'jusqua', 'free', 'gratuit', 'gratuite', 'with', 'avec', 'by', 'par']);
const PRODUCT_TOKEN_ALIASES = new Map([
  ['simple', 'single'], ['seul', 'single'], ['seule', 'single'],
  ['boisson', 'drink'], ['consommation', 'drink'], ['conso', 'drink'],
  ['offert', 'free'], ['offerte', 'free'], ['offerts', 'free'], ['offertes', 'free'],
  ['21h', '9pm'], ['21', '9pm'],
]);
const PLUS_SELECTORS = [
  "button:has-text('+')", "a:has-text('+')", "[role='button']:has-text('+')",
  "button[aria-label*='plus' i]", "button[aria-label*='add' i]", "button[aria-label*='ajouter' i]",
  '.qty-plus', '.qty-btn.qty-plus', "[class*='plus']", "[class*='increase']",
];
function normalizeLabel(text) {
  return String(text || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}
function productMatches(candidateText, productName) {
  const candidate = normalizeLabel(candidateText);
  const product = normalizeLabel(productName);
  if (!candidate || !product) return false;
  if (candidate.includes(product) || product.includes(candidate)) return true;
  const rawTokens = value => [...new Set(value.split(' ').filter(token => token.length > 1))];
  const tokens = value => rawTokens(value)
    .filter(token => !IGNORED_PRODUCT_WORDS.has(token))
    .map(token => PRODUCT_TOKEN_ALIASES.get(token) || token);
  const wanted = tokens(product);
  const found = new Set(tokens(candidate));
  if (wanted.length && wanted.filter(token => found.has(token)).length >= Math.ceil(wanted.length * 0.6)) return true;

  // Some requested labels (for example "Entrance by invitation") consist
  // entirely of generic words. In that case retain the generic overlap instead
  // of leaving the request with no usable tokens.
  const candidateRaw = new Set(rawTokens(candidate));
  const genericWanted = rawTokens(product).filter(token => IGNORED_PRODUCT_WORDS.has(token));
  return genericWanted.some(token => candidateRaw.has(token));
}
async function hasVisiblePlus(locator) {
  for (const selector of PLUS_SELECTORS) {
    try {
      const matches = locator.locator(selector);
      for (let i = 0; i < Math.min(await matches.count(), 4); i++) if (await matches.nth(i).isVisible()) return true;
    } catch {}
  }
  return false;
}
async function findProductContainer(page, productName) {
  const locator = page.locator("div, article, section, li, [class*='ticket' i], [class*='product' i], [class*='tarif' i], [class*='price' i]");
  const candidates = [];
  const detectedCandidates = [];
  const count = await locator.count();
  for (let index = 0; index < Math.min(count, 1000); index++) {
    const item = locator.nth(index);
    try {
      if (!(await item.isVisible())) continue;
      const text = (await item.innerText()).replace(/\s+/g, ' ').trim();
      if (!text) continue;
      const normalized = normalizeLabel(text);
      const exactContains = normalized.includes(normalizeLabel(productName));
      const hasPlusButton = await hasVisiblePlus(item);
      const hasPriceSignal = /€|\bfree\b|\bgratuit(?:e)?\b|\binvitation\b|\bentry\b|\bticket\b|\bbillet\b/i.test(text);
      if (!hasPriceSignal && !hasPlusButton) continue;
      const prices = text.match(/(?:\d+[,.]?\d*\s*€|€\s*\d+[,.]?\d*|\bfree\b|\bgratuit(?:e)?\b)/gi) || [];
      let score = (exactContains ? 5 : 0) + (hasPlusButton ? 3 : 0) + (hasPriceSignal ? 2 : 0);
      if (text.length > 900) score -= 5;
      if (prices.length > 1) score -= 3;
      const candidate = { index, text: text.slice(0, 900), score, hasPlusButton, hasPriceSignal, textLength: text.length };
      detectedCandidates.push(candidate);
      if (productMatches(text, productName)) candidates.push(candidate);
    } catch {}
  }
  candidates.sort((a, b) => b.score - a.score || a.textLength - b.textLength);
  detectedCandidates.sort((a, b) => b.score - a.score || a.textLength - b.textLength);
  logLine(`Found ${detectedCandidates.length} candidate product containers; ${candidates.length} matched (scanned ${count})`);
  if (!candidates.length) {
    detectedCandidates.slice(0, 5).forEach((candidate, position) => {
      logLine(`Product candidate ${position + 1}: score=${candidate.score} plus=${candidate.hasPlusButton} price=${candidate.hasPriceSignal} text=${candidate.text.slice(0, 300)}`);
    });
    const error = new Error(`Product not found: ${productName}`);
    error.failureDetails = { detected_product_candidates: detectedCandidates.slice(0, 20) };
    throw error;
  }
  const selected = candidates[0];
  logLine(`Selected product candidate score=${selected.score}: ${selected.text.slice(0, 300)}`);
  return { container: locator.nth(selected.index), selected, candidates: candidates.slice(0, 20) };
}
async function quantitySnapshot(container) {
  return container.evaluate(element => {
    const values = [];
    element.querySelectorAll('input, select, [class*="qty" i], [class*="quantity" i], [class*="counter" i], [aria-live]').forEach(node => {
      const value = 'value' in node ? node.value : node.textContent;
      const match = String(value || '').trim().match(/^-?\d+(?:[,.]\d+)?$/);
      if (match) values.push(`${node.tagName}:${match[0]}`);
    });
    return values;
  }).catch(() => []);
}
async function addTicketQuantity(page, match, productName, qty) {
  const plusSelectors = selectorsFor('quantity_plus', PLUS_SELECTORS);
  let searchRoot = match.container;
  let plus = null;
  let clickedSelector = null;
  for (let ancestor = 0; ancestor < 5 && !plus; ancestor++) {
    for (const selector of plusSelectors) {
      try {
        const options = searchRoot.locator(selector);
        for (let i = 0; i < Math.min(await options.count(), 5); i++) {
          if (await options.nth(i).isVisible()) { plus = options.nth(i); clickedSelector = selector; break; }
        }
      } catch {}
      if (plus) break;
    }
    if (!plus) searchRoot = searchRoot.locator('xpath=..');
  }
  // A page-wide fallback is safe only when the product itself was an exact, high-confidence match.
  if (!plus && match.selected.score >= 7 && normalizeLabel(match.selected.text).includes(normalizeLabel(productName))) {
    for (const selector of plusSelectors) {
      const options = page.locator(selector);
      if (await options.count() === 1 && await options.first().isVisible()) { plus = options.first(); clickedSelector = selector; break; }
    }
  }
  if (!plus) {
    const error = new Error(`Plus button not found for product: ${productName}`);
    error.failureDetails = { tried_selectors: plusSelectors, matched_container_text: match.selected.text, detected_product_candidates: match.candidates };
    throw error;
  }
  logLine(`Clicking quantity selector: ${clickedSelector}`);
  for (let i = 0; i < qty; i++) {
    const before = await quantitySnapshot(match.container);
    try {
      await plus.scrollIntoViewIfNeeded({ timeout: 5000 });
      await plus.click({ timeout: 5000 });
    } catch (clickError) {
      // Bizouk's horizontally animated ticket list can leave a visible button
      // outside Playwright's computed viewport even after it has been scrolled.
      // A DOM click still dispatches the site's normal click handler and is
      // constrained to the plus control selected inside the matched product.
      logLine(`Regular quantity click failed (${clickError.message}); retrying with DOM click`);
      try {
        await plus.evaluate(element => element.click());
      } catch (domClickError) {
        const error = new Error(`Plus button click failed for product: ${productName}: ${domClickError.message}`);
        error.failureDetails = { tried_selectors: plusSelectors, matched_container_text: match.selected.text, detected_product_candidates: match.candidates };
        throw error;
      }
    }
    await page.waitForTimeout(400);
    const after = await quantitySnapshot(match.container);
    if (!before.length || JSON.stringify(before) === JSON.stringify(after)) logLine('quantity click sent but counter not verified');
  }
  return plusSelectors;
}
async function selectGender(page) {
  const candidates = ["select[name*='gender']", "select[name*='civil']", "select[name*='sexe']", "select[name*='title']"];
  for (const selector of candidates) {
    try {
      const loc = page.locator(selector);
      const count = await loc.count();
      for (let i = 0; i < count; i++) {
        const item = loc.nth(i);
        if (await item.isVisible()) {
          for (const label of [DEFAULT_GENDER, 'Homme', 'Male', 'Mr', 'Monsieur']) {
            try { await item.selectOption({ label }); return; } catch {}
          }
        }
      }
    } catch {}
  }
}
async function fillFormByLabels(page, email) {
  const labels = await page.locator('label[for]').all();
  for (const label of labels) {
    const forId = await label.getAttribute('for');
    if (!forId) continue;
    const labelText = (await label.textContent() || '').toLowerCase().trim();
    const input = page.locator(`[name="${forId}"], #${forId}`).first();
    if (!(await input.count())) continue;
    const type = (await input.getAttribute('type') || 'text').toLowerCase();
    if (!['text', 'email', 'tel', 'number'].includes(type)) continue;
    if (!(await input.isVisible())) continue;
    let value = null;
    if ((labelText.includes('first') || labelText.includes('prénom') || labelText.includes('forename') || labelText.includes('given name'))) value = DEFAULT_FIRST_NAME;
    else if ((labelText.includes('last') || labelText.includes('name') || labelText.includes('nom') || labelText.includes('surname')) && !labelText.includes('first') && !labelText.includes('prénom')) value = DEFAULT_LAST_NAME;
    else if (labelText.includes('full') && labelText.includes('name')) value = DEFAULT_FULL_NAME;
    else if (labelText.includes('email') || labelText.includes('e-mail') || labelText.includes('courriel')) value = email;
    else if (labelText.includes('phone') || labelText.includes('portable') || labelText.includes('mobile') || labelText.includes('tel') || labelText.includes('téléphone')) value = DEFAULT_PHONE;
    if (value !== null) { try { await input.fill(value); } catch {} }
  }
  const groups = [
    [DEFAULT_FIRST_NAME, ["input[name*='firstname']","input[name*='first_name']","input[id*='firstname']","input[id*='first_name']"]],
    [DEFAULT_LAST_NAME, ["input[name*='lastname']","input[name*='last_name']","input[id*='lastname']","input[id*='last_name']"]],
    [DEFAULT_FULL_NAME, ["input[name*='fullname']","input[name*='full_name']","input[name*='buyer_name']","input[id*='fullname']","input[id*='buyer_name']"]],
    [email, ["input[type='email']","input[name*='email']","input[id*='email']"]],
    [DEFAULT_PHONE, ["input[name*='phone']","input[name*='mobile']","input[name*='tel']","input[id*='phone']","input[id*='mobile']"]],
  ];
  for (const [val, selectors] of groups) {
    for (const sel of selectors) {
      try { const loc = page.locator(sel); if (await loc.count() && await loc.first().isVisible()) await loc.first().fill(val); } catch {}
    }
  }
  await selectGender(page);
}
async function selectRadioDefaults(page) {
  try {
    const seen = new Set();
    const radios = await page.locator('input[type=radio]:visible').all();
    for (const r of radios) {
      const name = await r.getAttribute('name') || '';
      if (!name || seen.has(name)) continue;
      seen.add(name);
      try { if (!(await r.isChecked())) await r.check(); } catch {}
    }
  } catch {}
}
async function handleCheckboxes(page) {
  await page.evaluate(() => {
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (cb.checked) return;
      const container = cb.closest('.card, .panel, [class*="condition"], [class*="terms"], [class*="cgv"]') || cb.parentElement;
      const text = (container ? container.textContent : '').toLowerCase();
      if (text.includes('conditions') || text.includes('cgv') || text.includes('j\'accepte') || text.includes('obligatoire') || text.includes('accept') || text.includes('terms') || text.includes('i accept')) {
        cb.checked = true;
        cb.dispatchEvent(new Event('change', { bubbles: true }));
        cb.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
  }).catch(() => {});
}
async function detectSuccess(page) {
  const url = page.url();
  if (url.includes('order-confirmation') || url.includes('booking-confirmation') || url.includes('/confirmation') || url.includes('order-success') || url.includes('booking-success') || url.includes('thank-you') || url.includes('thankyou')) {
    const title = await page.title().catch(() => '');
    return `Confirmed (URL: ${url.split('?')[0]} | Title: ${title})`;
  }
  const selectors = selectorsFor('success', [
    "h1:has-text('Confirmé')", "h1:has-text('Confirmed')", "h2:has-text('Confirmé')", "h2:has-text('Confirmed')",
    "text=Votre réservation est confirmée", "text=Your booking is confirmed", "text=Votre commande est confirmée", "text=Your order is confirmed",
    "text=Merci pour votre réservation", "text=Thank you for your booking", "text=Référence de commande", "text=Order number"
  ]);
  for (const sel of selectors) {
    try {
      const loc = page.locator(sel).first();
      if (await loc.isVisible({ timeout: 700 })) {
        return (await loc.textContent() || sel).trim().slice(0, 300);
      }
    } catch {}
  }
  return null;
}
async function waitForSuccessAfterSubmit(page, prefix) {
  for (let attempt = 1; attempt <= SUCCESS_POLL_ATTEMPTS; attempt++) {
    try { await page.waitForLoadState('networkidle', { timeout: SUCCESS_POLL_DELAY_MS }); } catch {}
    const success = await detectSuccess(page);
    if (success) {
      await screenshot(page, `${prefix}-confirmed-late`);
      logLine(`Late confirmation detected on attempt ${attempt}: ${success}`);
      return success;
    }
    const url = page.url();
    const title = await page.title().catch(() => '');
    logLine(`Confirmation poll ${attempt}/${SUCCESS_POLL_ATTEMPTS}: no success yet | URL=${url} | Title=${title}`);
    if (attempt < SUCCESS_POLL_ATTEMPTS) await page.waitForTimeout(SUCCESS_POLL_DELAY_MS);
  }
  return null;
}
async function runPrepare(eventUrl, ticketCount, email, productName) {
  const startedAt = new Date().toISOString();
  let lastStepName = 'start';
  let lastIntent = 'start';
  let lastSelectors = [];
  writeState({ running: true, status: 'running', mode: 'human_approved', event_url: eventUrl, product_name: productName, ticket_count: ticketCount, email, started_at: startedAt, finished_at: null, last_error: null, confirmation_text: null });
  logLine(`Starting human-approved flow: ${eventUrl} / ${productName} / qty=${ticketCount} / email=${email}`);
  const { browser, page } = await newBrowserPage(chromium, { headless: DEFAULT_HEADLESS, slowMo: DEFAULT_SLOWMO });
  const prefix = slugify(productName);
  try {
    lastStepName = 'load_event'; lastIntent = 'load_event';
    await page.goto(eventUrl, { timeout: 60000 });
    // Bizouk keeps analytics and other background requests alive, so reaching
    // networkidle is an optimization rather than a requirement for product lookup.
    try {
      await page.waitForLoadState('networkidle', { timeout: 10000 });
    } catch {
      logLine(`Network idle timeout after page load; continuing with DOM at URL=${page.url()}`);
    }
    await acceptCookies(page);
    logLine(`Loaded URL=${page.url()} | Title=${await page.title().catch(() => '')} | Requested product=${productName}`);
    lastStepName = 'find_product'; lastIntent = 'product_match'; lastSelectors = [];
    const productMatch = await findProductContainer(page, productName);
    lastStepName = 'add_ticket_quantity'; lastIntent = 'quantity_plus'; lastSelectors = selectorsFor('quantity_plus', PLUS_SELECTORS);
    const plusSelectors = await addTicketQuantity(page, productMatch, productName, ticketCount);
    await screenshot(page, `${prefix}-02-qty`);
    const checkoutSelectors = selectorsFor('checkout', ["button:has-text('Continue booking')", "button:has-text('Continuer la réservation')", "button:has-text('Book now')", "button:has-text('Proceed to checkout')", "button:has-text('Commander')", "button:has-text('Continuer')", "button:has-text('Continuer ma commande')", "button:has-text('Réserver')", "button:has-text('Je réserve')", "button:has-text('Commander gratuitement')", "button:has-text('Valider')", "a:has-text('Continuer')", "a[href*='checkout']", "a[href*='cart']", "a[href*='commande']"]);
    lastStepName = 'proceed_checkout'; lastIntent = 'checkout'; lastSelectors = checkoutSelectors;
    const proceeded = await clickFirstVisible(page, checkoutSelectors, 10000);
    if (!proceeded) throw new Error('Could not find checkout button');
    await page.waitForTimeout(2000);
    try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}
    logLine(`URL after checkout click: ${page.url()}`);
    for (let step = 1; step <= 8; step++) {
      await fillFormByLabels(page, email);
      await selectRadioDefaults(page);
      await handleCheckboxes(page);
      const successBefore = await detectSuccess(page);
      if (successBefore) {
        writeState({ running: false, status: 'confirmed', finished_at: new Date().toISOString(), last_error: null, confirmation_text: successBefore });
        return;
      }
      const advanceSelectors = selectorsFor('advance', ["button:has-text('Continue booking')", "button:has-text('Continuer vers le paiement')", "button:has-text('Continue')", "button:has-text('Continuer')", "button:has-text('Suivant')", "button:has-text('Next')", "button:has-text('Confirmer')", "button:has-text('Confirm')", "button:has-text('Valider')", "button:has-text('Validate')", "button:has-text('Commander')", "button:has-text('Finaliser')", "button:has-text('Place order')", "button:has-text('Pay')", "button:has-text('Payer')", "button:has-text('Submit')", "button[type='submit']"]);
      lastStepName = `advance_step_${step}`; lastIntent = 'advance'; lastSelectors = advanceSelectors;
      const advanced = await clickFirstVisible(page, advanceSelectors, 6000);
      if (!advanced) break;
      await page.waitForTimeout(2500);
      try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}
      const successAfter = await detectSuccess(page);
      if (successAfter) {
        writeState({ running: false, status: 'confirmed', finished_at: new Date().toISOString(), last_error: null, confirmation_text: successAfter });
        return;
      }
    }
    lastStepName = 'confirmation_detection'; lastIntent = 'success'; lastSelectors = selectorsFor('success', []);
    const delayedSuccess = await waitForSuccessAfterSubmit(page, prefix);
    if (delayedSuccess) {
      writeState({ running: false, status: 'confirmed', finished_at: new Date().toISOString(), last_error: null, confirmation_text: delayedSuccess });
      return;
    }
    const finalUrl = page.url();
    const finalTitle = await page.title().catch(() => '');
    const msg = `Reached end of flow without confirmation page. URL: ${finalUrl} | Title: ${finalTitle}`;
    await saveFailureReport(page, { booking_started_at: startedAt, event_url: eventUrl, product_name: productName, step_name: lastStepName, intent: lastIntent, error_text: msg, tried_selectors: lastSelectors });
    writeState({ running: false, status: 'submitted_unconfirmed', finished_at: new Date().toISOString(), last_error: msg, confirmation_text: null });
  } catch (err) {
    const details = err.failureDetails || {};
    await saveFailureReport(page, { booking_started_at: startedAt, event_url: eventUrl, product_name: productName, step_name: lastStepName, intent: lastIntent, error_text: err.message || String(err), tried_selectors: lastSelectors, ...details });
    writeState({ running: false, status: 'failed', finished_at: new Date().toISOString(), last_error: String(err), confirmation_text: null });
    logLine(`Flow failed: ${err}`);
    throw err;
  } finally {
    await browser.close();
  }
}
function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i]; const value = argv[i + 1];
    if (!key || typeof value === 'undefined') continue;
    out[key.replace(/^--/, '')] = value;
  }
  return out;
}
(async () => {
  try {
    const args = parseArgs(process.argv);
    if (!args['event-url'] || !args['ticket-count'] || !args['email'] || !args['product-name']) {
      console.error('Usage: node booking_prepare.js --event-url <url> --ticket-count <n> --email <email> --product-name <name>');
      process.exit(1);
    }
    await runPrepare(args['event-url'], parseInt(args['ticket-count'], 10), args['email'], args['product-name']);
  } catch {
    process.exit(1);
  }
})();
