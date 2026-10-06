import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { formatId } from '../../lib/ids';
import { useAuth } from '../../context/AuthContext';

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export default function Metrics() {
  const { profile } = useAuth();
  const [m, setM] = useState(null);
  const [queue, setQueue] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    api('/admin/metrics').then(setM).catch((e) => setError(e?.message || 'Failed to load metrics'));
    api('/cases/queue').then((q) => setQueue(q || [])).catch(() => setQueue([]));
  }, []);

  const greeting = useGreeting();
  const displayName = profile?.profile?.name || profile?.email?.split('@')[0] || 'Admin';

  const recentEscalations = useMemo(
    () => queue.filter((c) => (c.triage_outcome || 'pending') === 'escalate').slice(0, 6),
    [queue],
  );

  const pendingImageCases = useMemo(
    () =>
      queue
        .filter((c) => Array.isArray(c.screening?.image_urls) && c.screening.image_urls.length > 0)
        .slice(0, 4),
    [queue],
  );

  const phcRows = useMemo(() => {
    const raw = (m && m.by_phc) || {};
    return Object.entries(raw)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);
  }, [m]);

  if (error) {
    return (
      <div className="card-elev border-l-[3px] border-l-red-500">
        <p className="font-semibold text-red-700 mb-1">Failed to load metrics</p>
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  if (!m) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-9 w-56 bg-[color:var(--surface-2)] rounded-xl" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-28 bg-[color:var(--surface-2)] rounded-xl border border-[color:var(--border)]" />
          ))}
        </div>
        <div className="h-64 bg-[color:var(--surface-2)] rounded-xl border border-[color:var(--border)]" />
        <div className="h-48 bg-[color:var(--surface-2)] rounded-xl border border-[color:var(--border)]" />
      </div>
    );
  }

  const total = m.total_cases || 0;
  const byOutcome = m.by_triage_outcome || {};
  const ruleOut = byOutcome.rule_out || 0;
  const altDx = byOutcome.alternative_dx || 0;
  const escalate = byOutcome.escalate || 0;
  const pending = byOutcome.pending || 0;
  const closedRemote = m.remote_closure_rate_pct || 0;

  const awaitingMO = queue.filter((c) => c.status === 'awaiting_mo').length;
  const scheduled = queue.filter((c) => c.status === 'scheduled').length;
  const inConsult = queue.filter((c) => c.status === 'in_consult').length;

  const totalImages = queue.reduce((n, c) => n + (c.screening?.image_urls?.length || 0), 0);
  const shownImages = pendingImageCases.reduce((n, c) => n + (c.screening?.image_urls?.length || 0), 0);
  const moreImages = Math.max(0, totalImages - shownImages);

  return (
    <div className="space-y-6">

      {/* ── Header ── */}
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <p className="section-title mb-1">Administrator</p>
          <h1 className="text-2xl font-bold tracking-tight t-ink">{greeting}, {displayName}</h1>
          <p className="text-sm t-muted mt-1">
            {new Date().toLocaleDateString('en-IN', {
              timeZone: 'Asia/Kolkata',
              weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
            })}
          </p>
        </div>
        <div className="sm:self-start">
          <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-[color:var(--border)] t-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Live
          </span>
        </div>
      </header>

      {/* ── KPI tiles ── */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          Icon={IcoUsers}
          label="Total cases"
          value={total}
          delta="All time"
          iconCls="bg-blue-50 text-blue-600"
          valCls="text-blue-700"
          borderCls="border-t-[3px] border-t-blue-500"
        />
        <KpiCard
          Icon={IcoAlert}
          label="Escalated"
          value={escalate}
          delta={escalate > 0 ? 'Needs MO review' : 'Queue clear'}
          iconCls={escalate > 0 ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'}
          valCls={escalate > 0 ? 'text-red-700' : 'text-emerald-700'}
          borderCls={escalate > 0 ? 'border-t-[3px] border-t-red-500' : 'border-t-[3px] border-t-emerald-500'}
        />
        <KpiCard
          Icon={IcoTrend}
          label="Referral rate"
          value={`${m.referral_rate_pct}%`}
          delta={m.referral_rate_pct > 25 ? 'Above target (≤25%)' : 'Within target (≤25%)'}
          iconCls={m.referral_rate_pct > 25 ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'}
          valCls={m.referral_rate_pct > 25 ? 'text-amber-700' : 'text-emerald-700'}
          borderCls={m.referral_rate_pct > 25 ? 'border-t-[3px] border-t-amber-500' : 'border-t-[3px] border-t-emerald-500'}
        />
        <KpiCard
          Icon={IcoHome}
          label="Closed remote"
          value={`${closedRemote}%`}
          delta="Resolved in community"
          iconCls="bg-[color:var(--brand-soft)] text-[color:var(--brand)]"
          valCls="text-[color:var(--brand-strong)]"
          borderCls="border-t-[3px] border-t-[color:var(--brand)]"
        />
      </section>

      {/* ── Triage overview + System health ── */}
      <section className="grid grid-cols-1 lg:grid-cols-5 gap-5">

        <div className="card-elev lg:col-span-3">
          <div className="flex items-baseline justify-between mb-5">
            <h2 className="text-base font-semibold t-ink">Triage overview</h2>
            <span className="text-xs t-muted">{total} total</span>
          </div>
          <div className="flex flex-col sm:flex-row items-center gap-8">
            <Donut
              total={total}
              segments={[
                { value: ruleOut,  color: '#059669' },
                { value: altDx,    color: '#f59e0b' },
                { value: escalate, color: '#ef4444' },
                { value: pending,  color: '#94a3b8' },
              ]}
            />
            <ul className="flex-1 w-full space-y-3.5">
              <LegendBar color="#059669" label="Rule out"       value={ruleOut}  total={total} />
              <LegendBar color="#f59e0b" label="Alternative dx" value={altDx}    total={total} />
              <LegendBar color="#ef4444" label="Escalate"       value={escalate} total={total} />
              {pending > 0 && (
                <LegendBar color="#94a3b8" label="Pending"      value={pending}  total={total} />
              )}
            </ul>
          </div>
        </div>

        <div className="card-elev lg:col-span-2 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold t-ink">System health</h2>
            <span className="pill-green flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Online
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            <StatBox label="Awaiting MO" value={awaitingMO}              warn={awaitingMO > 5} />
            <StatBox label="Scheduled"   value={scheduled} />
            <StatBox label="In consult"  value={inConsult}               ok={inConsult > 0} />
            <StatBox label="With images" value={pendingImageCases.length} />
          </div>
          <div className="mt-auto pt-4 border-t border-[color:var(--border)] mt-5">
            <p className="text-[10px] uppercase tracking-wider font-semibold t-muted mb-1.5">
              Total enrolled patients
            </p>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold t-ink">{m.total_patients || 0}</span>
              <span className="text-sm t-muted">
                across {phcRows.length} PHC{phcRows.length !== 1 ? 's' : ''}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ── PHC distribution ── */}
      <section className="card-elev">
        <div className="flex items-center gap-3 mb-5">
          <div className="p-2 rounded-xl bg-[color:var(--accent-soft)] text-[color:var(--accent)] shrink-0">
            <IcoPin size={15} />
          </div>
          <div>
            <h2 className="text-base font-semibold t-ink">Patients by PHC</h2>
            <p className="text-xs t-muted mt-0.5">
              {m.total_patients || 0} enrolled · {phcRows.length} facilit{phcRows.length !== 1 ? 'ies' : 'y'}
            </p>
          </div>
        </div>
        {phcRows.length === 0 ? (
          <EmptyState message="No patient data yet." hint="Enroll patients to see PHC distribution." />
        ) : (
          <PhcChart rows={phcRows} />
        )}
      </section>

      {/* ── Recent escalations ── */}
      <section className="card-elev !p-0 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[color:var(--border)]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-red-50 text-red-500 shrink-0">
              <IcoAlert size={14} />
            </div>
            <div>
              <h2 className="text-base font-semibold t-ink">Recent escalations</h2>
              <p className="text-xs t-muted">{recentEscalations.length} active</p>
            </div>
          </div>
          <Link to="/agent/patients" className="text-xs link flex items-center gap-0.5 shrink-0">
            View all <IcoChevronRight size={11} />
          </Link>
        </div>

        {recentEscalations.length === 0 ? (
          <EmptyState message="No active escalations." hint="Queue is clear." />
        ) : (
          <>
            {/* desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wider t-muted border-b border-[color:var(--border)]">
                    <th className="text-left font-semibold px-5 py-3">Patient</th>
                    <th className="text-left font-semibold px-4 py-3">Case ID</th>
                    <th className="text-left font-semibold px-4 py-3">Risk</th>
                    <th className="text-left font-semibold px-4 py-3">Triage signals</th>
                    <th className="text-right font-semibold px-5 py-3">Last update</th>
                  </tr>
                </thead>
                <tbody>
                  {recentEscalations.map((c) => (
                    <tr
                      key={c.id}
                      className="border-b border-[color:var(--border)] last:border-0 hover:bg-[color:var(--surface-2)] transition-colors duration-150"
                    >
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <PatientAvatar name={c.patient_name} />
                          <span className="font-medium t-ink">{c.patient_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <span className="font-mono text-xs t-soft">{formatId(c.id)}</span>
                      </td>
                      <td className="px-4 py-3.5">
                        <span className="pill-red">High</span>
                      </td>
                      <td className="px-4 py-3.5 max-w-[260px]">
                        <span className="text-xs t-soft truncate block">
                          {(c.triage?.reasons || []).slice(0, 2).join(' · ') || c.condition || '—'}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <span className="text-xs font-mono t-muted whitespace-nowrap">
                          {relTime(c.updated_at || c.created_at)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* mobile list */}
            <ul className="sm:hidden divide-y divide-[color:var(--border-cool)]">
              {recentEscalations.map((c) => (
                <li key={c.id} className="flex items-start gap-3 px-4 py-3.5">
                  <PatientAvatar name={c.patient_name} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-medium t-ink truncate">{c.patient_name}</span>
                      <span className="pill-red shrink-0 text-[10px] mt-0.5">High</span>
                    </div>
                    <div className="text-[11px] font-mono t-muted mt-0.5">{formatId(c.id)}</div>
                    <div className="text-xs t-soft mt-1 truncate">
                      {(c.triage?.reasons || []).slice(0, 1).join('') || c.condition || '—'}
                    </div>
                    <div className="text-[11px] t-muted mt-1">{relTime(c.updated_at || c.created_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* ── Pending image reviews ── */}
      <section className="card-elev">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-[color:var(--accent-soft)] text-[color:var(--accent)] shrink-0">
              <IcoImage size={14} />
            </div>
            <h2 className="text-base font-semibold t-ink">Pending image reviews</h2>
          </div>
          <Link to="/mo" className="text-xs link flex items-center gap-0.5 shrink-0">
            View all <IcoChevronRight size={11} />
          </Link>
        </div>

        {pendingImageCases.length === 0 ? (
          <EmptyState message="No pending image reviews." hint="All images have been reviewed." />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {pendingImageCases.slice(0, 3).map((c) => (
              <Link
                key={c.id}
                to={`/mo/case/${c.id}`}
                className="group relative aspect-square rounded-xl overflow-hidden border border-[color:var(--border)] hover:border-[color:var(--brand)] transition-all duration-200"
                title={c.patient_name}
              >
                <img
                  src={c.screening.image_urls[0]}
                  alt={c.patient_name}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
                <div className="absolute bottom-0 inset-x-0 p-2.5">
                  <div className="text-[11px] text-white font-semibold truncate">{c.patient_name}</div>
                </div>
              </Link>
            ))}
            {moreImages > 0 && (
              <Link
                to="/mo"
                className="aspect-square rounded-xl border-2 border-dashed border-[color:var(--border)] hover:border-[color:var(--brand)] flex flex-col items-center justify-center gap-1.5 transition-colors duration-200 group"
              >
                <span className="text-2xl font-bold t-soft group-hover:text-[color:var(--brand)] transition-colors">+{moreImages}</span>
                <span className="text-[11px] t-muted">more images</span>
              </Link>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function KpiCard({ Icon, label, value, delta, iconCls, valCls, borderCls }) {
  return (
    <div className={`card-elev ${borderCls}`}>
      <div className={`inline-flex items-center justify-center w-9 h-9 rounded-xl mb-3 ${iconCls}`}>
        <Icon size={16} />
      </div>
      <div className={`text-3xl font-bold tracking-tight leading-none ${valCls}`}>{value}</div>
      <div className="text-[11px] uppercase tracking-wide font-semibold t-muted mt-2">{label}</div>
      {delta && <div className="text-xs t-muted mt-1.5">{delta}</div>}
    </div>
  );
}

function Donut({ segments, total }) {
  const size = 190;
  const stroke = 22;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const sum = segments.reduce((s, x) => s + x.value, 0) || 1;
  let offset = 0;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border-cool)" strokeWidth={stroke} />
        {segments.map((seg, i) => {
          if (!seg.value) return null;
          const gap = c * 0.012;
          const len = Math.max(0, (seg.value / sum) * c - gap);
          const el = (
            <circle
              key={i}
              cx={size / 2} cy={size / 2} r={r}
              fill="none"
              stroke={seg.color}
              strokeWidth={stroke}
              strokeDasharray={`${len} ${c}`}
              strokeDashoffset={-offset}
              strokeLinecap="butt"
            />
          );
          offset += (seg.value / sum) * c;
          return el;
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <span className="text-3xl font-bold t-ink leading-none">{total}</span>
        <span className="text-[10px] uppercase tracking-widest t-muted mt-1 font-semibold">Cases</span>
      </div>
    </div>
  );
}

function LegendBar({ color, label, value, total }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <li>
      <div className="flex items-center justify-between mb-1.5 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: color }} />
          <span className="font-medium t-ink">{label}</span>
        </div>
        <div className="font-semibold t-ink shrink-0 ml-4">
          {value} <span className="t-muted font-normal">({pct}%)</span>
        </div>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden bg-[color:var(--surface-2)]">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </li>
  );
}

function StatBox({ label, value, warn = false, ok = false }) {
  const accent = warn ? '#f59e0b' : ok ? '#059669' : 'var(--brand)';
  return (
    <div className="rounded-xl neu-inset px-3.5 py-3 border-l-[3px]" style={{ borderLeftColor: accent }}>
      <div className="text-[10px] uppercase tracking-wider t-muted font-semibold leading-tight">{label}</div>
      <div className="text-2xl font-bold t-ink mt-1 leading-none">{value}</div>
    </div>
  );
}

const PHC_COLORS = [
  { bar: '#0f766e', bg: 'rgba(15,118,110,0.10)' },
  { bar: '#0891b2', bg: 'rgba(8,145,178,0.10)' },
  { bar: '#7c3aed', bg: 'rgba(124,58,237,0.10)' },
  { bar: '#db2777', bg: 'rgba(219,39,119,0.10)' },
  { bar: '#d97706', bg: 'rgba(217,119,6,0.10)' },
  { bar: '#16a34a', bg: 'rgba(22,163,74,0.10)' },
  { bar: '#dc2626', bg: 'rgba(220,38,38,0.10)' },
];

function PhcChart({ rows }) {
  const max = rows[0]?.count || 1;
  const grandTotal = rows.reduce((s, r) => s + r.count, 0) || 1;
  return (
    <div className="space-y-4">
      {rows.map(({ name, count }, i) => {
        const { bar, bg } = PHC_COLORS[i % PHC_COLORS.length];
        const widthPct = (count / max) * 100;
        const sharePct = Math.round((count / grandTotal) * 100);
        return (
          <div key={name}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: bar }} />
              <span className="text-sm font-medium t-ink flex-1 truncate min-w-0" title={name}>{name}</span>
              <span className="text-xs font-bold shrink-0" style={{ color: bar }}>{count}</span>
              <span className="text-xs t-muted w-8 text-right shrink-0">{sharePct}%</span>
            </div>
            <div className="h-6 rounded-lg overflow-hidden ml-[22px]" style={{ background: bg }}>
              <div
                className="h-full rounded-lg"
                style={{ width: `${widthPct}%`, background: bar, opacity: 0.75 }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const AVATAR_PALETTE = [
  'bg-blue-100 text-blue-800',
  'bg-violet-100 text-violet-800',
  'bg-emerald-100 text-emerald-800',
  'bg-amber-100 text-amber-800',
  'bg-rose-100 text-rose-800',
  'bg-cyan-100 text-cyan-800',
];

function PatientAvatar({ name }) {
  const idx = name ? (name.charCodeAt(0) + (name.charCodeAt(1) || 0)) % AVATAR_PALETTE.length : 0;
  const init = (name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('');
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${AVATAR_PALETTE[idx]}`}>
      {init}
    </div>
  );
}

function EmptyState({ message, hint }) {
  return (
    <div className="py-10 text-center">
      <div className="text-sm font-medium t-soft">{message}</div>
      {hint && <div className="text-xs t-muted mt-1">{hint}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Icon components
// ─────────────────────────────────────────────────────────────────────────────

const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

function IcoUsers({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function IcoAlert({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function IcoTrend({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );
}

function IcoHome({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

function IcoPin({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function IcoImage({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  );
}

function IcoChevronRight({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" {...S}>
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Hooks + pure helpers
// ─────────────────────────────────────────────────────────────────────────────

function useGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function relTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' });
}
