import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
} from 'firebase/auth';
import { auth } from '../lib/firebase';
import { api } from '../lib/api';
import { useTranslation } from '../i18n/I18nContext';
import Banner from '../components/Banner';
import PartnerLogos from '../components/PartnerLogos';
import { assetUrl } from '../utils/assetUrl';

const FEATURES = [
  { icon: 'cpu', key: 'login.feature.triage' },
  { icon: 'shield', key: 'login.feature.audit' },
  { icon: 'wifi', key: 'login.feature.recall' },
  { icon: 'globe', key: 'login.feature.scheduling' },
  { icon: 'doc', key: 'login.feature.repo' },
];

const PASSWORD_RE = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-\[\];/\\`~+=]).{6,}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Login() {
  const { t, lang, setLang, languages } = useTranslation();
  const nav = useNavigate();
  const [selectedRole, setSelectedRole] = useState('agent');

  const ROLES = [
    { role: 'agent', color: 'var(--brand)', title: t('login.card.agent.title'), short: t('login.card.agent.short'), icon: <AgentIcon />, loginOnly: false },
    { role: 'mo', color: 'var(--accent)', title: t('login.card.mo.title'), short: t('login.card.mo.short'), icon: <MOIcon />, loginOnly: false },
    { role: 'admin', color: '#4f46e5', title: t('login.card.admin.title'), short: t('login.card.admin.short'), icon: <AdminIcon />, loginOnly: true },
  ];

  const currentRole = ROLES.find((r) => r.role === selectedRole);

  return (
    <div
      className="min-h-screen flex flex-col overflow-x-hidden relative bg-[color:var(--bg)] lg:bg-[image:var(--login-bg-image)] lg:bg-cover lg:bg-[position:center_right] lg:bg-no-repeat"
      style={{ '--login-bg-image': `url(${assetUrl('login-bg.jpg')})` }}
    >
      <div className="absolute inset-0 bg-white/55 pointer-events-none hidden lg:block" aria-hidden />

      {/* Header */}
      <header className="sticky top-0 z-30 border-b border-white/40 bg-white/70 backdrop-blur-md">
        <div className="w-full px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <a
              href="/"
              title={t('common.back_to_portal')}
              aria-label={t('common.back_to_portal')}
              className="inline-flex items-center justify-center w-8 h-8 rounded-full border border-[color:var(--border)] t-muted hover:t-ink hover:border-[color:var(--border-strong)] transition-colors duration-150 shrink-0"
            >
              <BackArrow />
            </a>
            <span className="w-px h-6 bg-[color:var(--border)] shrink-0" aria-hidden />
            <span className="brand-mark"><Logo /></span>
            <div className="leading-tight">
              <div className="font-bold tracking-wide text-sm t-ink">TELE-LEPROSY</div>
              <div className="text-[9px] uppercase tracking-[0.16em] t-muted">{t('brand.subtitle')}</div>
            </div>
          </div>
          <LanguagePicker lang={lang} setLang={setLang} languages={languages} />
        </div>
      </header>

      {/* Main */}
      <main className="relative z-10 flex-1 w-full px-4 sm:px-6 lg:px-10 pt-0 pb-8 lg:pt-10 lg:pb-12 flex items-start justify-center">
        <div className="w-full max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-[1fr_480px] gap-8 lg:gap-16 items-start">

          {/* Left: Hero */}
          <div className="hidden lg:flex flex-col">
            <h1 className="text-4xl xl:text-5xl font-extrabold tracking-tight t-ink leading-[1.15]">
              {t('login.hero_title')}
            </h1>
            <p className="mt-4 text-base t-muted leading-relaxed">
              {t('login.hero_subtitle')}
            </p>
            <div className="mt-8 grid grid-cols-2 xl:grid-cols-3 gap-3">
              {FEATURES.map((f) => (
                <div
                  key={f.key}
                  className="flex items-center gap-2.5 p-3 rounded-xl bg-white/65 backdrop-blur-sm border border-white/70 shadow-card"
                >
                  <span className="text-[color:var(--brand)] shrink-0"><FeatureIcon name={f.icon} /></span>
                  <span className="text-xs font-medium t-soft leading-tight">{t(f.key)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Auth card */}
          <div className="w-full max-w-md mx-auto lg:mx-0">
            {/* Mobile app-style hero — full-bleed gradient panel, logo + headline
                overlaid directly on it, card pulled up to overlap the bottom edge. */}
            <div className="lg:hidden -mx-4 sm:-mx-6">
              <div
                className="relative pt-7 pb-14 px-6 rounded-b-[2.5rem] overflow-hidden"
                style={{ background: 'linear-gradient(160deg, var(--brand) 0%, var(--accent) 100%)' }}
              >
                <div className="absolute -top-12 -right-10 w-48 h-48 rounded-full bg-white/10 blur-2xl" />
                <div className="absolute -bottom-16 -left-12 w-56 h-56 rounded-full bg-white/10 blur-2xl" />
                <svg className="absolute inset-0 w-full h-full opacity-[0.12]" preserveAspectRatio="none">
                  <defs>
                    <pattern id="tele-dots" width="22" height="22" patternUnits="userSpaceOnUse">
                      <circle cx="2" cy="2" r="1.6" fill="#fff" />
                    </pattern>
                  </defs>
                  <rect width="100%" height="100%" fill="url(#tele-dots)" />
                </svg>

                <div className="relative z-10 flex items-center gap-2.5">
                  <span className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-white/15 border border-white/25 text-white shrink-0">
                    <Logo size={18} />
                  </span>
                  <div className="leading-tight text-white">
                    <div className="font-bold tracking-wide text-sm">TELE-LEPROSY</div>
                    <div className="text-[9px] uppercase tracking-[0.16em] text-white/70">{t('brand.subtitle')}</div>
                  </div>
                </div>

                <h1 className="relative z-10 mt-7 text-[26px] font-extrabold tracking-tight text-white leading-[1.2]">
                  {t('login.hero_title')}
                </h1>
                <p className="relative z-10 mt-2 text-sm text-white/80 leading-relaxed max-w-xs">
                  {t('login.hero_subtitle')}
                </p>
              </div>
            </div>

            <div className="-mt-8 lg:mt-0 relative z-10">
              <AuthCard
                roles={ROLES}
                selectedRole={selectedRole}
                setSelectedRole={setSelectedRole}
                currentRole={currentRole}
                t={t}
                nav={nav}
              />
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-black/10 bg-white">
        <div className="w-full px-4 py-3 flex flex-col items-center gap-2 text-center text-xs t-muted sm:flex-row sm:justify-between sm:text-left sm:gap-4">
          <div>
            {t('footer.copy')} &middot; {t('footer.note')}
          </div>
          <PartnerLogos size="xs" className="justify-center" />
        </div>
      </footer>
    </div>
  );
}

/* ===================== Single unified auth card ===================== */
function AuthCard({ roles, selectedRole, setSelectedRole, currentRole, t, nav }) {
  const [mode, setMode] = useState('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [touched, setTouched] = useState({});
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const { role, color, loginOnly } = currentRole;

  const phoneDigits = phone.replace(/\D/g, '');
  const emailError =
    touched.email && !email ? t('validation.required') :
    touched.email && !EMAIL_RE.test(email) ? t('validation.invalid_email') : null;
  const passwordError =
    touched.password && !password ? t('validation.required') :
    touched.password && mode === 'signup' && !PASSWORD_RE.test(password) ? t('validation.password_rule') :
    touched.password && mode === 'signin' && password.length < 6 ? t('validation.password_short') : null;
  const nameError = touched.name && mode === 'signup' && !name ? t('validation.required') : null;
  const phoneError = touched.phone && mode === 'signup' && phoneDigits.length !== 10
    ? t('validation.phone_digits') : null;

  const passwordRules = mode === 'signup' && password
    ? [
        { ok: /[A-Za-z]/.test(password), label: 'A-z' },
        { ok: /\d/.test(password), label: '0-9' },
        { ok: /[!@#$%^&*(),.?":{}|<>_\-\[\];/\\`~+=]/.test(password), label: '!@#' },
        { ok: password.length >= 6, label: '≥6' },
      ]
    : [];

  const handleRoleChange = (newRole) => {
    setSelectedRole(newRole);
    setMode('signin');
    setError(null);
    setNotice(null);
    setTouched({});
    setEmail('');
    setPassword('');
    setName('');
    setPhone('');
  };

  const switchMode = () => {
    setMode((m) => (m === 'signin' ? 'signup' : 'signin'));
    setError(null);
    setNotice(null);
    setTouched({});
    setPassword('');
  };

  const submit = async (e) => {
    e.preventDefault();
    setTouched({ email: true, password: true, name: true, phone: true });
    setError(null);
    setNotice(null);
    if (!EMAIL_RE.test(email)) return;
    if (mode === 'signup' && !PASSWORD_RE.test(password)) return;
    if (mode === 'signin' && password.length < 6) return;
    if (mode === 'signup' && !name) return;
    if (mode === 'signup' && phoneDigits.length !== 10) return;

    setBusy(true);
    try {
      if (mode === 'signup') {
        await createUserWithEmailAndPassword(auth, email, password);
        await api('/auth/bootstrap', { method: 'POST', body: JSON.stringify({ name, role, phone: phoneDigits }) });
        await signOut(auth);
        setMode('signin');
        setPassword('');
        setName('');
        setPhone('');
        setTouched({});
        setNotice(t('login.account_created'));
      } else {
        await signInWithEmailAndPassword(auth, email, password);
        let me = null;
        try { me = await api('/auth/me'); } catch { /* handled below */ }
        if (!me?.role) {
          await signOut(auth);
          setError(t('login.role_verify_error'));
          return;
        }
        if (me.role !== role) {
          await signOut(auth);
          setError(t('login.role_mismatch'));
          return;
        }
        nav('/');
      }
    } catch (err) {
      setError(prettifyAuthError(err.message, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-elev w-full !p-0 overflow-hidden">
      {/* Card heading */}
      <div className="px-6 sm:px-8 pt-7 pb-5 border-b border-[color:var(--border-cool)]">
        <h2 className="text-2xl font-bold t-ink text-center">{t('login.welcome_back')} 👋</h2>
        <p className="text-sm t-muted text-center mt-1 leading-snug">{t('login.welcome_subtitle')}</p>

        {/* Role selector */}
        <div className="grid grid-cols-3 gap-2 mt-5">
          {roles.map((r) => {
            const active = selectedRole === r.role;
            return (
              <button
                key={r.role}
                type="button"
                onClick={() => handleRoleChange(r.role)}
                className={`flex flex-col items-center gap-2 rounded-xl p-3 border-2 transition-all duration-150 ${
                  active
                    ? 'shadow-card -translate-y-px'
                    : 'border-[color:var(--border)] hover:border-[color:var(--border-strong)] hover:-translate-y-px'
                }`}
                style={active ? { borderColor: r.color } : undefined}
              >
                <span
                  className="w-10 h-10 rounded-full grid place-items-center shrink-0 transition-colors duration-150"
                  style={active ? { background: r.color, color: '#fff' } : { background: 'var(--surface-2)', color: r.color }}
                >
                  {r.icon}
                </span>
                <div className="text-center">
                  <div
                    className="text-xs font-semibold leading-tight"
                    style={active ? { color: r.color } : { color: 'var(--ink)' }}
                  >
                    {r.title}
                  </div>
                  <div className="text-[10px] t-muted mt-0.5 leading-tight">{r.short}</div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Login / Sign up toggle */}
        {!loginOnly && (
          <div className="grid grid-cols-2 gap-1.5 mt-5 p-1.5 rounded-xl" style={{ background: 'var(--surface-2)' }}>
            <button
              type="button"
              onClick={() => mode !== 'signin' && switchMode()}
              className={`py-2.5 rounded-lg text-sm font-semibold transition-all duration-150 cursor-pointer ${
                mode === 'signin' ? 'bg-white shadow-card' : 't-muted'
              }`}
              style={mode === 'signin' ? { color } : undefined}
            >
              {t('login.signin')}
            </button>
            <button
              type="button"
              onClick={() => mode !== 'signup' && switchMode()}
              className={`py-2.5 rounded-lg text-sm font-semibold transition-all duration-150 cursor-pointer ${
                mode === 'signup' ? 'bg-white shadow-card' : 't-muted'
              }`}
              style={mode === 'signup' ? { color } : undefined}
            >
              {t('login.create_account')}
            </button>
          </div>
        )}
      </div>

      {/* Form */}
      <form onSubmit={submit} noValidate className="px-6 sm:px-8 py-6 space-y-4">
        {mode === 'signup' && (
          <Field label={t('common.name')} required error={nameError}>
            <input
              className={inputCls(nameError)}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setTouched((s) => ({ ...s, name: true }))}
              placeholder="Jane Doe"
            />
          </Field>
        )}

        {mode === 'signup' && (
          <Field label={t('login.phone_label')} required error={phoneError}>
            <input
              className={inputCls(phoneError)}
              inputMode="numeric"
              maxLength={10}
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/\D/g, '').slice(0, 10))}
              onBlur={() => setTouched((s) => ({ ...s, phone: true }))}
              placeholder={t('login.phone_placeholder')}
            />
            <p className="text-[11px] t-muted mt-1.5">{t('login.phone_hint')}</p>
          </Field>
        )}

        <Field label={t('common.email')} required error={emailError}>
          <input
            className={inputCls(emailError)}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => setTouched((s) => ({ ...s, email: true }))}
            placeholder="you@example.com"
            autoComplete="email"
          />
        </Field>

        <Field label={t('common.password')} required error={passwordError}>
          <div className="relative">
            <input
              className={inputCls(passwordError) + ' pr-10'}
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => setTouched((s) => ({ ...s, password: true }))}
              placeholder="••••••••"
              autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            />
            <button
              type="button"
              onClick={() => setShowPw((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 t-muted hover:t-ink"
              tabIndex={-1}
              aria-label={showPw ? t('common.hide_password') : t('common.show_password')}
            >
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
          {mode === 'signup' && passwordRules.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {passwordRules.map((r, i) => (
                <span
                  key={i}
                  className={`text-[10px] px-2 py-0.5 rounded font-semibold tracking-wide ${
                    r.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-[color:var(--surface-2)] t-muted'
                  }`}
                >
                  {r.ok ? '✓ ' : '· '}{r.label}
                </span>
              ))}
            </div>
          )}
        </Field>

        {mode === 'signin' && (
          <div className="flex items-center gap-2">
            <input
              id="remember-me"
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="w-4 h-4 rounded cursor-pointer"
              style={{ accentColor: color }}
            />
            <label htmlFor="remember-me" className="text-sm t-soft cursor-pointer select-none">
              {t('login.remember_me')}
            </label>
          </div>
        )}

        {notice && <Banner kind="info">{notice}</Banner>}
        {error && <Banner kind="error">{error}</Banner>}

        <button
          className="neu-btn-primary w-full"
          disabled={busy}
          style={{ background: color }}
        >
          {busy ? (
            <><Spinner /> {t('common.please_wait')}</>
          ) : mode === 'signin' ? (
            <>{t('login.signin')} <Arrow /></>
          ) : (
            <>{role === 'mo' ? t('login.create_mo') : t('login.create_agent')} <Arrow /></>
          )}
        </button>

        {loginOnly && (
          <p className="text-center text-xs t-muted pt-1">{t('login.admin_provisioned')}</p>
        )}
      </form>
    </div>
  );
}

/* ===================== Small UI helpers ===================== */
function inputCls(error) {
  return `neu-input${error ? ' border-red-400 focus:border-red-500' : ''}`;
}

function Field({ label, required, error, children }) {
  return (
    <div>
      <label className="neu-label flex items-center gap-1">
        <span>{label}</span>
        {required && <span className="text-red-500" aria-hidden>*</span>}
      </label>
      {children}
      {error && <p className="text-[11px] text-red-600 mt-1.5 font-medium">{error}</p>}
    </div>
  );
}

function LanguagePicker({ lang, setLang, languages }) {
  return (
    <div className="relative shrink-0">
      <select
        value={lang}
        onChange={(e) => setLang(e.target.value)}
        className="rounded-lg pl-3 pr-7 py-1.5 text-xs font-medium appearance-none cursor-pointer border border-[color:var(--border)] t-ink shadow-card"
        style={{ background: 'var(--surface)' }}
      >
        {languages.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>{l.native}</option>
        ))}
      </select>
      <svg
        className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none t-muted"
        width="10" height="10" viewBox="0 0 20 20" fill="currentColor"
      >
        <path d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 10.94l3.71-3.71a.75.75 0 1 1 1.06 1.06l-4.24 4.24a.75.75 0 0 1-1.06 0L5.21 8.29a.75.75 0 0 1 .02-1.08z" />
      </svg>
    </div>
  );
}

function Logo({ size = 22 }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v6" /><path d="M9 7h6" /><path d="M3 17h3l2-4 3 8 2-6 2 2h6" />
    </svg>
  );
}

function AgentIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function MOIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 2v3a4 4 0 0 0 8 0V2" />
      <path d="M6 5a6 6 0 0 0 6 6 6 6 0 0 0 6-6" /><path d="M12 11v4a4 4 0 0 0 8 0v-1" />
      <circle cx="20" cy="14" r="2" />
    </svg>
  );
}

function AdminIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2l8 4v6c0 5-3.5 9.5-8 10-4.5-.5-8-5-8-10V6l8-4z" /><circle cx="12" cy="11" r="2.5" />
      <path d="M12 13.5V16" />
    </svg>
  );
}

function FeatureIcon({ name }) {
  const c = { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'cpu': return <svg {...c}><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" /></svg>;
    case 'shield': return <svg {...c}><path d="M12 2l8 4v6c0 5-3.5 9.5-8 10-4.5-.5-8-5-8-10V6l8-4z" /></svg>;
    case 'wifi': return <svg {...c}><path d="M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0" /><line x1="12" y1="20" x2="12" y2="20" /></svg>;
    case 'globe': return <svg {...c}><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20z" /></svg>;
    case 'doc': return <svg {...c}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h6" /></svg>;
    default: return null;
  }
}

function Eye() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>;
}
function EyeOff() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a19.65 19.65 0 0 1 4.06-5.94" /><path d="M1 1l22 22" /><path d="M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a19.62 19.62 0 0 1-3.17 4.19" /></svg>;
}
function Arrow() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14" /><path d="M12 5l7 7-7 7" />
    </svg>
  );
}
function BackArrow() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
    </svg>
  );
}
function Spinner() {
  return (
    <svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
function prettifyAuthError(msg, t) {
  if (!msg) return msg;
  if (msg.includes('auth/wrong-password')) return t('validation.wrong_password');
  if (msg.includes('auth/invalid-credential')) return t('validation.wrong_password');
  if (msg.includes('auth/user-not-found')) return t('validation.no_user');
  if (msg.includes('auth/email-already-in-use')) return t('validation.email_in_use');
  if (msg.includes('auth/weak-password')) return t('validation.password_short');
  if (msg.includes('auth/network-request-failed')) return t('validation.network_error');
  if (msg.includes('auth/too-many-requests')) return t('validation.too_many_requests');
  return msg.replace(/^Firebase:\s*/, '');
}
