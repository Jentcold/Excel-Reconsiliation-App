import { api } from '../api.js';
import { clear, debounce, el, emptyState, notice, num, spinner, toast } from '../ui.js';

let state = { payload: null, sheetId: null, sort: {}, filter: '' };

export default async function renderTable(view, user) {
  clear(view).append(spinner('Loading the table…'));
  try {
    state.payload = await api.table();
  } catch (error) {
    clear(view).append(notice(error.message, error.status === 409 ? 'warn' : 'err'));
    return;
  }
  state.sheetId = state.sheetId && state.payload.sheets.some((s) => s.id === state.sheetId)
    ? state.sheetId
    : state.payload.sheets[0]?.id;
  draw(view, user);
}

function draw(view, user) {
  clear(view);

  const body = el('div');
  const repaint = () => paint(body, view, user);
  view.append(toolbar(view, user, repaint), body);
  repaint();
}

function paint(body, view, user) {
  clear(body);
  const { payload } = state;

  const tabs = el('div', { class: 'sheet-tabs' });
  for (const sheet of payload.sheets) {
    tabs.append(el('button', {
      'aria-selected': sheet.id === state.sheetId ? 'true' : 'false',
      text: `${sheet.name}  (${sheet.rows.length})`,
      onclick: () => {
        state.sheetId = sheet.id;
        state.sort = {};
        paint(body, view, user);
      },
    }));
  }
  body.append(tabs);

  const sheet = payload.sheets.find((s) => s.id === state.sheetId);
  if (!sheet || !sheet.rows.length) {
    body.append(emptyState('Nothing to show on this sheet.'));
    return;
  }
  body.append(sheetTable(sheet, () => paint(body, view, user)));
}

function toolbar(view, user, repaint) {
  const { payload } = state;
  const bar = el('div', { class: 'panel row between' });

  const left = el('div', { class: 'row' });

  const search = el('input', { type: 'search', placeholder: 'Filter rows…', style: 'width:220px' });
  search.value = state.filter;
  const rerun = debounce(repaint);
  search.addEventListener('input', () => { state.filter = search.value; rerun(); });
  left.append(search);

  const right = el('div', { class: 'row' });
  right.append(el('span', {
    class: 'badge',
    text: builtLabel(payload.built_at),
    title: 'The table is rebuilt when a file is uploaded or the mapping changes — '
         + 'opening this tab never recomputes it.',
  }));

  right.append(el('button', {
    class: 'primary',
    text: 'Download Excel',
    onclick: async (event) => {
      event.target.disabled = true;
      try {
        const blob = await api.exportBlob();
        const url = URL.createObjectURL(blob);
        const link = el('a', { href: url, download: 'combined_output.xlsx' });
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      } catch (error) {
        toast(error.message, 'err');
      } finally {
        event.target.disabled = false;
      }
    },
  }));

  bar.append(left, right);
  return bar;
}

function builtLabel(builtAt) {
  if (!builtAt) return 'built just now';
  const when = new Date(builtAt);
  if (Number.isNaN(when.getTime())) return 'built';
  const sameDay = when.toDateString() === new Date().toDateString();
  return `built ${sameDay ? when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                          : when.toLocaleString()}`;
}

function visibleRows(sheet) {
  let rows = sheet.rows;
  const needle = state.filter.trim().toLowerCase();
  if (needle) {
    rows = rows.filter((row) =>
      Object.values(row).some((value) => String(value ?? '').toLowerCase().includes(needle)));
  }
  const { key, dir } = state.sort;
  if (key) {
    const column = sheet.columns.find((c) => c.key === key);
    rows = [...rows].sort((a, b) => {
      const [x, y] = [a[key], b[key]];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const cmp = column?.type === 'number'
        ? Number(x) - Number(y)
        : String(x).localeCompare(String(y));
      return dir === 'asc' ? cmp : -cmp;
    });
  }
  return rows;
}

function sheetTable(sheet, repaint) {
  const rows = visibleRows(sheet);
  const table = el('table', { class: 'data' });

  const head = el('tr');
  for (const column of sheet.columns) {
    const active = state.sort.key === column.key;
    head.append(el('th', {
      class: column.type === 'number' ? 'num' : '',
      title: column.label,
      text: active ? `${column.label} ${state.sort.dir === 'asc' ? '▲' : '▼'}` : column.label,
      onclick: () => {
        state.sort = active && state.sort.dir === 'asc'
          ? { key: column.key, dir: 'desc' }
          : { key: column.key, dir: 'asc' };
        repaint();
      },
    }));
  }
  table.append(el('thead', {}, head));

  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const column of sheet.columns) {
      const value = row[column.key];
      const blank = value === null || value === undefined || value === '';
      tr.append(el('td', {
        class: `${column.type === 'number' ? 'num' : ''}${blank ? ' empty' : ''}`,
        title: blank ? '' : String(value),
        text: blank ? '—' : (column.type === 'number' ? num(value) : String(value)),
      }));
    }
    body.append(tr);
  }
  table.append(body);

  if (Object.keys(sheet.totals || {}).length) {
    const foot = el('tr');
    sheet.columns.forEach((column, index) => {
      const total = sheet.totals[column.key];
      foot.append(el('td', {
        class: column.type === 'number' ? 'num' : '',
        text: total !== undefined ? num(total) : (index === 0 ? 'Total' : ''),
      }));
    });
    table.append(el('tfoot', {}, foot));
  }

  const wrap = el('div', { class: 'table-scroll', style: 'max-height:calc(100vh - 260px);overflow-y:auto' });
  wrap.append(table);

  const caption = el('div', { class: 'muted', style: 'margin-top:8px' },
    `${rows.length} of ${sheet.rows.length} rows`);
  return el('div', {}, [wrap, caption]);
}
