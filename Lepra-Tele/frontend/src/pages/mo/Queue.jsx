import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { formatId } from '../../lib/ids';
import { useTranslation } from '../../i18n/I18nContext';

const PILL = {
  rule_out: 'pill-green',
  alternative_dx: 'pill-amber',
  escalate: 'pill-red',
};

export default function Queue() {
  const { t } = useTranslation();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () =>
    api('/cases/queue')
      .then(setCases)
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const statusLabel = (s) => t('status.' + s, s.replace('_', ' '));

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">{t('role.mo')}</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">{t('queue.title')}</h1>
          <p className="text-sm t-muted mt-1">{t('queue.subtitle')}</p>
        </div>
        <div>
          <span className="pill-brand">
            {cases.length} {cases.length === 1 ? t('queue.case') : t('queue.cases')} · {t('queue.pending')}
          </span>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 animate-pulse">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="card h-24 border-[color:var(--border)]" />
          ))}
        </div>
      ) : cases.length === 0 ? (
        <div className="card-elev text-center">
          <div className="t-soft text-sm font-medium">{t('queue.empty')}</div>
          <div className="t-muted text-xs mt-1">{t('queue.empty_hint')}</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {cases.map((c) => (
            <Link
              to={`/mo/case/${c.id}`}
              key={c.id}
              className="card block border-[color:var(--border)] hover:border-[color:var(--border-strong)]"
            >
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="min-w-0">
                  <div className="font-semibold t-ink truncate">{c.patient_name}</div>
                  <div className="text-xs t-muted mt-0.5">{formatId(c.id)}</div>
                </div>
                <span className="pill-ink">{statusLabel(c.status)}</span>
              </div>

              {c.scheduled_at && (
                <div className="text-xs t-muted mb-2">
                  {t('queue.scheduled')} · {new Date(c.scheduled_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
