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
const DEFAULT_GENDER = 'Homme';
const DEFAULT_HEADLESS = process.env.PLAYWRIGHT_HEADLESS === '1' || String(process.env.PLAYWRIGHT_HEADLESS || '').toLowerCase() === 'true';
const DEFAULT_SLOWMO = Number(process.env.PLAYWRIGHT_SLOWMO || '250');
const DEFAULT_KEEP_OPEN_MS = Number(process.env.PLAYWRIGHT_KEEP_OPEN_MS || '120000');

function ensureDir(dir) { fs.mkdirSync(dir, { recursive: true }); }
function defaultState() {
  return {
    running: false,
    status: 'idle',
    mode: 'prepare_only',
    event_url: null,
    product_name: null,
    ticket_count: 0,
    email: null,
    started_at: null,
    finished_at: null,
    last_error: null,
    log_path: LOG_PATH,
    final_step_ready: false,
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
  ensureDir(SCREEN_DIR);
  await page.screenshot({ path: path.join(SCREEN_DIR, `${name}.png`), fullPage: true });
}
async function clickFirstVisible(page, selectors, timeout = 2500) {
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
async function fillAllMatching(page, selectors, value) {
  for (const selector of selectors) {
    try {
      const locator = page.locator(selector);
      const count = await locator.count();
      for (let i = 0; i < count; i++) {
        const item = locator.nth(i);
        if (await item.isVisible()) {
          try { await item.fill(value); } catch {}
        }
      }
    } catch {}
  }
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
          for (const label of ['Homme', 'Male', 'Mr', 'Monsieur']) {
            try { await item.selectOption({ label }); return; } catch {}
          }
        }
      }
    } catch {}
  }
}
async function fillCommonForms(page, email) {
  await fillAllMatching(page, ["input[name*='firstname']","input[name*='first_name']","input[id*='firstname']","input[id*='first_name']"], DEFAULT_FIRST_NAME);
  await fillAllMatching(page, ["input[name*='lastname']","input[name*='last_name']","input[id*='lastname']","input[id*='last_name']"], DEFAULT_LAST_NAME);
  await fillAllMatching(page, ["input[name*='fullname']","input[name*='full_name']","input[name*='buyer_name']","input[id*='fullname']","input[id*='buyer_name']"], DEFAULT_FULL_NAME);
  await fillAllMatching(page, ["input[name*='phone']","input[name*='mobile']","input[name*='tel']","input[id*='phone']","input[id*='mobile']","input[id*='tel']"], DEFAULT_PHONE);
  await fillAllMatching(page, ["input[type='email']","input[name*='email']","input[id*='email']"], email);
  await selectGender(page);
}
async function acceptTerms(page) {
  const selectors = ["input[type='checkbox']","label:has-text('I agree')","label:has-text('J’accepte')","label:has-text(\"J'accepte\")","label:has-text('conditions')","label:has-text('terms')"];
  for (const selector of selectors) {
    try {
      const loc = page.locator(selector);
      const count = await loc.count();
      for (let i = 0; i < count; i++) {
        const item = loc.nth(i);
        if (await item.isVisible()) {
          try {
            const tag = await item.evaluate(el => el.tagName.toLowerCase());
            if (tag === 'input') {
              const checked = await item.isChecked();
              if (!checked) await item.check();
            } else {
              await item.click();
            }
          } catch {}
        }
      }
    } catch {}
  }
}
async function findProductContainer(page, productName) {
  const target = page.getByText(productName, { exact: false }).first();
  await target.waitFor({ timeout: 15000 });
  for (const xp of ['xpath=ancestor::div[1]','xpath=ancestor::div[2]','xpath=ancestor::section[1]','xpath=ancestor::article[1]']) {
    try {
      const container = target.locator(xp);
      if (await container.count() > 0) return container.first();
    } catch {}
  }
  return target;
}
async function addTicketQuantity(page, productName, qty) {
  const container = await findProductContainer(page, productName);
  const plusSelectors = ["button:has-text('+')","a:has-text('+')","[role='button']:has-text('+')","button:has-text('Ajouter')","button:has-text('Add')"];
  let plus = null;
  for (const selector of plusSelectors) {
    const loc = container.locator(selector);
    if (await loc.count() > 0) { plus = loc.first(); break; }
  }
  if (!plus) {
    for (const selector of plusSelectors) {
      const loc = page.locator(selector);
      if (await loc.count() > 0) { plus = loc.first(); break; }
    }
  }
  if (!plus) throw new Error(`Impossible de trouver le bouton + pour '${productName}'`);
  for (let i = 0; i < qty; i++) { await plus.click(); await page.waitForTimeout(350); }
}
async function advanceOneStep(page) {
  return await clickFirstVisible(page, [
    "button:has-text('Continue booking')",
    "button:has-text('Continuer')",
    "button:has-text('Continue')",
    "button:has-text('Suivant')",
    "button:has-text('Réserver')",
    "button:has-text('Book now')",
    "button:has-text('Valider')",
    "button:has-text('Validate')",
  ]);
}
async function finalSubmitVisible(page) {
  const selectors = [
    "button:has-text('Confirmer')",
    "button:has-text('Confirm')",
    "button:has-text('Finaliser')",
    "button:has-text('Finish')",
    "button:has-text('Continuer vers le paiement')",
    "button:has-text('Continue to payment')",
  ];
  for (const selector of selectors) {
    try {
      const loc = page.locator(selector);
      const count = await loc.count();
      for (let i = 0; i < count; i++) {
        if (await loc.nth(i).isVisible()) return true;
      }
    } catch {}
  }
  return false;
}
async function runPrepare(eventUrl, ticketCount, email, productName) {
  writeState({
    running: true,
    status: 'running',
    mode: 'prepare_only',
    event_url: eventUrl,
    product_name: productName,
    ticket_count: ticketCount,
    email,
    started_at: new Date().toISOString(),
    finished_at: null,
    last_error: null,
    final_step_ready: false,
  });
  logLine(`Starting prepare-only flow for ${eventUrl} / ${productName} / qty=${ticketCount} / email=${email}`);
  const browser = await chromium.launch({ headless: DEFAULT_HEADLESS, slowMo: DEFAULT_SLOWMO });
  const page = await browser.newPage();
  const prefix = slugify(productName);
  try {
    await page.goto(eventUrl, { timeout: 60000 });
    await page.waitForLoadState('networkidle');
    await screenshot(page, `${prefix}-01-event`);
    await addTicketQuantity(page, productName, ticketCount);
    await screenshot(page, `${prefix}-02-qty`);
    await clickFirstVisible(page, ['text=Your cart','text=Panier','div.cart-icon','[class*="cart"]']);
    await page.waitForTimeout(800);
    for (let i = 0; i < 4; i++) {
      await fillCommonForms(page, email);
      await acceptTerms(page);
      if (await finalSubmitVisible(page)) break;
      const moved = await advanceOneStep(page);
      if (!moved) break;
      try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
      await page.waitForTimeout(1000);
    }
    await fillCommonForms(page, email);
    await acceptTerms(page);
    await screenshot(page, `${prefix}-03-ready-for-manual-confirm`);
    writeState({
      running: false,
      status: 'ready_for_manual_confirm',
      finished_at: new Date().toISOString(),
      final_step_ready: true,
      last_error: null,
    });
    logLine('Flow prepared up to final manual confirmation step');
    await page.waitForTimeout(DEFAULT_KEEP_OPEN_MS);
  } catch (err) {
    writeState({
      running: false,
      status: 'failed',
      finished_at: new Date().toISOString(),
      last_error: String(err),
      final_step_ready: false,
    });
    logLine(`Prepare flow failed: ${err}`);
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
