import { useEffect, useState } from 'react';
import { listAllBundles } from './offlineDB';
import { drainQueue, isSyncing, onSyncChange } from './syncEngine';

/** Returns true when navigator.onLine is true. Tracks online/offline events. */
export function useOnlineStatus() {
  const [online, setOnline] = useState(
    typeof navigator !== 'undefined' ? navigator.onLine : true,
  );
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);
  return online;
}

/** Returns { pending, syncing, retry } — for the OfflineBanner.
 *  Re-queries IndexedDB whenever the sync engine emits a state change. */
export function useSyncState() {
  const [pending, setPending] = useState([]);
  const [syncing, setSyncing] = useState(isSyncing());

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      const all = await listAllBundles();
      if (!alive) return;
      setPending(all.filter((b) => b.status !== 'synced'));
      setSyncing(isSyncing());
    };
    refresh();
    const off = onSyncChange(refresh);
    return () => { alive = false; off(); };
  }, []);

  return { pending, syncing, retry: drainQueue };
}
