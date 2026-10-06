import { api } from './api';

let _cache = null;
let _pending = null;

/** Fetch the PHC master list (with supervisors + CHWs per PHC).
 *  Cached for the lifetime of the page. The backend seeds on first read.
 */
export async function getPhcMeta() {
  if (_cache) return _cache;
  if (_pending) return _pending;
  _pending = api('/phc-meta')
    .then((r) => {
      _cache = (r && r.items) || [];
      return _cache;
    })
    .finally(() => {
      _pending = null;
    });
  return _pending;
}

/** Clear the cache after an admin edit. */
export function invalidatePhcMeta() {
  _cache = null;
}

/** Lookup helper: find one PHC entry by name (case-insensitive). */
export function findPhc(items, name) {
  if (!name) return null;
  const n = String(name).toLowerCase();
  return items.find((p) => String(p.name).toLowerCase() === n) || null;
}
