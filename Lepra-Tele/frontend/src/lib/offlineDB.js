/**
 * IndexedDB persistence for the offline-write queue.
 *
 * Two stores:
 *   - intake_bundles: a complete agent intake (patient + history + screening + images-as-blobs)
 *                     queued atomically; sync replays the whole bundle sequentially.
 *   - sync_log     : append-only diagnostics so we can show retry history in the UI.
 */
import { openDB } from 'idb';

const DB_NAME = 'lepra-offline';
const DB_VERSION = 1;

let _dbPromise = null;

export function getDB() {
  if (!_dbPromise) {
    _dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('intake_bundles')) {
          const store = db.createObjectStore('intake_bundles', { keyPath: 'id' });
          store.createIndex('by_status', 'status');
          store.createIndex('by_created', 'created_at');
        }
        if (!db.objectStoreNames.contains('sync_log')) {
          db.createObjectStore('sync_log', { keyPath: 'id', autoIncrement: true });
        }
      },
      // Another tab is trying to open the DB with a higher version and this
      // connection is in the way. Close it (and drop the cache) so the upgrade
      // can proceed; the next getDB() call reopens against the new version.
      blocking() {
        if (_dbPromise) {
          _dbPromise.then((db) => db.close()).catch(() => {});
          _dbPromise = null;
        }
      },
      // The connection was closed unexpectedly (bfcache restore, browser
      // reclaiming an idle handle, abnormal termination). Drop the stale
      // promise so the next call reopens instead of reusing a dead connection.
      terminated() {
        _dbPromise = null;
      },
    });
  }
  return _dbPromise;
}

/**
 * Run a DB operation, transparently reopening once if the connection was
 * closing/closed underneath us. Guards every store helper below so callers
 * never see "The database connection is closing."
 */
async function withDB(fn) {
  try {
    return await fn(await getDB());
  } catch (err) {
    if (isConnectionClosingError(err)) {
      _dbPromise = null;
      return fn(await getDB());
    }
    throw err;
  }
}

function isConnectionClosingError(err) {
  const msg = String((err && err.message) || err || '');
  return (
    msg.includes('connection is closing') ||
    msg.includes('database connection is closing') ||
    (err && err.name === 'InvalidStateError')
  );
}

/**
 * Ask the browser to make this origin's storage persistent, so queued intakes
 * are never silently evicted under disk pressure. Best-effort: the browser may
 * grant or deny it. Returns the resulting persisted state (or null if the API
 * is unavailable).
 */
export async function ensurePersistentStorage() {
  try {
    if (!navigator.storage || !navigator.storage.persist) return null;
    if (await navigator.storage.persisted()) return true;
    return await navigator.storage.persist();
  } catch {
    return null;
  }
}

/** Current storage usage/quota estimate (bytes), for surfacing in the UI. */
export async function getStorageEstimate() {
  try {
    if (!navigator.storage || !navigator.storage.estimate) return null;
    return await navigator.storage.estimate();
  } catch {
    return null;
  }
}

// ---------- Intake bundles ----------
export async function saveIntakeBundle(bundle) {
  await withDB((db) => db.put('intake_bundles', bundle));
  return bundle.id;
}

export async function getIntakeBundle(id) {
  return withDB((db) => db.get('intake_bundles', id));
}

export async function listPendingBundles() {
  const all = await withDB((db) => db.getAll('intake_bundles'));
  return all
    .filter((b) => b.status !== 'synced')
    .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
}

export async function listAllBundles() {
  const all = await withDB((db) => db.getAll('intake_bundles'));
  return all.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
}

export async function deleteBundle(id) {
  await withDB((db) => db.delete('intake_bundles', id));
}

export async function updateBundleStatus(id, patch) {
  await withDB(async (db) => {
    const current = await db.get('intake_bundles', id);
    if (!current) return;
    await db.put('intake_bundles', { ...current, ...patch });
  });
}

// ---------- Sync log ----------
export async function logSyncEvent(event) {
  await withDB(async (db) => {
    await db.add('sync_log', { ...event, at: Date.now() });
    // Cap the log so it doesn't grow forever.
    const all = await db.getAll('sync_log');
    if (all.length > 200) {
      const drop = all.slice(0, all.length - 200);
      const tx = db.transaction('sync_log', 'readwrite');
      for (const e of drop) await tx.store.delete(e.id);
      await tx.done;
    }
  });
}
