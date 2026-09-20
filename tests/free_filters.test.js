const test = require('node:test');
const assert = require('node:assert/strict');
const { parseLooseDate, periodForDate } = require('../static/free-filters.js');

test('parses crawler date formats without changing the calendar day', () => {
  for (const value of [
    '2026-10-12T20:00:00-04:00',
    '12 octobre 2026 à 20h',
    'October 12, 2026 at 8:00 pm',
    '12/10/2026',
  ]) {
    const date = parseLooseDate(value);
    assert.ok(date, value);
    assert.deepEqual([date.getFullYear(), date.getMonth(), date.getDate()], [2026, 9, 12]);
  }
});

test('rejects missing and invalid dates', () => {
  assert.equal(parseLooseDate(''), null);
  assert.equal(parseLooseDate('2026-02-30T12:00:00'), null);
});

test('assigns dates to each selectable period', () => {
  const now = new Date(2026, 8, 20); // Sunday
  const cases = {
    '2026-09-19': 'past',
    '2026-09-20': 'today',
    '2026-09-21': 'next_week',
    '2026-09-28': 'this_month',
    '2026-10-12': 'next_month',
    '2026-11-12': 'future',
  };
  for (const [value, expected] of Object.entries(cases)) {
    assert.equal(periodForDate(parseLooseDate(value), now).key, expected, value);
  }
  assert.equal(periodForDate(null, now).key, 'unknown');
});
