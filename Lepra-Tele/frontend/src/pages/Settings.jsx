import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from '../i18n/I18nContext';

export default function Settings() {
  const { profile } = useAuth();
  const { t, lang, setLang, languages } = useTranslation();

  const initialName = profile?.profile?.name || '';
  const initialPhone = profile?.profile?.phone || '';
  const [name, setName] = useState(initialName);
  const [phone, setPhone] = useState(initialPhone);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setName(initialName);
    setPhone(initialPhone);
  }, [initialName, initialPhone]);

  const saveProfile = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const phoneDigits = (phone || '').replace(/\D/g, '');
    if (phoneDigits && phoneDigits.length !== 10) {
      setError('Phone must be exactly 10 digits.');
      setBusy(false);
      return;
    }
    try {
      await api('/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ name, phone: phoneDigits }),
      });
      setNotice(t('settings.profile_saved'));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const displayName = profile?.profile?.name || profile?.email || 'User';
  const role = profile?.role || 'agent';

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
        <div>
          <div className="section-title">{t('role.' + role)}</div>
          <h1 className="text-2xl font-semibold tracking-tight t-ink">{t('nav.settings')}</h1>
          <p className="text-sm t-muted mt-1">{t('settings.manage')}</p>
        </div>
        {notice && (
          <div className="pill-green">{notice}</div>
        )}
      </div>

      <div className="space-y-5">
        {/* Profile */}
        <section className="card-elev">
          <div className="mb-4">
            <h2 className="text-base font-semibold t-ink">{t('settings.tab.profile')}</h2>
            <p className="text-xs t-muted mt-0.5">{t('settings.tab.profile_desc')}</p>
          </div>

          <form onSubmit={saveProfile}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label={t('common.name')}>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
              </Field>
              <Field label={t('common.phone')}>
                <input
                  className="input"
                  inputMode="numeric"
                  maxLength={10}
                  value={phone}
                  onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
                  placeholder="10-digit mobile number"
                />
              </Field>
              <Field label={t('common.email')}>
                <input className="input opacity-60 cursor-not-allowed" value={profile?.email || ''} readOnly />
              </Field>
              <Field label={t('common.role')}>
                <input className="input opacity-60 cursor-not-allowed uppercase tracking-wider" value={role} readOnly />
              </Field>
            </div>

            {error && (
              <div className="mt-4 text-sm text-red-700 border border-red-200 bg-red-50 rounded-md px-4 py-2.5">
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={() => { setName(initialName); setPhone(initialPhone); }}
                className="btn-ghost"
              >
                {t('common.reset')}
              </button>
              <button className="btn-primary px-5" disabled={busy}>
                {busy ? t('common.please_wait') : t('settings.save_profile')}
              </button>
            </div>
          </form>
        </section>

        {/* Account */}
        <section className="card-elev">
          <div className="mb-4">
            <h2 className="text-base font-semibold t-ink">{t('common.role')}</h2>
            <p className="text-xs t-muted mt-0.5">{displayName}</p>
          </div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div className="neu-inset rounded-md px-3 py-2.5">
              <dt className="text-[10px] uppercase tracking-wider t-muted font-semibold">{t('common.email')}</dt>
              <dd className="t-ink mt-0.5 font-mono text-xs break-all">{profile?.email || '—'}</dd>
            </div>
            <div className="neu-inset rounded-md px-3 py-2.5">
              <dt className="text-[10px] uppercase tracking-wider t-muted font-semibold">{t('common.role')}</dt>
              <dd className="t-ink mt-0.5 uppercase tracking-wider text-xs">{role}</dd>
            </div>
          </dl>
        </section>

        {/* Language */}
        <section className="card-elev">
          <div className="mb-4">
            <h2 className="text-base font-semibold t-ink">{t('settings.tab.language')}</h2>
            <p className="text-xs t-muted mt-0.5">{t('settings.language_desc')}</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2.5">
            {languages.map((l) => {
              const selected = lang === l.code;
              return (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setLang(l.code)}
                  lang={l.code}
                  className={`rounded-md p-3 text-left border ${
                    selected
                      ? 'border-brand-700 bg-brand-50'
                      : 'border-[color:var(--border)] hover:border-[color:var(--border-strong)]'
                  }`}
                >
                  <div className={`text-sm font-medium leading-tight ${selected ? 'text-brand-700' : 't-ink'}`}>{l.native}</div>
                  <div className={`text-[10px] mt-0.5 ${selected ? 'text-brand-700' : 't-muted'}`}>{l.label}</div>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider t-muted font-semibold mb-1.5">{label}</label>
      {children}
    </div>
  );
}
