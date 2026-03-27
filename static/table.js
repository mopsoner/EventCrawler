function initDataTable(tableId, searchId, regionId, resetId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const search = searchId ? document.getElementById(searchId) : null;
  const region = regionId ? document.getElementById(regionId) : null;
  const reset = resetId ? document.getElementById(resetId) : null;

  function applyFilters() {
    const q = (search?.value || '').toLowerCase().trim();
    const regionValue = (region?.value || '').toLowerCase().trim();
    rows.forEach((row) => {
      const text = row.innerText.toLowerCase();
      const rowRegion = (row.dataset.region || '').toLowerCase();
      const okSearch = !q || text.includes(q);
      const okRegion = !regionValue || rowRegion === regionValue;
      row.style.display = okSearch && okRegion ? '' : 'none';
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
  region?.addEventListener('change', applyFilters);
  reset?.addEventListener('click', () => {
    if (search) search.value = '';
    if (region) region.value = '';
    applyFilters();
  });

  applyFilters();
}
