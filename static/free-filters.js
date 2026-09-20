(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.FreeProductFilters = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  const monthNumbers = {
    january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
    july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
    janvier: 0, fevrier: 1, 'février': 1, mars: 2, avril: 3, mai: 4, juin: 5,
    juillet: 6, aout: 7, 'août': 7, septembre: 8, octobre: 9, novembre: 10,
    decembre: 11, 'décembre': 11,
  };
  const monthPattern = Object.keys(monthNumbers).join('|');

  function validLocalDate(year, month, day) {
    const date = new Date(year, month, day);
    return date.getFullYear() === year && date.getMonth() === month && date.getDate() === day
      ? date
      : null;
  }

  function parseLooseDate(text) {
    if (!text) return null;
    const raw = String(text).trim().toLowerCase();
    let match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[t\s]|$)/);
    if (match) return validLocalDate(Number(match[1]), Number(match[2]) - 1, Number(match[3]));

    match = raw.match(/^(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:\D|$)/);
    if (match) return validLocalDate(Number(match[3]), Number(match[2]) - 1, Number(match[1]));

    match = raw.match(new RegExp(`(\\d{1,2})\\D*?(${monthPattern})\\D*?(20\\d{2})`, 'i'));
    if (match) return validLocalDate(Number(match[3]), monthNumbers[match[2]], Number(match[1]));

    match = raw.match(new RegExp(`(${monthPattern})\\s+(\\d{1,2})\\D*?(20\\d{2})`, 'i'));
    if (match) return validLocalDate(Number(match[3]), monthNumbers[match[1]], Number(match[2]));
    return null;
  }

  function periodForDate(date, currentDate = new Date()) {
    if (!date) return { key: 'unknown', label: 'Date unknown' };
    const today = new Date(currentDate.getFullYear(), currentDate.getMonth(), currentDate.getDate());
    const eventDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const diffDays = Math.round((eventDay - today) / 86400000);
    const mondayOffset = today.getDay() === 0 ? -6 : 1 - today.getDay();
    const startThisWeek = new Date(today); startThisWeek.setDate(today.getDate() + mondayOffset);
    const endThisWeek = new Date(startThisWeek); endThisWeek.setDate(startThisWeek.getDate() + 6);
    const startNextWeek = new Date(startThisWeek); startNextWeek.setDate(startThisWeek.getDate() + 7);
    const endNextWeek = new Date(startNextWeek); endNextWeek.setDate(startNextWeek.getDate() + 6);
    const endThisMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    const startNextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1);
    const endNextMonth = new Date(today.getFullYear(), today.getMonth() + 2, 0);

    if (diffDays < 0) return { key: 'past', label: 'Past' };
    if (diffDays === 0) return { key: 'today', label: 'Today' };
    if (eventDay >= startThisWeek && eventDay <= endThisWeek) return { key: 'this_week', label: 'This week' };
    if (eventDay >= startNextWeek && eventDay <= endNextWeek) return { key: 'next_week', label: 'Next week' };
    if (eventDay <= endThisMonth) return { key: 'this_month', label: 'This month' };
    if (eventDay >= startNextMonth && eventDay <= endNextMonth) return { key: 'next_month', label: 'Next month' };
    return { key: 'future', label: 'Upcoming' };
  }

  function initializeRows(documentRoot = document, currentDate = new Date()) {
    documentRoot.querySelectorAll('#free-table tbody tr').forEach((row) => {
      const info = periodForDate(parseLooseDate(row.dataset.date || ''), currentDate);
      row.dataset.period = info.key;
      const badge = row.querySelector('.js-period-badge');
      if (badge) {
        badge.textContent = info.label;
        badge.style.display = '';
      }
    });
  }

  return { parseLooseDate, periodForDate, initializeRows };
}));
