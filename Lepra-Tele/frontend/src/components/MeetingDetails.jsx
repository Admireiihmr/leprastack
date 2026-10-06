import { useState } from 'react';

const svg = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

/** Small reusable card that shows Zoom meeting credentials with copy buttons.
 *  Usage: <MeetingDetails meetingId={...} password={...} joinUrl={...} compact />
 */
export default function MeetingDetails({ meetingId, password, joinUrl, compact = false }) {
  if (!meetingId && !password && !joinUrl) return null;

  return (
    <div className={`rounded-xl neu-inset ${compact ? 'px-3 py-2.5' : 'px-4 py-3'} space-y-2`}>
      <div className="text-[10px] uppercase tracking-wider t-muted font-bold">Meeting details</div>
      {meetingId && (
        <CopyRow label="Meeting ID" value={meetingId} mono />
      )}
      {password && (
        <CopyRow label="Password" value={password} mono highlight />
      )}
      {joinUrl && (
        <CopyRow label="Link" value={joinUrl} truncate />
      )}
    </div>
  );
}

function CopyRow({ label, value, mono = false, truncate = false, highlight = false }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Older browsers / non-https: fall back to select + execCommand
      try {
        const ta = document.createElement('textarea');
        ta.value = value;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      } catch {}
    }
  };

  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-[10px] font-bold uppercase tracking-wider t-muted w-16 shrink-0">{label}</span>
      <span
        className={`flex-1 text-xs min-w-0 ${truncate ? 'truncate' : ''} ${mono ? 'font-mono' : ''} ${
          highlight ? 'font-bold t-ink bg-emerald-50 dark:bg-emerald-900/30 rounded px-2 py-0.5' : 't-soft'
        }`}
      >
        {value}
      </span>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/30 transition"
        title="Copy"
        aria-label={`Copy ${label}`}
      >
        {copied ? (
          <svg {...svg} width="14" height="14"><path d="M20 6L9 17l-5-5" /></svg>
        ) : (
          <svg {...svg} width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
        )}
      </button>
    </div>
  );
}
