const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const DATA_DIR = path.join(process.cwd(), 'data');
const STATE_PATH = path.join(DATA_DIR, 'booking_state.json');
const LOG_PATH = path.join(DATA_DIR, 'booking.log');
const SCREEN_DIR = path.join(DATA_DIR, 'booking_screens');

const DEFAULT_FIRST_NAME = 'Olivier';
const DEFAULT_LAST_NAME = 'Mops';
const DEFAULT_FULL_NAME = 'Olivier Mops';
const DEFAULT_PHONE = '0691243236';
const DEFAULT_HEADLESS = !(process.env.PLAYWRIGHT_HEADLESS === '0' || String(process.env.PLAYWRIGHT_HEADLESS || '').toLowerCase() === 'false');
const DEFAULT_SLOWMO = Number(process.env.PLAYWRIGHT_SLOWMO || '200');
const SCREENSHOTS_ENABLED = process.env.PLAYWRIGHT_SCREENSHOTS === '1';

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
async function addTicketQuantity(page, productName, qty) {
  const target = page.getByText(productName, { exact: false }).first();
  await target.waitFor({ timeout: 15000 });
  const container = target.locator('xpath=ancestor::div[3]').first();

  // Try Bizouk-specific class first, then generic selectors
  const plusSelectors = [
    '.qty-btn.qty-plus',
    '.qty-plus',
    "button:has-text('+')",
    "a:has-text('+')",
    "[role='button']:has-text('+')",
    "button:has-text('Ajouter')",
    "button:has-text('Add')",
  ];
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
}

// Fill all visible text/email/tel inputs by matching their label text
async function fillFormByLabels(page, email) {
  const labels = await page.locator('label[for]').all();
  for (const label of labels) {
    const forId = await label.getAttribute('for');
    if (!forId) continue;
    const labelText = (await label.textContent() || '').toLowerCase().trim();
    const input = page.locator(`[name="${forId}"]`).first();
    if (!(await input.count())) continue;
    const type = (await input.getAttribute('type') || 'text').toLowerCase();
    if (!['text', 'email', 'tel', 'number'].includes(type)) continue;
    if (!(await input.isVisible())) continue;

    let value = null;
    if ((labelText.includes('first') || labelText.includes('prénom') || labelText.includes('forename') || labelText.includes('given name'))) {
      value = DEFAULT_FIRST_NAME;
    } else if ((labelText.includes('last') || labelText.includes('name') || labelText.includes('nom') || labelText.includes('surname')) && !labelText.includes('first') && !labelText.includes('prénom')) {
      value = DEFAULT_LAST_NAME;
    } else if (labelText.includes('full') && labelText.includes('name')) {
      value = DEFAULT_FULL_NAME;
    } else if (labelText.includes('email') || labelText.includes('e-mail') || labelText.includes('courriel')) {
      value = email;
    } else if (labelText.includes('phone') || labelText.includes('portable') || labelText.includes('mobile') || labelText.includes('tel') || labelText.includes('téléphone')) {
      value = DEFAULT_PHONE;
    }
    if (value !== null) {
      try { await input.fill(value); } catch {}
    }
  }

  // Also fill generic inputs not linked via label (fallback)
  const nameSelectors = ["input[name*='firstname']","input[name*='first_name']","input[id*='firstname']","input[id*='first_name']"];
  for (const sel of nameSelectors) {
    try { const loc = page.locator(sel); if (await loc.count() && await loc.first().isVisible()) await loc.first().fill(DEFAULT_FIRST_NAME); } catch {}
  }
  const lastSelectors = ["input[name*='lastname']","input[name*='last_name']","input[id*='lastname']","input[id*='last_name']"];
  for (const sel of lastSelectors) {
    try { const loc = page.locator(sel); if (await loc.count() && await loc.first().isVisible()) await loc.first().fill(DEFAULT_LAST_NAME); } catch {}
  }
  const emailSelectors = ["input[type='email']","input[name*='email']","input[id*='email']"];
  for (const sel of emailSelectors) {
    try { const loc = page.locator(sel); if (await loc.count() && await loc.first().isVisible()) await loc.first().fill(email); } catch {}
  }
  const phoneSelectors = ["input[name*='phone']","input[name*='mobile']","input[name*='tel']","input[id*='phone']","input[id*='mobile']"];
  for (const sel of phoneSelectors) {
    try { const loc = page.locator(sel); if (await loc.count() && await loc.first().isVisible()) await loc.first().fill(DEFAULT_PHONE); } catch {}
  }
}

// Select first option for each visible radio group
async function selectRadioDefaults(page) {
  try {
    const seen = new Set();
    const radios = await page.locator('input[type=radio]:visible').all();
    for (const r of radios) {
      const name = await r.getAttribute('name') || '';
      if (!name || seen.has(name)) continue;
      seen.add(name);
      try {
        const isChecked = await r.isChecked();
        if (!isChecked) await r.check();
      } catch {}
    }
  } catch {}
}

// Handle all checkboxes:
// - Multi-select groups (name ends with []): check the FIRST option in each group
// - Single checkboxes: check if they look like terms/required (including CGV toggles)
// - Uses JS evaluate for hidden/CSS-toggle checkboxes (like Bizouk's CGV toggle)
async function handleCheckboxes(page) {
  // Part 1: JS-based force-check for hidden toggle checkboxes (e.g. Bizouk CGV toggle)
  await page.evaluate(() => {
    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (cb.checked) return;
      const container = cb.closest('.card, .panel, [class*="condition"], [class*="terms"], [class*="cgv"]') || cb.parentElement;
      const text = (container ? container.textContent : '').toLowerCase();
      if (text.includes('conditions') || text.includes('cgv') || text.includes('j\'accepte') ||
          text.includes('obligatoire') || text.includes('accept') || text.includes('terms') ||
          text.includes('i accept')) {
        cb.checked = true;
        cb.dispatchEvent(new Event('change', { bubbles: true }));
        cb.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
  }).catch(() => {});

  // Part 2: Playwright-based check for visible checkboxes
  try {
    const seenGroups = new Set();
    const checkboxes = await page.locator('input[type=checkbox]:visible').all();
    for (const cb of checkboxes) {
      const name = await cb.getAttribute('name') || '';
      const id = await cb.getAttribute('id') || '';
      if (name.endsWith('[]')) {
        // Multi-select checkbox group — check the first option in each group
        if (!seenGroups.has(name)) {
          seenGroups.add(name);
          try { if (!(await cb.isChecked())) await cb.check(); } catch {}
        }
      } else {
        // Single checkbox — check via label[for] or ancestor text
        let labelText = '';
        try {
          const lbl = page.locator(`label[for="${id}"]`);
          if (await lbl.count()) labelText += ' ' + (await lbl.textContent() || '').toLowerCase();
        } catch {}
        try {
          const parentText = await cb.evaluate(el => {
            const ancestor = el.closest('[class*="condition"],[class*="terms"],[class*="cgv"],.card,.form-group,.form-check,.row');
            return ancestor ? ancestor.textContent.toLowerCase() : '';
          });
          labelText += ' ' + parentText;
        } catch {}
        const isTerms = labelText.includes('ok') || labelText.includes('passport') ||
          labelText.includes('accept') || labelText.includes('agree') ||
          labelText.includes('autoris') || labelText.includes('required') ||
          labelText.includes('obligatoire') || labelText.includes('conditions') ||
          labelText.includes('terms') || labelText.includes('cgv') ||
          labelText.includes('j\'accepte') || labelText.includes('i accept');
        if (isTerms) {
          try { if (!(await cb.isChecked())) await cb.check(); } catch {}
        }
      }
    }
  } catch {}
}

async function detectSuccess(page) {
  const url = page.url();
  if (url.includes('order-confirmation') || url.includes('booking-confirmation') ||
      url.includes('/confirmation') || url.includes('order-success') ||
      url.includes('booking-success') || url.includes('thank-you') || url.includes('thankyou')) {
    const title = await page.title().catch(() => '');
    return `Confirmed (URL: ${url.split('?')[0]} | Title: ${title})`;
  }
  const selectors = [
    "h1:has-text('Confirmé')", "h1:has-text('Confirmed')", "h2:has-text('Confirmé')", "h2:has-text('Confirmed')",
    "h1:has-text('Thank you')", "h2:has-text('Thank you')",
    ".order-confirmation", ".booking-confirmation", ".thank-you",
    "[class*='order-confirmed']", "[class*='booking-success']",
    "text=Votre réservation est confirmée",
    "text=Your booking is confirmed",
    "text=Votre commande est confirmée",
    "text=Your order is confirmed",
    "text=Merci pour votre réservation",
    "text=Thank you for your booking",
    "text=Réservation confirmée",
    "text=Booking confirmed",
    "text=Commande confirmée",
    "text=Order confirmed",
  ];
  for (const sel of selectors) {
    try {
      const loc = page.locator(sel).first();
      if (await loc.isVisible({ timeout: 500 })) {
        return (await loc.textContent() || sel).trim().slice(0, 300);
      }
    } catch {}
  }
  return null;
}

async function runPrepare(eventUrl, ticketCount, email, productName) {
  writeState({
    running: true,
    status: 'running',
    mode: 'auto_confirm',
    event_url: eventUrl,
    product_name: productName,
    ticket_count: ticketCount,
    email,
    started_at: new Date().toISOString(),
    finished_at: null,
    last_error: null,
    confirmation_text: null,
  });
  logLine(`Starting auto-confirm flow: ${eventUrl} / ${productName} / qty=${ticketCount} / email=${email}`);
  const browser = await chromium.launch({ headless: DEFAULT_HEADLESS, slowMo: DEFAULT_SLOWMO });
  const page = await browser.newPage();
  const prefix = slugify(productName);
  try {
    // ── Step 1: Load event page ──
    logLine('Step 1: Loading event page...');
    await page.goto(eventUrl, { timeout: 60000 });
    await page.waitForLoadState('networkidle');
    await acceptCookies(page);
    await screenshot(page, `${prefix}-01-event`);

    // ── Step 2: Add tickets ──
    logLine(`Step 2: Adding ${ticketCount} ticket(s) for "${productName}"...`);
    await addTicketQuantity(page, productName, ticketCount);
    await screenshot(page, `${prefix}-02-qty`);

    // ── Step 3: Click Continue booking → navigate to checkout ──
    logLine('Step 3: Proceeding to checkout...');
    const proceeded = await clickFirstVisible(page, [
      "button:has-text('Continue booking')",
      "button:has-text('Continuer la réservation')",
      "button:has-text('Book now')",
      "button:has-text('Proceed to checkout')",
      "button:has-text('Commander')",
    ], 10000);
    if (!proceeded) throw new Error('Could not find checkout button');
    await page.waitForTimeout(2000);
    try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}
    logLine(`Step 3: On page ${page.url()}`);
    await screenshot(page, `${prefix}-03-checkout`);

    // ── Step 4+: Fill forms and advance through all steps ──
    for (let step = 1; step <= 8; step++) {
      const currentUrl = page.url();
      logLine(`Step ${3 + step}: Filling forms (page: ${currentUrl.split('?')[0]})...`);

      await fillFormByLabels(page, email);
      await selectRadioDefaults(page);
      await handleCheckboxes(page);
      await screenshot(page, `${prefix}-0${3 + step}-step${step}`);

      // Check for success before clicking anything
      const successBefore = await detectSuccess(page);
      if (successBefore) {
        logLine(`Order confirmed at step ${step}: ${successBefore}`);
        writeState({ running: false, status: 'confirmed', finished_at: new Date().toISOString(), last_error: null, confirmation_text: successBefore });
        return;
      }

      // Click the next/confirm button
      const advanced = await clickFirstVisible(page, [
        "button:has-text('Continue booking')",
        "button:has-text('Continuer vers le paiement')",
        "button:has-text('Continue')",
        "button:has-text('Continuer')",
        "button:has-text('Suivant')",
        "button:has-text('Next')",
        "button:has-text('Confirmer')",
        "button:has-text('Confirm')",
        "button:has-text('Valider')",
        "button:has-text('Validate')",
        "button:has-text('Commander')",
        "button:has-text('Finaliser')",
        "button:has-text('Place order')",
        "button:has-text('Pay')",
        "button:has-text('Payer')",
        "button:has-text('Submit')",
        "button[type='submit']",
      ], 6000);

      if (!advanced) {
        logLine(`Step ${3 + step}: No advance button found, stopping`);
        break;
      }
      logLine(`Step ${3 + step}: Clicked advance/confirm button`);
      await page.waitForTimeout(2500);
      try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}

      // Check for success after navigation
      const successAfter = await detectSuccess(page);
      if (successAfter) {
        await screenshot(page, `${prefix}-confirmed`);
        logLine(`Order confirmed after step ${step}: ${successAfter}`);
        writeState({ running: false, status: 'confirmed', finished_at: new Date().toISOString(), last_error: null, confirmation_text: successAfter });
        return;
      }
    }

    // If we reach here, we ran out of steps without a success page
    const finalUrl = page.url();
    const finalTitle = await page.title().catch(() => '');
    await screenshot(page, `${prefix}-final`);
    const msg = `Reached end of flow without confirmation page. URL: ${finalUrl} | Title: ${finalTitle}`;
    logLine(msg);
    writeState({ running: false, status: 'submitted_unconfirmed', finished_at: new Date().toISOString(), last_error: msg, confirmation_text: null });

  } catch (err) {
    await screenshot(page, `${prefix}-error`).catch(() => {});
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
