import { api } from '../api.js';
import { clear, dropZone, el, emptyState, notice, spinner, toast } from '../ui.js';

const DSR_MONTHS = 3;

const KINDS = [
  {
    id: 'dsr',
    title: 'DSR',
    blurb: 'Name files for the month — "DSR - Mar", "DSR - July", abbreviated or full. The year is taken as the current one. Re-uploading a month replaces the file held for it; the table uses the newest three months.',
    monthsUsed: DSR_MONTHS,
  },
  {
    id: 'inventory',
    title: 'Inventory',
    blurb: 'Same naming as the DSR — one file per month, and a new upload replaces that month. The table uses the most recent one.',
    monthsUsed: 1,
  },
  {
    id: 'psi',
    title: 'PSI',
    blurb: 'The current month up to today, sent daily. The filename doesn\'t matter — it\'s filed under the day you upload it, and uploading again the same day replaces that day. Every day is kept, so an older one can be pulled up on the table tab.',
  },
];

const state = { uploads: [], canUpload: false, repaint: null };

export default async function renderUploads(view, user) {
  clear(view).append(spinner('Loading uploads…'));
  try {
    ({ uploads: state.uploads } = await api.listUploads());
  } catch (error) {
    clear(view).append(notice(error.message, 'err'));
    return;
  }
  state.canUpload = user.role === 'commercial';
  draw(view);
}

async function reload() {
  try {
    ({ uploads: state.uploads } = await api.listUploads());
  } catch (error) {
    toast(error.message, 'err');
    return;
  }
  state.repaint?.();
}

function draw(view) {
  clear(view);

  if (!state.canUpload) {
    view.append(notice('Read-only: uploads are managed by the commercial team.', 'warn'));
  }

  const sections = [];
  for (const kind of KINDS) {
    const count = el('span', { class: 'badge' });
    const list = el('div');
    const panel = el('div', { class: 'panel' }, [
      el('div', { class: 'row between' }, [el('h2', { text: kind.title }), count]),
      el('p', { class: 'muted', style: 'margin:0 0 14px', text: kind.blurb }),
    ]);

    if (state.canUpload) {
      panel.append(dropZone(`Drop a ${kind.title} workbook here, or click to choose`,
        '.xlsx,.xls,.xlsm', (file, onProgress) => send(kind.id, file, onProgress)));
    }
    panel.append(list);
    view.append(panel);
    sections.push({ kind, count, list });
  }

  state.repaint = () => {
    for (const { kind, count, list } of sections) {
      const mine = state.uploads.filter((u) => u.kind === kind.id);
      count.textContent = `${mine.length} on file`;
      clear(list).append(mine.length
        ? fileList(mine, kind.monthsUsed)
        : emptyState(`No ${kind.title} files yet.`));
    }
  };
  state.repaint();
}

async function send(kind, file, onProgress) {

  try {
    const result = await api.upload(kind, file, onProgress);
    toast(result.message, 'ok');
    await reload();
  } catch (error) {

    toast(error.message, error.status === 409 ? 'warn' : 'err', 7000);
  }
}

function fileList(uploads, monthsUsed) {
  const sorted = [...uploads].sort((a, b) => b.period_key.localeCompare(a.period_key));
  const table = el('table', { class: 'data' });
  table.append(el('thead', {}, el('tr', {}, [
    el('th', { text: 'Period' }),
    el('th', { text: 'File' }),
    el('th', { text: 'Uploaded by' }),
    el('th', { text: 'When' }),
    state.canUpload && el('th', { text: '' }),
  ].filter(Boolean))));

  const body = el('tbody');
  sorted.forEach((upload, index) => {

    const inUse = !monthsUsed || index < monthsUsed;
    body.append(el('tr', { class: inUse ? '' : 'muted' }, [
      el('td', { title: upload.period_key }, [
        upload.period_label || upload.period_key,
        !inUse && el('span', { class: 'badge', style: 'margin-left:8px', text: 'not in the table' }),
      ].filter(Boolean)),
      el('td', { title: upload.filename, text: upload.filename }),
      el('td', { text: upload.uploaded_by || '—' }),
      el('td', { text: upload.uploaded_at ? new Date(upload.uploaded_at).toLocaleString() : '—' }),
      state.canUpload && el('td', {}, el('button', {
        class: 'danger icon',
        text: 'Remove',
        onclick: async (event) => {
          if (!confirm(`Remove ${upload.filename}? The processed table will rebuild without it.`)) return;
          event.target.disabled = true;
          try {
            const result = await api.deleteUpload(upload.id);
            toast(result.message, 'ok');
            await reload();
          } catch (error) {
            toast(error.message, 'err');
            event.target.disabled = false;
          }
        },
      })),
    ].filter(Boolean)));
  });
  table.append(body);
  return el('div', { class: 'table-scroll', style: 'margin-top:14px' }, table);
}
