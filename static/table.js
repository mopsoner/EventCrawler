function initDataTable(tableId, config = {}) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const search = config.searchId ? document.getElementById(config.searchId) : null;
  const reset = config.resetId ? document.getElementById(config.resetId) : null;
  const filters = (config.filters || []).map((item) => ({
    el: document.getElementById(item.id),
    dataset: item.dataset,
    mode: item.mode || 'exact'
  })).filter((item) => item.el);

  function applyFilters() {
    const q = (search?.value || '').toLowerCase().trim();
    rows.forEach((row) => {
      const text = row.innerText.toLowerCase();
      const okSearch = !q || text.includes(q);
      let okFilters = true;
      for (const filter of filters) {
        const wanted = String(filter.el.value || '').toLowerCase().trim();
        if (!wanted) continue;
        const actual = String(row.dataset[filter.dataset] || '').toLowerCase().trim();
        if (filter.mode === 'includes') {
          if (!actual.includes(wanted)) okFilters = false;
        } else {
          if (actual !== wanted) okFilters = false;
        }
      }
      row.style.display = okSearch && okFilters ? '' : 'none';
    });
  }

  table.querySelectorAll('th[data-sort]').forEach((th) => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      const type = th.dataset.type || 'text';
      const asc = th.dataset.order !== 'asc';
      table.querySelectorAll('th[data-sort]').forEach((other) => {
        if (other !== th) other.dataset.order = '';
      });
      th.dataset.order = asc ? 'asc' : 'desc';
      const sorted = [...rows].sort((a, b) => {
        let va = a.dataset[key] || '';
        let vb = b.dataset[key] || '';
        if (type === 'number') {
          va = parseFloat(String(va).replace(',', '.')) || 0;
          vb = parseFloat(String(vb).replace(',', '.')) || 0;
          return asc ? va - vb : vb - va;
        }
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        return asc ? va.localeCompare(vb) : vb.localeCompare(va);
      });
      sorted.forEach((row) => tbody.appendChild(row));
      applyFilters();
    });
  });

  search?.addEventListener('input', applyFilters);
  filters.forEach((filter) => filter.el.addEventListener('change', applyFilters));
  reset?.addEventListener('click', () => {
    if (search) search.value = '';
    filters.forEach((filter) => { filter.el.value = ''; });
    applyFilters();
  });

  applyFilters();
}
