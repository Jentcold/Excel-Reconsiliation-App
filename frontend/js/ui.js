const THEME_KEY = 'ea-theme';

export function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);

  const theme = saved || 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  return theme;
}

export function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem(THEME_KEY, next);
  return next;
}

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value !== null && value !== undefined && value !== false) {
      node.setAttribute(key, value === true ? '' : value);
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function num(value, decimals = 0) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function compact(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return num(n);
}

let toastHost = null;

export function toast(message, kind = 'ok', ms = 4200) {
  if (!toastHost) {
    toastHost = el('div', { class: 'toast-host' });
    document.body.append(toastHost);
  }
  const node = el('div', { class: `toast ${kind}`, text: message });
  toastHost.append(node);
  setTimeout(() => node.remove(), ms);
}

export function spinner(label = 'Loading…') {
  return el('div', { class: 'empty-state' }, [el('span', { class: 'spinner' }), ' ', label]);
}

export function emptyState(message) {
  return el('div', { class: 'empty-state', text: message });
}

export function notice(message, kind = 'err') {
  return el('div', { class: `notice ${kind}`, text: message });
}

export function debounce(fn, ms = 140) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function dropZone(label, accept, onFile) {
  const input = el('input', { type: 'file', accept });
  const caption = el('div', { class: 'drop-label', text: label });
  const fill = el('div', { class: 'progress-fill' });
  const bar = el('div', { class: 'progress' }, fill);
  const zone = el('div', { class: 'drop' }, [caption, bar, input]);
  let busy = false;

  function progress(fraction, name) {
    if (fraction === null) {
      bar.classList.add('indeterminate');
      fill.style.width = '100%';
      caption.textContent = `Processing ${name}… this can take a moment.`;
      return;
    }
    bar.classList.remove('indeterminate');
    fill.style.width = `${Math.round(fraction * 100)}%`;
    caption.textContent = `Uploading ${name}… ${Math.round(fraction * 100)}%`;
  }

  async function handle(file) {
    if (busy) return;
    busy = true;
    zone.classList.add('busy');
    progress(0, file.name);
    try {
      await onFile(file, (fraction) => progress(fraction, file.name));
    } finally {
      busy = false;
      zone.classList.remove('busy');
      bar.classList.remove('indeterminate');
      fill.style.width = '0%';
      caption.textContent = label;
    }
  }

  zone.addEventListener('click', () => { if (!busy) input.click(); });
  input.addEventListener('change', () => {
    const file = input.files?.[0];
    input.value = '';
    if (file) handle(file);
  });
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (!busy) zone.classList.add('over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('over');
    if (e.dataTransfer.files?.[0]) handle(e.dataTransfer.files[0]);
  });
  return zone;
}
