import { useEffect, useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import MeetingDetails from '../../components/MeetingDetails';
import { meetingPhase } from '../../lib/meetingPhase';

const STATUS_PILL = {
  scheduled: 'pill-brand',
  in_consult: 'pill-amber',
  completed: 'pill-green',
  cancelled: 'pill-red',
};

const svg = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

export default function MOAppointments() {
  const [list, setList] = useState([]);
  const [filter, setFilter] = useState('all');
  const [, setTick] = useState(0);
  useEffect(() => {
    api('/appointments/mine').then(setList).catch(() => setList([]));
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    const now = Date.now();
    return (list || []).filter((a) => {
      const t = new Date(a.scheduled_at).getTime();
      const { phase } = meetingPhase(a.scheduled_at, a.duration_minutes || 30);
      if (filter === 'today') {
        const d = new Date(a.scheduled_at);
        const today = new Date();
        return d.toDateString() === today.toDateString();
      }
      if (filter === 'upcoming') return t > now && phase !== 'expired';
      if (filter === 'past') return phase === 'expired';
      return true;
    });
  }, [list, filter]);

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">Tele-consults</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">My Appointments</h1>
          <p className="text-sm t-muted mt-1">Click "Start consult" to open Zoom as host.</p>
        </div>
        <div>
          <span className="pill-brand">{list.length} {list.length === 1 ? 'appointment' : 'appointments'}</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-5">
        {[
          { k: 'all', l: 'All' },
          { k: 'today', l: 'Today' },
          { k: 'upcoming', l: 'Upcoming' },
          { k: 'past', l: 'Past' },
        ].map((f) => (
          <button
            key={f.k}
            type="button"
            onClick={() => setFilter(f.k)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md border ${
              filter === f.k
                ? 'border-brand-600 text-brand-700 bg-brand-50'
                : 'border-[color:var(--border)] t-soft hover:border-[color:var(--border-strong)]'
            }`}
          >
            {f.l}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="card-elev text-center">
          <div className="t-soft text-sm font-medium">No appointments yet.</div>
          <div className="t-muted text-xs mt-1">Scheduled tele-consults will appear here.</div>
        </div>
      ) : (
        <div className="card-elev !p-0 overflow-hidden">
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="text-[11px] uppercase tracking-wider t-muted">
              <tr className="border-b border-[color:var(--border)]">
                <th className="text-left font-semibold px-4 py-2.5">Patient</th>
                <th className="text-left font-semibold px-4 py-2.5">Date / Time</th>
                <th className="text-left font-semibold px-4 py-2.5">Duration</th>
                <th className="text-left font-semibold px-4 py-2.5">Status</th>
                <th className="text-left font-semibold px-4 py-2.5">Meeting</th>
                <th className="text-right font-semibold px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => {
                const when = new Date(a.scheduled_at);
                const { phase, label } = meetingPhase(a.scheduled_at, a.duration_minutes || 30);
                const isActive = phase === 'active';
                const isExpired = phase === 'expired';
                const hostUrl = a.zoom_start_url || a.zoom_join_url;
                const hasUrl = Boolean(hostUrl);
                const canStart = isActive && hasUrl;

                const pillCls = isExpired ? 'pill-red' : isActive ? 'pill-amber' : STATUS_PILL[a.status] || 'pill-ink';
                const pillLabel = isExpired ? 'expired' : isActive ? 'live now' : (a.status || '').replace('_', ' ');

                return (
                  <tr key={a.id} className="border-b border-[color:var(--border)] last:border-0 hover:bg-[color:var(--surface-2)]">
                    <td className="px-4 py-3 t-ink font-medium">{a.patient_name}</td>
                    <td className="px-4 py-3 t-soft">
                      <div>{when.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', month: 'short', day: 'numeric' })}</div>
                      <div className="text-xs t-muted">{when.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit' })}</div>
                    </td>
                    <td className="px-4 py-3 t-soft">{a.duration_minutes}m</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <span className={pillCls}>{pillLabel}</span>
                        {label && (
                          <span className={`text-[11px] ${isExpired ? 'text-red-600 font-semibold' : isActive ? 'text-brand-700 font-semibold' : 't-muted'}`}>
                            {label}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {!isExpired && (a.zoom_meeting_id || a.zoom_join_url) ? (
                        <MeetingDetails
                          meetingId={a.zoom_meeting_id}
                          password={a.zoom_password}
                          joinUrl={a.zoom_join_url}
                          compact
                        />
                      ) : (
                        <span className="text-xs t-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {isExpired ? (
                          <Link
                            to={`/mo/case/${a.case_id}`}
                            className="btn-primary inline-flex items-center justify-center gap-2"
                          >
                            <svg {...svg} width="14" height="14"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                            Reschedule
                          </Link>
                        ) : (
                          <a
                            href={canStart ? hostUrl : undefined}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`btn-primary inline-flex items-center justify-center gap-2 ${
                              !canStart ? 'opacity-50 pointer-events-none' : ''
                            }`}
                            aria-disabled={!canStart}
                            title={!canStart && hasUrl ? 'Available 5 minutes before the scheduled time' : undefined}
                          >
                            <svg {...svg} width="14" height="14"><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
                            {isActive ? 'Start' : 'Start at slot'}
                          </a>
                        )}
                        <Link
                          to={`/mo/case/${a.case_id}`}
                          className="btn-ghost inline-flex items-center justify-center gap-1.5"
                          title="Open case file"
                        >
                          Case
                        </Link>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  );
}
