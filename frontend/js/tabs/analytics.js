import { api } from '../api.js';
import { clear, compact, el, emptyState, notice, num, spinner } from '../ui.js';

export default async function renderAnalytics(view) {
  clear(view).append(spinner('Crunching the numbers…'));

  let data;
  try {
    data = await api.analytics();
  } catch (error) {
    clear(view).append(notice(error.message, error.status === 409 ? 'warn' : 'err'));
    return;
  }

  clear(view);

  view.append(statGrid([
    ['Net sales', num(data.net_sales), 'Latest DSR, summed across products'],
    ['Net quantity', num(data.net_qty), 'Units sold in the latest DSR'],
    ['PSI total', num(data.psi_total), 'Sell-out across all PSI periods'],
    ['Inventory value', num(data.inventory_value), 'From the latest inventory file'],
    ['Products', num(data.product_count), 'Rows in the mapping table'],
  ]));

  const charts = el('div', { class: 'chart-grid' });
  charts.append(barPanel(
    'Net sales by month',
    (data.by_month || []).map((m) => ({ name: m.label, value: m.net_sales })),
    'No DSR months to compare yet.',
  ));
  charts.append(barPanel(
    'Quantity by month',
    (data.by_month || []).map((m) => ({ name: m.label, value: m.qty })),
    'No DSR months to compare yet.',
  ));
  charts.append(barPanel(
    'Top 10 products by net sales',
    (data.top_products || []).map((p) => ({ name: p.label, value: p.net_sales })),
    'No product sales recorded.',
  ));
  view.append(charts);
}

function statGrid(entries) {
  const grid = el('div', { class: 'stat-grid' });
  for (const [label, value, hint] of entries) {
    grid.append(el('div', { class: 'stat', title: hint }, [
      el('div', { class: 'label', text: label }),
      el('div', { class: 'value', text: value }),
    ]));
  }
  return grid;
}

function barPanel(title, series, emptyMessage) {
  const panel = el('div', { class: 'panel' }, [el('h2', { text: title })]);
  const points = series.filter((p) => Number.isFinite(Number(p.value)) && Number(p.value) !== 0);

  if (!points.length) {
    panel.append(emptyState(emptyMessage));
    return panel;
  }

  const max = Math.max(...points.map((p) => Math.abs(Number(p.value))));
  for (const point of points) {
    const width = max ? (Math.abs(Number(point.value)) / max) * 100 : 0;
    panel.append(el('div', { class: 'bar-row' }, [
      el('div', { class: 'name', title: point.name, text: point.name ?? '—' }),
      el('div', { class: 'bar-track' }, el('div', { class: 'bar-fill', style: `width:${width}%` })),
      el('div', { class: 'val', title: num(point.value), text: compact(point.value) }),
    ]));
  }
  return panel;
}
