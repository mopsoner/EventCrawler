const assert = require('node:assert/strict');
const { test, before, after } = require('node:test');
const { chromium } = require('playwright');
const { collectAgenda, validateKiwolUrl } = require('../render_kiwol_page');
const { buildLaunchOptions } = require('../playwright_helpers');

// Controlled listing pages exercise real Chromium and async loading. They are
// not snapshots of Kiwol's current markup; live validation is separate.
let browser;
before(async () => { browser = await chromium.launch(buildLaunchOptions()); });
after(async () => { await browser?.close(); });

function card(id) {
  return `<a href="https://www.kiwol.com/billetterie/${id}"><span class="ticketing-card-title">Event ${id}</span></a>`;
}

test('loads every async agenda batch and retains replaced cards', async () => {
  const page = await browser.newPage();
  try {
    await page.setContent(`<main>${card(13402)}</main><button>Afficher plus de résultat</button>`);
    await page.evaluate(() => {
      let count = 13402;
      document.querySelector('button').onclick = () => setTimeout(() => {
        count++;
        document.querySelector('main').innerHTML = `<a href="https://www.kiwol.com/billetterie/${count}">Event ${count}</a>`;
        if (count === 13404) document.querySelector('button').remove();
      }, 40);
    });
    const html = await collectAgenda(page, { progressTimeout: 2000 });
    for (const id of [13402, 13403, 13404]) assert.ok(html.includes(`/billetterie/${id}`));
    assert.ok(html.includes('ticketing-card-title'));
  } finally { await page.close(); }
});

test('handles show-all and a disabled exhausted control', async () => {
  const page = await browser.newPage();
  try {
    await page.setContent(`<main>${card(13402)}</main><button>Voir tous les événements</button><button>Réserver</button>`);
    await page.evaluate(() => {
      const more = document.querySelector('button');
      more.onclick = () => {
        document.querySelector('main').insertAdjacentHTML('beforeend', '<a href="https://www.kiwol.com/billetterie/13403">Event 13403</a>');
        more.disabled = true;
      };
      document.querySelectorAll('button')[1].onclick = () => { document.body.dataset.booked = 'yes'; };
    });
    assert.ok((await collectAgenda(page)).includes('/billetterie/13403'));
    assert.equal(await page.locator('body').getAttribute('data-booked'), null);
  } finally { await page.close(); }
});

test('reports stalled loading instead of returning an incomplete agenda', async () => {
  const page = await browser.newPage();
  try {
    await page.setContent(`${card(13402)}<button>Afficher plus</button>`);
    await assert.rejects(collectAgenda(page, { progressTimeout: 100 }), /aucun nouvel événement/);
    await assert.rejects(collectAgenda(page, { maxLoads: 0 }), /incomplet/);
  } finally { await page.close(); }
});

test('accepts a final empty batch only when the control is exhausted', async () => {
  for (const action of ['remove', 'disable']) {
    const page = await browser.newPage();
    try {
      await page.setContent(`${card(13402)}<button>Afficher plus de résultat</button>`);
      await page.evaluate(action => {
        const button = document.querySelector('button');
        button.onclick = () => { if (action === 'remove') button.remove(); else button.disabled = true; };
      }, action);
      assert.ok((await collectAgenda(page, { progressTimeout: 100 })).includes('/billetterie/13402'));
    } finally { await page.close(); }
  }
});

test('reports failed API requests even if the button disappears', async () => {
  const page = await browser.newPage();
  try {
    await page.route('https://api.kiwol.com/**', route => route.fulfill({status:503, body:'Unavailable'}));
    await page.setContent(`${card(13402)}<button>Afficher plus de résultat</button>`);
    await page.evaluate(() => {
      document.querySelector('button').onclick = async () => {
        await fetch('https://api.kiwol.com/api/v1.0/kiwol/agenda/search').catch(() => {});
        document.querySelector('button').remove();
      };
    });
    await assert.rejects(collectAgenda(page, { progressTimeout: 1000 }), /HTTP 503/);
    assert.equal(page.listenerCount('requestfailed'), 0);
  } finally { await page.close(); }
});

test('rejects foreign hosts, credentials, checkout and non-HTTPS URLs', () => {
  assert.equal(validateKiwolUrl('https://www.kiwol.com/agenda?location=GP').pathname, '/agenda');
  for (const url of ['http://www.kiwol.com/agenda', 'https://evil.example/agenda',
    'https://user:pass@www.kiwol.com/agenda', 'https://www.kiwol.com/billetterie/13402/checkout']) {
    assert.throws(() => validateKiwolUrl(url), /non autorisée/);
  }
});
