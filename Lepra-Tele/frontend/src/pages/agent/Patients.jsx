import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, downloadAuthFile } from '../../lib/api';
import { formatId } from '../../lib/ids';
import { useTranslation } from '../../i18n/I18nContext';

const svg = { fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

const STATUS_KEYS = {
  rule_out: { labelKey: 'pstatus.not_affected', pillCls: 'pill-green' },
  alternative_dx: { labelKey: 'pstatus.alt_dx', pillCls: 'pill-amber' },
  escalate: { labelKey: 'pstatus.affected_mo', pillCls: 'pill-red' },
};

const PENDING_META = { labelKey: 'pstatus.pending', pillCls: 'pill-ink' };
const NOT_SCREENED_META = { labelKey: 'pstatus.not_screened', pillCls: 'pill-ink' };

function statusFor(p) {
  const c = p.latest_case;
  if (!c) return NOT_SCREENED_META;
  if (c.triage_outcome && STATUS_KEYS[c.triage_outcome]) return STATUS_KEYS[c.triage_outcome];
  return PENDING_META;
}

function reasonFor(p) {
  const c = p.latest_case;
  if (!c) return null;
  if (Array.isArray(c.reason) && c.reason.length) return c.reason.join(' · ');
  if (c.condition) return c.condition;
  return null;
}

export default function Patients() {
  const { t } = useTranslation();
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(true);
      api(query ? `/patients?q=${encodeURIComponent(query)}` : '/patients')
        .then((res) => setPatients(res || []))
        .catch(console.error)
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const handleBulkDownload = () => {
    const url = query ? `/patients/export/excel?q=${encodeURIComponent(query)}` : `/patients/export/excel`;
    downloadAuthFile(url, 'patients_export.csv');
  };

  const handleSingleDownload = (patientId) => {
    downloadAuthFile(`/patients/export/excel?patient_id=${patientId}`, `patient_${patientId}.csv`);
  };

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
        <div>
          <div className="section-title">Directory</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">{t('nav.patients')}</h1>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <svg {...svg} width="16" height="16" className="absolute left-3 top-1/2 -translate-y-1/2 text-[color:var(--text-muted)]">
              <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
            </svg>
            <input
              type="text"
              placeholder={t('search_placeholder', 'Search patients...')}
              className="neu-input w-full pl-9"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button onClick={handleBulkDownload} className="btn-ghost shrink-0 !px-3" title="Download Excel">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span className="ml-2 hidden sm:inline">Export</span>
          </button>
        </div>
      </div>

      {/* Main list */}
      {loading ? (
        <div className="card-elev !p-0 overflow-hidden">
          <ul className="divide-y divide-[color:var(--border-cool)] animate-pulse">
            {[...Array(5)].map((_, i) => (
              <li key={i} className="p-4 sm:p-5">
                <div className="h-4 w-40 bg-[color:var(--surface-2)] rounded-md mb-2" />
                <div className="h-3 w-56 bg-[color:var(--surface-2)] rounded-md" />
              </li>
            ))}
          </ul>
        </div>
      ) : patients.length === 0 ? (
        <EmptyState query={query} t={t} />
      ) : (
        <>
          <div className="text-[11px] uppercase tracking-wider font-semibold t-muted mb-3 px-1">
            {patients.length} {patients.length === 1 ? 'Patient' : 'Patients'}
          </div>
          <div className="card-elev !p-0 overflow-hidden">
            <ul className="divide-y divide-[color:var(--border-cool)]">
              {patients.map((p) => {
                const meta = statusFor(p);
                const reason = reasonFor(p);
                return (
                  <li key={p.id} className="relative group hover:bg-[color:var(--surface-2)] transition-colors">
                    <Link to={`/patients/${p.id}`} className="block p-4 sm:p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2.5 mb-1 flex-wrap">
                            <span className="text-base font-semibold t-ink truncate">{p.name}</span>
                            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border border-transparent ${meta.pillCls}`}>
                              {t(meta.labelKey)}
                            </span>
                          </div>
                          <div className="text-xs t-muted flex items-center gap-1.5 flex-wrap">
                            <span className="font-mono text-[10px] tracking-wide">{formatId(p.id)}</span>
                            <span>·</span>
                            {p.age ?? '—'}
                            {p.phone && <span> · {p.phone}</span>}
                            {p.location && <span> · {p.location}</span>}
                          </div>
                          {reason && (
                            <div className="text-[11px] t-soft truncate mt-0.5">{reason}</div>
                          )}
                        </div>
                        
                        <div className="flex items-center gap-2">
                          <button
                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleSingleDownload(p.id); }}
                            className="opacity-0 group-hover:opacity-100 btn-ghost !p-1.5"
                            title="Download Data"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                          </button>
                          <svg {...svg} width="14" height="14" className="t-muted shrink-0 mt-1"><path d="M9 18l6-6-6-6" /></svg>
                        </div>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function EmptyState({ query, t }) {
  return (
    <div className="card-elev text-center">
      <div className="w-12 h-12 rounded-md bg-brand-50 grid place-items-center mx-auto mb-3 text-brand-700">
        <svg {...svg} width="22" height="22">
          {query ? (
            <><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></>
          ) : (
            <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /></>
          )}
        </svg>
      </div>
      <h3 className="text-[15px] font-semibold t-ink">
        {query ? t('no_results_found', 'No results found') : t('no_patients_yet', 'No patients yet')}
      </h3>
      <p className="text-sm t-muted mt-1 max-w-sm mx-auto">
        {query ? 'Try adjusting your search terms.' : 'Records synced by field agents will appear here.'}
      </p>
    </div>
  );
}