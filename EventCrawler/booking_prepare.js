const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const DATA_DIR = path.join(process.cwd(), 'data');
const STATE_PATH = path.join(DATA_DIR, 'booking_state.json');
const LOG_PATH = path.join(DATA_DIR, 'booking.log');

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key || typeof value === 'undefined') continue;
    out[key.replace(/^--/, '')] = value;
  }
  return out;
}

function logLine(message) {
  ensureDir(DATA_DIR);
  fs.appendFileSync(LOG_PATH, `[${new Date().toISOString()}] ${message}\n`, 'utf8');
}

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
    try {
      state = { ...state, ...JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')) };
    } catch {}
  }
  fs.writeFileSync(STATE_PATH, JSON.stringify({ ...state, ...fields }, null, 2), 'utf8');
}

function detectSource(eventUrl) {
  try {
    const host = new URL(eventUrl).hostname.toLowerCase();
    if (host.includes('kiwol.com')) return 'kiwol';
  } catch {}
  return 'bizouk';
}

function sourceScriptPath(source) {
  if (source === 'kiwol') return path.join(process.cwd(), 'booking_prepare_kiwol.js');
  return path.join(process.cwd(), 'booking_prepare_bizouk.js');
}

async function main() {
  const args = parseArgs(process.argv);
  const eventUrl = args['event-url'];
  const ticketCount = args['ticket-count'];
  const email = args.email;
  const productName = args['product-name'];

  if (!eventUrl || !ticketCount || !email || !productName) {
    console.error('Usage: node booking_prepare.js --event-url <url> --ticket-count <n> --email <email> --product-name <name>');
    process.exit(1);
  }

  const source = detectSource(eventUrl);
  const script = sourceScriptPath(source);
  logLine(`Routing booking prepare to source=${source} script=${script}`);

  if (source === 'kiwol') {
    writeState({
      running: true,
      status: 'routing',
      mode: 'auto_confirm',
      event_url: eventUrl,
      product_name: productName,
      ticket_count: Number(ticketCount) || 0,
      email,
      started_at: new Date().toISOString(),
      finished_at: null,
      last_error: null,
      confirmation_text: null,
    });
  }

  if (!fs.existsSync(script)) {
    const msg = `Booking script not found for source=${source}: ${script}`;
    logLine(msg);
    writeState({ running: false, status: 'failed', finished_at: new Date().toISOString(), last_error: msg });
    process.exit(1);
  }

  const child = spawn('node', [script, ...process.argv.slice(2)], {
    stdio: 'inherit',
    env: { ...process.env, BOOKING_SOURCE: source },
  });

  child.on('exit', (code) => {
    if (source === 'kiwol' && code === 0) {
      writeState({
        running: false,
        status: 'not_implemented',
        finished_at: new Date().toISOString(),
        last_error: 'Kiwol Playwright reservation script is intentionally empty for now.',
        confirmation_text: null,
      });
      logLine('Kiwol routing completed: placeholder script exists but reservation flow is not implemented yet.');
    }
    process.exit(code || 0);
  });

  child.on('error', (err) => {
    const msg = `Failed to launch booking script for source=${source}: ${err}`;
    logLine(msg);
    writeState({ running: false, status: 'failed', finished_at: new Date().toISOString(), last_error: msg });
    process.exit(1);
  });
}

main().catch((err) => {
  logLine(`booking_prepare router failed: ${err}`);
  writeState({ running: false, status: 'failed', finished_at: new Date().toISOString(), last_error: String(err) });
  process.exit(1);
});
