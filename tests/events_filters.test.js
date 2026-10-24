const test = require('node:test');
const assert = require('node:assert/strict');
const { parseLooseDate, matchesPeriod } = require('../static/free-filters.js');

const matches = (date, period, now = '2026-10-24') =>
  matchesPeriod(parseLooseDate(date), period, parseLooseDate(now));

test('today also belongs to the current week and month', () => {
  for (const period of ['today', 'this_week', 'this_month']) {
    assert.equal(matches('2026-10-24T23:00:00-04:00', period), true, period);
  }
  assert.equal(matches('23 octobre 2026', 'this_week'), true);
  assert.equal(matches('23/10/2026', 'past'), true);
  assert.equal(matches('2026-10-01', 'this_month'), true);
});

test('calendar week and month boundaries overlap correctly', () => {
  assert.equal(matches('2026-10-25', 'this_week'), true);
  assert.equal(matches('2026-10-26', 'this_week'), false);
  assert.equal(matches('2026-10-26', 'next_week'), true);
  assert.equal(matches('2026-11-01', 'next_week'), true);
  assert.equal(matches('2026-11-01', 'next_month'), true);
  assert.equal(matches('2026-11-02', 'next_week'), false);
  assert.equal(matches('2026-12-01', 'next_month'), false);
  assert.equal(matches('2027-01-01', 'next_month', '2026-12-31'), true);
});

test('missing dates only match unknown or an unfiltered selection', () => {
  assert.equal(matches('', 'unknown'), true);
  assert.equal(matches('', ''), true);
  assert.equal(matches('', 'this_month'), false);
  assert.equal(matches('2026-10-24', 'unknown'), false);
  assert.equal(matches('2026-02-30', 'unknown'), true);
});
