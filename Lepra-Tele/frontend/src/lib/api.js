import { auth } from './firebase';

const BASE = import.meta.env.VITE_API_BASE || '/api';

/** Thrown by api() when the device is offline so callers can fork on it
 *  (e.g. enqueue the request to IndexedDB instead of failing the form). */
export class OfflineError extends Error {
  constructor(message = 'Offline — request not sent') {
    super(message);
    this.name = 'OfflineError';
    this.offline = true;
  }
}

async function authHeaders() {
  const user = auth.currentUser;
  if (!user) return {};
  const token = await user.getIdToken();
  return { Authorization: `Bearer ${token}` };
}

function isWriteMethod(method = 'GET') {
  const m = method.toUpperCase();
  return m === 'POST' || m === 'PUT' || m === 'PATCH' || m === 'DELETE';
}

export async function api(path, opts = {}) {
  // Short-circuit writes when offline so callers can choose to enqueue.
  if (typeof navigator !== 'undefined' && navigator.onLine === false && isWriteMethod(opts.method)) {
    throw new OfflineError();
  }
  const headers = {
    'Content-Type': 'application/json',
    ...(await authHeaders()),
    ...(opts.headers || {}),
  };
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...opts, headers });
  } catch (err) {
    // Network-level failure (DNS, timeout, dropped connection). For writes,
    // surface as an OfflineError so callers can route to the offline queue.
    if (isWriteMethod(opts.method)) throw new OfflineError(err.message || String(err));
    throw err;
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

/** Fetch a binary file (PDF) from an authenticated endpoint and trigger a
 *  browser download. Returns the blob so callers can also inline-open it. */
export async function downloadAuthFile(path, filename) {
  const res = await fetch(`${BASE}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return blob;
}

/** Multipart upload of an arbitrary file/blob to an authenticated endpoint. */
export async function uploadFile(path, file, filename) {
  const fd = new FormData();
  fd.append('file', file, filename || file.name || 'upload');
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: await authHeaders(),
    body: fd,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function uploadImage(file) {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new OfflineError('Offline — image upload deferred');
  }
  const fd = new FormData();
  fd.append('file', file);
  let res;
  try {
    res = await fetch(`${BASE}/uploads/image`, {
      method: 'POST',
      headers: await authHeaders(),
      body: fd,
    });
  } catch (err) {
    throw new OfflineError(err.message || String(err));
  }
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}
