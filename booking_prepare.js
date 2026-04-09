const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const DATA_DIR = path.join(process.cwd(), 'data');
const STATE_PATH = path.join(DATA_DIR, 'booking_state.json');
const LOG_PATH = path.join(DATA_DIR, 'booking.log');
const SCREEN_DIR = path.join(DATA_DIR, 'booking_screens');
const FAILURE_DIR = path.join(DATA_DIR, 'booking_failures');

const DEFAULT_FIRST_NAME = (process.env.BOOKING_FIRST_NAME || 'Olivier').trim() || 'Olivier';
const DEFAULT_LAST_NAME = (process.env.BOOKING_LAST_NAME || 'Mops').trim() || 'Mops';
const DEFAULT_FULL_NAME = (process.env.BOOKING_FULL_NAME || `${DEFAULT_FIRST_NAME} ${DEFAULT_LAST_NAME}`).trim() || `${DEFAULT_FIRST_NAME} ${DEFAULT_LAST_NAME}`;
const DEFAULT_PHONE = (process.env.BOOKING_PHONE || '0691243236').trim() || '0691243236';
const DEFAULT_GENDER = (process.env.BOOKING_GENDER || 'Homme').trim() || 'Homme';
const DEFAULT_HEADLESS = !(process.env.PLAYWRIGHT_HEADLESS === '0' || String(process.env.PLAYWRIGHT_HEADLESS || '').toLowerCase() === 'false');
const DEFAULT_SLOWMO = Number(process.env.PLAYWRIGHT_SLOWMO || '200');
const SCREENSHOTS_ENABLED = process.env.PLAYWRIGHT_SCREENSHOTS === '1';
const SUCCESS_POLL_ATTEMPTS = Number(process.env.BOOKING_SUCCESS_POLL_ATTEMPTS || '8');
const SUCCESS_POLL_DELAY_MS = Number(process.env.BOOKING_SUCCESS_POLL_DELAY_MS || '2500');
const SELECTOR_RULES = (() => { try { return JSON.parse(process.env.BOOKING_SELECTOR_RULES_JSON || '{}'); } catch { return {}; } })();

function ensureDir(dir) { fs.mkdirSync(dir, { recursive: true }); }
function defaultState() {
  return {
    running: false,
    status: 'idle',
    mode: 'auto_confirm',
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
function writeState(fields = {}) {
  ensureDir(DATA_DIR);
  let state = defaultState();
  if (fs.existsSync(STATE_PATH)) {
    try { state = { ...state, ...JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) }; } catch {}
  }
  state = { ...state, ...fields };
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2), 'utf8');
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
      created_at: new Date().toISOString(),
    };
    const name = `${Date.now()}-${slugify(report.step_name || report.intent || 'failure')}.json`;
    fs.writeFileSync(path.join(FAILURE_DIR, name), JSON.stringify(payload, null, 2), 'utf8');
  } catch {}
}
async function addTicketQuantity(page, productName, qty) {
  const target = page.getByText(productName, { exact: false }).first();
  await target.waitFor({ timeout: 15000 });
  const container = target.locator('xpath=ancestor::div[3]').first();
  const plusSelectors = selectorsFor('quantity_plus', [
    '.qty-btn.qty-plus', '.qty-plus', "button:has-text('+')", "a:has-text('+')", "[role='button']:has-text('+')", "button:has-text('Ajouter')", "button:has-text('Add')",
  ]);
  let plus = null;
  for (const sel of plusSelectors) {
    try {
      const loc = container.locator(sel);
      if (await loc.count() > 0) { plus = loc.first(); break; }
    } catch {}
  }
  if (!plus) {
    for (const sel of plusSelectors) {
      try {
        const loc = page.locator(sel);
        if (await loc.count() > 0) { plus = loc.first(); break; }
      } catch {}
    }
  }
  if (!plus) throw new Error(`Could not find + button for '${productName}'`);
  for (let i = 0; i < qty; i++) {
    await plus.click();
    await page.waitForTimeout(400);
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
  writeState({ running: true, status: 'running', mode: 'auto_confirm', event_url: eventUrl, product_name: productName, ticket_count: ticketCount, email, started_at: startedAt, finished_at: null, last_error: null, confirmation_text: null });
  logLine(`Starting auto-confirm flow: ${eventUrl} / ${productName} / qty=${ticketCount} / email=${email}`);
  const browser = await chromium.launch({ headless: DEFAULT_HEADLESS, slowMo: DEFAULT_SLOWMO });
  const page = await browser.newPage();
  const prefix = slugify(productName);
  try {
    lastStepName = 'load_event'; lastIntent = 'load_event';
    await page.goto(eventUrl, { timeout: 60000 });
    await page.waitForLoadState('networkidle');
    await acceptCookies(page);
    const plusSelectors = await addTicketQuantity(page, productName, ticketCount);
    lastStepName = 'add_ticket_quantity'; lastIntent = 'quantity_plus'; lastSelectors = plusSelectors;
    await screenshot(page, `${prefix}-02-qty`);
    const checkoutSelectors = selectorsFor('checkout', ["button:has-text('Continue booking')", "button:has-text('Continuer la réservation')", "button:has-text('Book now')", "button:has-text('Proceed to checkout')", "button:has-text('Commander')"]);
    lastStepName = 'proceed_checkout'; lastIntent = 'checkout'; lastSelectors = checkoutSelectors;
    const proceeded = await clickFirstVisible(page, checkoutSelectors, 10000);
    if (!proceeded) throw new Error('Could not find checkout button');
    await page.waitForTimeout(2000);
    try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}
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
    await saveFailureReport(page, { booking_started_at: startedAt, event_url: eventUrl, product_name: productName, step_name: lastStepName, intent: lastIntent, error_text: String(err), tried_selectors: lastSelectors });
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
