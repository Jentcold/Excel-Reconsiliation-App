import { api } from './api.js';
import { clear, el, initTheme, spinner, toast, toggleTheme } from './ui.js';

import renderAnalytics from './tabs/analytics.js';
import renderTable from './tabs/table.js';
import renderItems from './tabs/items.js';
import renderMapping from './tabs/mapping.js';
import renderUploads from './tabs/uploads.js';
import renderAccounts from './tabs/accounts.js';

initTheme();

const TABS = [
  { id: 'analytics', label: 'Analytics', roles: ['commercial', 'admin'], render: renderAnalytics },
  { id: 'table', label: 'Processed table', roles: ['commercial', 'admin'], render: renderTable },
  { id: 'items', label: 'Items & prices', roles: ['sales', 'commercial', 'admin'], render: renderItems },
  { id: 'uploads', label: 'Uploads', roles: ['commercial', 'admin'], render: renderUploads },
  { id: 'mapping', label: 'Mapping', roles: ['commercial', 'admin'], render: renderMapping },
  { id: 'accounts', label: 'Accounts', roles: ['admin'], render: renderAccounts },
];

const view = document.getElementById('view');
const tabStrip = document.getElementById('tabs');

let user = null;
let allowed = [];
let activeId = null;

async function boot() {
  try {
    ({ user } = await api.me());
  } catch {
    window.location.href = 'index.html';
    return;
  }
  sessionStorage.setItem('user', JSON.stringify(user));

  document.getElementById('who-name').textContent = user.name || user.email;
  document.getElementById('who-role').textContent = user.role;
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
  document.getElementById('logout').addEventListener('click', async () => {
    await api.logout().catch(() => {});
    sessionStorage.removeItem('user');
    window.location.href = 'index.html';
  });

  allowed = TABS.filter((tab) => tab.roles.includes(user.role));
  if (!allowed.length) {
    view.append(el('div', { class: 'empty-state', text: 'This account has no tabs assigned. Ask your administrator.' }));
    return;
  }

  buildTabStrip();
  document.getElementById('refresh').addEventListener('click', () => {
    const tab = allowed.find((t) => t.id === activeId);
    if (tab) load(tab);
  });

  window.addEventListener('ea:changed', () => {
    for (const [id, pane] of panes) {
      if (id !== activeId) delete pane.dataset.loadedAt;
    }
  });
  window.addEventListener('hashchange', openFromHash);
  openFromHash();
}

function buildTabStrip() {
  clear(tabStrip);
  for (const tab of allowed) {
    tabStrip.append(el('button', {
      role: 'tab',
      id: `tab-${tab.id}`,
      'aria-selected': 'false',
      text: tab.label,
      onclick: () => { window.location.hash = tab.id; },
    }));
  }
}

const panes = new Map();
const STALE_AFTER = 5 * 60 * 1000;

function paneFor(tab) {
  let pane = panes.get(tab.id);
  if (!pane) {
    pane = el('div', { class: 'pane' });
    panes.set(tab.id, pane);
    view.append(pane);
  }
  return pane;
}

function load(tab) {
  const pane = paneFor(tab);
  pane.dataset.loadedAt = String(Date.now());
  clear(pane).append(spinner());
  Promise.resolve(tab.render(pane, user)).catch((error) => {
    clear(pane).append(el('div', { class: 'notice err', text: error.message }));
    toast(error.message, 'err');
  });
}

function openFromHash() {
  const wanted = window.location.hash.replace('#', '');
  const tab = allowed.find((t) => t.id === wanted) || allowed[0];
  activeId = tab.id;

  for (const button of tabStrip.children) {
    button.setAttribute('aria-selected', button.id === `tab-${tab.id}` ? 'true' : 'false');
  }

  const pane = paneFor(tab);
  for (const [id, other] of panes) other.hidden = id !== tab.id;

  const loadedAt = Number(pane.dataset.loadedAt || 0);

  if (!loadedAt || Date.now() - loadedAt > STALE_AFTER) load(tab);
}

boot();
