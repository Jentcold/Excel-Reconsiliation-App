export const API_BASE = window.API_BASE || 'http://localhost:8000/api';

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

function messageFrom(detail, fallback) {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message;

    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}

function announceChange() {
  window.dispatchEvent(new CustomEvent('ea:changed'));
}

function expired() {
  sessionStorage.removeItem('user');
  window.location.href = 'index.html';
  return new ApiError('Session expired', 401, null);
}

function upload(path, file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.withCredentials = true;

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    xhr.upload.addEventListener('load', () => onProgress(null));

    xhr.addEventListener('load', () => {
      if (xhr.status === 401) { reject(expired()); return; }
      let payload = {};
      try { payload = JSON.parse(xhr.responseText); } catch {  }
      if (xhr.status >= 200 && xhr.status < 300) { announceChange(); resolve(payload); return; }
      reject(new ApiError(
        messageFrom(payload.detail, `Request failed (${xhr.status})`), xhr.status, payload.detail,
      ));
    });
    xhr.addEventListener('error', () =>
      reject(new ApiError('Can\'t reach the server. Is the API running?', 0, null)));
    xhr.addEventListener('abort', () => reject(new ApiError('Upload cancelled.', 0, null)));

    xhr.send(form);
  });
}

async function request(path, { method = 'GET', body, formData, raw = false } = {}) {
  const options = { method, credentials: 'include', headers: {} };
  if (formData) {
    options.body = formData;
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new ApiError('Can\'t reach the server. Is the API running?', 0, null);
  }

  if (response.status === 401 && !path.startsWith('/auth/')) throw expired(path);

  if (raw) {
    if (!response.ok) throw new ApiError('Download failed', response.status, null);
    return response.blob();
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      messageFrom(payload.detail, `Request failed (${response.status})`),
      response.status,
      payload.detail,
    );
  }
  if (method !== 'GET' && !path.startsWith('/auth/')) announceChange();
  return payload;
}

export const api = {
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),

  listUploads: (kind) => request(`/uploads${kind ? `?kind=${kind}` : ''}`),
  upload: (kind, file, onProgress) => upload(`/uploads/${kind}`, file, onProgress),
  deleteUpload: (id) => request(`/uploads/${id}`, { method: 'DELETE' }),

  table: () => request('/reports/table'),
  analytics: () => request('/reports/analytics'),
  exportBlob: () => request('/reports/export', { raw: true }),

  mapping: () => request('/mapping'),
  importMapping: (file, onProgress) => upload('/mapping/import', file, onProgress),
  addMappingRow: (row) => request('/mapping', { method: 'POST', body: row }),
  editMappingRow: (id, patch) => request(`/mapping/${id}`, { method: 'PATCH', body: patch }),
  deleteMappingRow: (id) => request(`/mapping/${id}`, { method: 'DELETE' }),

  items: () => request('/items'),
  importItems: (file, onProgress) => upload('/items/import', file, onProgress),
  createItem: (item) => request('/items', { method: 'POST', body: item }),
  updateItem: (id, patch) => request(`/items/${id}`, { method: 'PATCH', body: patch }),
  deleteItem: (id) => request(`/items/${id}`, { method: 'DELETE' }),
  uploadItemImage: (id, file, onProgress) => upload(`/items/${id}/image`, file, onProgress),

  users: () => request('/admin/users'),
  createUser: (payload) => request('/admin/users', { method: 'POST', body: payload }),
  setUserRole: (id, role) => request(`/admin/users/${id}/role`, { method: 'PATCH', body: { role } }),
  setUserPassword: (id, password) =>
    request(`/admin/users/${id}/password`, { method: 'PATCH', body: { password } }),
  deleteUser: (id) => request(`/admin/users/${id}`, { method: 'DELETE' }),
};
