function initDataTable(tableId, options = {}) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const tbody = table.querySelector('tbody');
  if (!tbody) return;

  const rows = Array.from(tbody.querySelectorAll('tr'));
  const searchInput = options.searchId ? document.getElementById(options.searchId) : null;
  const resetBtn = options.resetId ? document.getElementById(options.resetId) : null;
  const filters = (options.filters || []).map((f) => ({
    ...f,
    el: document.getElementById(f.id),
  }));

  const storageKey = `eventcrawler:${window.location.pathname}:${tableId}`;

  function loadState() {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || '{}');
    } catch {
      return {};
    }
  }

  function saveState() {
    const state = {
      search: searchInput ? searchInput.value : '',
      filters: {},
      sort: table.dataset.sort || '',
      order: table.dataset.order || '',
    };

    filters.forEach((f) => {
      if (f.el) state.filters[f.id] = f.el.value;
    });

    localStorage.setItem(storageKey, JSON.stringify(state));
  }

  function restoreState() {
    const state = loadState();

    if (searchInput && typeof state.search === 'string') {
      searchInput.value = state.search;
    }

    filters.forEach((f) => {
      if (f.el && state.filters && typeof state.filters[f.id] === 'string') {
        f.el.value = state.filters[f.id];
      }
    });

    if (state.sort) table.dataset.sort = state.sort;
    if (state.order) table.dataset.order = state.order;
  }

  function rowMatchesSearch(row) {
    if (!searchInput) return true;
    const query = (searchInput.value || '').trim().toLowerCase();
    if (!query) return true;
    return row.textContent.toLowerCase().includes(query);
  }

  function rowMatchesFilters(row) {
    return filters.every((f) => {
      if (!f.el) return true;
      const wanted = f.el.value;
      if (!wanted) return true;
      return String(row.dataset[f.dataset] || '') === wanted;
    });
  }

  function applyFilters() {
    rows.forEach((row) => {
      row.style.display = rowMatchesSearch(row) && rowMatchesFilters(row) ? '' : 'none';
    });
    saveState();
  }

  function sortRows(column, order, type = 'text') {
    const sorted = [...rows].sort((a, b) => {
      let av = a.dataset[column] || '';
      let bv = b.dataset[column] || '';

      if (type === 'number') {
        av = Number(av);
        bv = Number(bv);
        return order === 'asc' ? av - bv : bv - av;
      }

      av = String(av).toLowerCase();
      bv = String(bv).toLowerCase();
      return order === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    });

    sorted.forEach((row) => tbody.appendChild(row));
    table.dataset.sort = column;
    table.dataset.order = order;
    saveState();
  }

  function applySavedSort() {
    const sort = table.dataset.sort;
    const order = table.dataset.order;
    if (!sort || !order) return;

    const th = table.querySelector(`th[data-sort="${sort}"]`);
    const type = th ? th.dataset.type || 'text' : 'text';

    table.querySelectorAll('th[data-sort]').forEach((x) => x.removeAttribute('data-order'));
    if (th) th.setAttribute('data-order', order);

    sortRows(sort, order, type);
  }

  table.querySelectorAll('th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      const column = th.dataset.sort;
      const type = th.dataset.type || 'text';
      const currentSort = table.dataset.sort;
      const currentOrder = table.dataset.order || 'asc';
      const nextOrder = currentSort === column && currentOrder === 'asc' ? 'desc' : 'asc';

      table.querySelectorAll('th[data-sort]').forEach((x) => x.removeAttribute('data-order'));
      th.setAttribute('data-order', nextOrder);

      sortRows(column, nextOrder, type);
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', applyFilters);
  }

  filters.forEach((f) => {
    if (f.el) f.el.addEventListener('change', applyFilters);
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      filters.forEach((f) => {
        if (f.el) f.el.value = '';
      });

      table.dataset.sort = '';
      table.dataset.order = '';
      table.querySelectorAll('th[data-sort]').forEach((x) => x.removeAttribute('data-order'));

      localStorage.removeItem(storageKey);
      applyFilters();
    });
  }

  restoreState();
  applySavedSort();
  applyFilters();
}
