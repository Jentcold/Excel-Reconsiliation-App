import { api } from '../api.js';
import { clear, debounce, dropZone, el, emptyState, notice, num, spinner, toast } from '../ui.js';

const state = { items: [], editable: false, query: '', repaint: null };

export default async function renderItems(view, user) {
  clear(view).append(spinner('Loading items…'));

  try {
    const data = await api.items();
    state.items = data.items;
    state.editable = data.editable;
  } catch (error) {
    clear(view).append(notice(error.message, 'err'));
    return;
  }
  draw(view, user);
}

async function reload() {
  try {
    const data = await api.items();
    state.items = data.items;
    state.editable = data.editable;
  } catch (error) {
    toast(error.message, 'err');
    return;
  }
  state.repaint?.();
}

function draw(view, user) {
  clear(view);
  const results = el('div');
  const count = el('span', { class: 'badge' });
  const repaint = () => paint(results, view, user, count);
  state.repaint = repaint;
  view.append(toolbar(view, user, count, repaint), results);
  repaint();
}

function paint(results, view, user, count) {
  const matches = filtered();
  if (count) {
    count.textContent = matches.length === state.items.length
      ? `${state.items.length} items`
      : `${matches.length} of ${state.items.length} items`;
  }

  clear(results);
  if (!matches.length) {
    results.append(emptyState(
      state.items.length
        ? 'No items match that search.'
        : state.editable
          ? 'No items yet — import the specs & prices sheet above.'
          : 'No items have been published yet.',
    ));
    return;
  }

  const grid = el('div', { class: 'card-grid' });
  for (const item of matches) grid.append(card(item, state.editable, view, user));
  results.append(grid);
}

function filtered() {
  const needle = state.query.trim().toLowerCase();
  if (!needle) return state.items;
  return state.items.filter((item) => {
    const haystack = [item.name, item.brand, item.category, item.unified_code, item.ram, item.rom,
      ...(item.specs || []).flatMap((s) => [s.label, s.value])].join(' ').toLowerCase();
    return haystack.includes(needle);
  });
}

function toolbar(view, user, count, repaint) {
  const panel = el('div', { class: 'panel' });
  const row = el('div', { class: 'row between' });

  const search = el('input', { type: 'search', placeholder: 'Search items, brands, specs…', style: 'width:280px' });
  search.value = state.query;

  const rerun = debounce(repaint);
  search.addEventListener('input', () => { state.query = search.value; rerun(); });

  row.append(search, count);
  panel.append(row);

  if (state.editable) {
    panel.append(el('div', { style: 'margin-top:14px' },
      dropZone('Import the specs & prices sheet (.xlsx) — existing codes are updated, new ones added',
        '.xlsx,.xls', async (file, onProgress) => {
          try {
            const result = await api.importItems(file, onProgress);
            toast(result.message, 'ok');
            await reload();
          } catch (error) {
            toast(error.message, 'err');
          }
        })));
  }
  return panel;
}

function card(item, editable, view, user) {
  const photo = el('div', { class: 'photo' });
  if (item.image_url) {
    photo.append(el('img', { src: item.image_url, alt: item.name || item.unified_code, loading: 'lazy' }));
  } else {
    photo.append(el('span', { class: 'placeholder', text: 'No photo' }));
  }

  if (editable) {
    const input = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', class: 'hidden' });
    const button = el('button', {
      class: 'upload',
      text: item.image_url ? 'Replace' : 'Add photo',
      onclick: () => { if (!button.disabled) input.click(); },
    });
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      input.value = '';
      if (!file) return;
      button.disabled = true;
      button.textContent = 'Uploading…';
      try {
        await api.uploadItemImage(item.id, file, (fraction) => {
          button.textContent = fraction === null ? 'Saving…' : `${Math.round(fraction * 100)}%`;
        });
        toast('Photo updated.', 'ok');
        await reload();
      } catch (error) {
        toast(error.message, 'err');
        button.disabled = false;
        button.textContent = item.image_url ? 'Replace' : 'Add photo';
      }
    });
    photo.append(button, input);
  }

  const config = [item.ram, item.rom].filter(Boolean).join(' · ');
  const currency = item.currency || 'EGP';

  const prices = el('div', { class: 'prices' });
  if (item.rrp != null) {
    prices.append(el('div', { class: 'price' }, `${num(item.rrp)} ${currency}`));
    prices.append(el('div', { class: 'muted', text: 'RRP' }));
  }
  if (item.rdp != null) {
    prices.append(el('div', { class: 'price-sub' }, `${num(item.rdp)} ${currency}`));
    prices.append(el('div', { class: 'muted', text: 'RDP' }));
  }
  if (item.rrp == null && item.rdp == null) {
    prices.append(el('div', { class: 'muted', text: 'Price not set' }));
  }

  const body = el('div', { class: 'body' }, [
    el('div', { class: 'brand' }, [item.brand || '', item.category ? ` · ${item.category}` : ''].join('')),
    el('div', { class: 'name', text: item.name || '(unnamed)' }),
    config && el('div', { class: 'config', text: config }),
    prices,
  ]);

  const specs = item.specs || [];
  if (specs.length) {
    const list = el('ul', { class: 'specs' });
    for (const spec of specs) {
      if (!spec?.label) continue;
      list.append(el('li', {}, [
        el('span', { class: 'k', text: spec.label }),
        el('span', { class: 'v', title: String(spec.value ?? ''), text: String(spec.value ?? '—') }),
      ]));
    }
    body.append(list);
  }

  return el('div', { class: 'item-card' }, [photo, body]);
}
