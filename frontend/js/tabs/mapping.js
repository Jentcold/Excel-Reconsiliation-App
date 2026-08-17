import { api } from '../api.js';
import { clear, debounce, dropZone, el, emptyState, notice, spinner, toast } from '../ui.js';

const FIELDS = [
  { key: 'unified_code', label: 'Unified code', required: true },
  { key: 'psi_model', label: 'PSI model' },
  { key: 'inventory_family', label: 'Inventory family' },
  { key: 'dsr_item_model', label: 'DSR item model' },
  { key: 'comment', label: 'Comment' },
];

const state = { rows: [], editable: false, query: '', repaint: null };

async function reload() {
  try {
    const data = await api.mapping();
    state.rows = data.rows;
    state.editable = data.editable;
  } catch (error) {
    toast(error.message, 'err');
    return;
  }
  state.repaint?.();
}

export default async function renderMapping(view, user) {
  clear(view).append(spinner('Loading mapping…'));

  try {
    const data = await api.mapping();
    state.rows = data.rows;
    state.editable = data.editable;
  } catch (error) {
    clear(view).append(notice(error.message, 'err'));
    return;
  }
  draw(view, user);
}

function draw(view, user) {
  clear(view);

  const panel = el('div', { class: 'panel' });
  const results = el('div');
  const count = el('span', { class: 'badge' });

  const search = el('input', { type: 'search', placeholder: 'Search the mapping…', style: 'width:280px' });
  search.value = state.query;
  const repaint = () => paint(results, count, view, user);
  state.repaint = repaint;
  const rerun = debounce(repaint);
  search.addEventListener('input', () => { state.query = search.value; rerun(); });

  panel.append(el('div', { class: 'row between' }, [search, count]));

  if (state.editable) {
    panel.append(el('div', { style: 'margin-top:14px' },
      dropZone('Import a map workbook (.xlsx) — matching codes are updated, new ones added',
        '.xlsx,.xls', async (file, onProgress) => {
          try {
            const result = await api.importMapping(file, onProgress);
            toast(result.message, 'ok');
            await reload();
          } catch (error) {
            toast(error.message, 'err');
          }
        })));
    panel.append(addRowForm(view, user));
  } else {
    panel.append(notice('Read-only: the mapping is maintained by the commercial team.', 'warn'));
  }

  view.append(panel, results);
  repaint();
}

function paint(results, count, view, user) {
  const needle = state.query.trim().toLowerCase();
  const rows = needle
    ? state.rows.filter((row) => FIELDS.some((f) => String(row[f.key] ?? '').toLowerCase().includes(needle)))
    : state.rows;

  count.textContent = rows.length === state.rows.length
    ? `${state.rows.length} products`
    : `${rows.length} of ${state.rows.length} products`;

  clear(results);
  results.append(rows.length
    ? mappingTable(rows, state.editable, view, user)
    : emptyState(state.rows.length ? 'Nothing matches that search.' : 'No mapping rows yet.'));
}

function addRowForm(view, user) {
  const wrap = el('div', { class: 'row', style: 'margin-top:14px;align-items:flex-end' });
  const inputs = {};

  for (const field of FIELDS) {
    inputs[field.key] = el('input', { type: 'text', placeholder: field.required ? 'required' : '' });
    wrap.append(el('div', { style: 'flex:1;min-width:130px' }, [
      el('label', { text: field.label }),
      inputs[field.key],
    ]));
  }

  wrap.append(el('button', {
    class: 'primary',
    text: 'Add row',
    onclick: async (event) => {
      const payload = {};
      for (const field of FIELDS) {
        const value = inputs[field.key].value.trim();
        if (value) payload[field.key] = value;
      }
      if (!payload.unified_code) {
        toast('A unified code is required.', 'warn');
        return;
      }
      event.target.disabled = true;
      try {
        await api.addMappingRow(payload);
        toast(`${payload.unified_code} added.`, 'ok');
        for (const field of FIELDS) inputs[field.key].value = '';
        await reload();
      } catch (error) {
        toast(error.message, 'err');
      } finally {
        event.target.disabled = false;
      }
    },
  }));
  return wrap;
}

function mappingTable(rows, editable, view, user) {
  const table = el('table', { class: 'data' });
  table.append(el('thead', {}, el('tr', {}, [
    ...FIELDS.map((f) => el('th', { text: f.label })),
    editable && el('th', { text: '' }),
  ].filter(Boolean))));

  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const field of FIELDS) {
      const value = row[field.key];
      const cell = el('td', {
        title: value ?? '',
        text: value || '—',
        class: value ? '' : 'empty',
      });
      if (editable) {
        cell.setAttribute('contenteditable', 'plaintext-only');
        cell.dataset.key = field.key;
        cell.dataset.original = value ?? '';
        cell.addEventListener('blur', () => saveCell(row, cell, field));
        cell.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') { event.preventDefault(); cell.blur(); }
          if (event.key === 'Escape') { cell.textContent = cell.dataset.original || '—'; cell.blur(); }
        });
      }
      tr.append(cell);
    }
    if (editable) {
      tr.append(el('td', {}, el('button', {
        class: 'danger icon',
        text: 'Delete',
        onclick: async () => {
          if (!confirm(`Delete mapping row ${row.unified_code}?`)) return;
          try {
            await api.deleteMappingRow(row.id);
            toast('Row deleted.', 'ok');
            await reload();
          } catch (error) {
            toast(error.message, 'err');
          }
        },
      })));
    }
    body.append(tr);
  }
  table.append(body);
  return el('div', { class: 'table-scroll', style: 'max-height:calc(100vh - 380px);overflow-y:auto' }, table);
}

async function saveCell(row, cell, field) {
  const next = cell.textContent.trim().replace(/^—$/, '');
  if (next === (cell.dataset.original || '')) return;
  if (field.required && !next) {
    toast(`${field.label} can't be empty.`, 'warn');
    cell.textContent = cell.dataset.original || '';
    return;
  }
  try {
    await api.editMappingRow(row.id, { [field.key]: next });
    cell.dataset.original = next;
    cell.classList.toggle('empty', !next);
    if (!next) cell.textContent = '—';
    toast('Saved.', 'ok', 1500);
  } catch (error) {
    cell.textContent = cell.dataset.original || '—';
    toast(error.message, 'err');
  }
}
