import { useOnlineStatus, useSyncState } from '../lib/onlineStatus';

/** Slim banner at the top of every page. Hides itself when online and the
 *  queue is empty. When offline OR when there are pending uploads, surfaces
 *  status + a manual "Retry" action.
 */
export default function OfflineBanner() {
  const online = useOnlineStatus();
  const { pending, syncing, retry } = useSyncState();
  const pendingCount = pending.length;
  const hasErrors = pending.some((b) => b.status === 'error');

  if (online && pendingCount === 0) return null;

  let bg, fg, label;
  if (!online) {
    bg = 'bg-amber-50 dark:bg-amber-900/30 border-amber-300 dark:border-amber-800';
    fg = 'text-amber-900 dark:text-amber-100';
    label = `Offline${pendingCount ? ` — ${pendingCount} intake${pendingCount === 1 ? '' : 's'} waiting to upload` : ''}`;
  } else if (hasErrors) {
    bg = 'bg-red-50 dark:bg-red-900/30 border-red-300 dark:border-red-800';
    fg = 'text-red-900 dark:text-red-100';
    label = `${pendingCount} intake${pendingCount === 1 ? '' : 's'} couldn't sync — tap retry`;
  } else if (syncing) {
    bg = 'bg-brand-50 dark:bg-brand-900/30 border-brand-300 dark:border-brand-800';
    fg = 'text-brand-800 dark:text-brand-100';
    label = `Uploading ${pendingCount} queued intake${pendingCount === 1 ? '' : 's'}…`;
  } else {
    bg = 'bg-brand-50 dark:bg-brand-900/30 border-brand-300 dark:border-brand-800';
    fg = 'text-brand-800 dark:text-brand-100';
    label = `${pendingCount} intake${pendingCount === 1 ? '' : 's'} queued for upload`;
  }

  return (
    <div className={`${bg} border-b`}>
      <div className="max-w-[1600px] mx-auto px-3 sm:px-4 md:px-8 py-2 flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-2 text-xs font-medium ${fg}`}>
          <span
            className={`w-2 h-2 rounded-full ${
              !online ? 'bg-amber-500' : hasErrors ? 'bg-red-500' : syncing ? 'bg-brand-500 animate-pulse' : 'bg-brand-500'
            }`}
          />
          {label}
        </span>
        {online && pendingCount > 0 && !syncing && (
          <button
            type="button"
            onClick={retry}
            className={`text-xs underline ${fg} ml-auto`}
          >
            Retry now
          </button>
        )}
      </div>
    </div>
  );
}
