import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTranslation } from '../i18n/I18nContext';
import OfflineBanner from './OfflineBanner';
import PartnerLogos from './PartnerLogos';
import { assetUrl } from '../utils/assetUrl';

export default function Layout({ children }) {
  const { profile, role, signOut } = useAuth();
  const { t, lang, setLang, languages } = useTranslation();
  const nav = useNavigate();

  const items = navByRole(role, t);
  const displayName = profile?.profile?.name || profile?.email || 'User';
  const initials = (displayName || '?').slice(0, 1).toUpperCase();

  return (
    <div
      className="min-h-screen flex flex-col relative overflow-x-hidden"
      style={{
        backgroundImage: `url(${assetUrl('app-bg.jpg')})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
      }}
    >
      {/* Subtle veil to keep content readable over the background */}
      <div className="absolute inset-0 bg-white/60 pointer-events-none" aria-hidden />
      <header
        className="relative z-40 shrink-0 sticky top-0 border-b border-white/40 bg-white/80 backdrop-blur-md"
      >
        <div className="w-full px-4 sm:px-5 md:px-8 h-14 flex items-center justify-between gap-2 sm:gap-3">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <a
              href="/"
              title={t('common.lepra_stack_home')}
              aria-label={t('common.lepra_stack_home')}
              className="inline-flex items-center justify-center w-7 h-7 rounded-full border border-[color:var(--border)] t-muted hover:t-ink hover:border-[color:var(--border-strong)] transition-colors duration-150 shrink-0"
            >
              <HomeIcon />
            </a>
            <span className="w-px h-5 bg-[color:var(--border)] shrink-0" aria-hidden />
            <Link to="/" className="shrink-0 flex items-center gap-2 sm:gap-2.5 min-w-0">
              <span className="brand-mark"><Logo /></span>
              <div className="leading-tight hidden sm:block min-w-0">
                <div className="font-semibold tracking-wide text-[13px] t-ink truncate">TELE-LEPROSY</div>
                <div className="text-[10px] uppercase tracking-[0.16em] t-muted truncate">
                  {t('brand.subtitle')}
                </div>
              </div>
            </Link>
          </div>

          <nav className="hidden lg:flex items-center gap-1 mx-4">
            {items.map((i) => (
              <NavLink
                key={i.to}
                to={i.to}
                end
                className={({ isActive }) =>
                  `px-3.5 py-2 rounded-lg text-sm font-semibold transition-all duration-150 ${
                    isActive
                      ? 'text-white bg-[color:var(--brand)] shadow-[0_4px_12px_-4px_var(--brand-ring)] -translate-y-px'
                      : 't-soft hover:text-[color:var(--brand)] hover:bg-[color:var(--brand-soft)] hover:-translate-y-px'
                  }`
                }
              >
                {i.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
<div className="relative shrink-0">
              <select
                aria-label={t('settings.language')}
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                className="rounded-md pl-2.5 sm:pl-3 pr-6 sm:pr-7 py-1.5 text-xs font-medium appearance-none cursor-pointer t-ink border max-w-[80px] sm:max-w-none truncate"
                style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
              >
                {languages.map((l) => (
                  <option key={l.code} value={l.code} lang={l.code}>{l.native}</option>
                ))}
              </select>
              <svg
                className="absolute right-1.5 sm:right-2 top-1/2 -translate-y-1/2 pointer-events-none t-muted"
                width="10" height="10" viewBox="0 0 20 20" fill="currentColor"
              >
                <path d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 10.94l3.71-3.71a.75.75 0 1 1 1.06 1.06l-4.24 4.24a.75.75 0 0 1-1.06 0L5.21 8.29a.75.75 0 0 1 .02-1.08z" />
              </svg>
            </div>

            <div className="hidden lg:flex flex-col items-end leading-tight ml-1 min-w-0 max-w-[180px]">
              <span className="text-sm font-medium t-ink truncate w-full text-right">{displayName}</span>
              <span className="text-[11px] t-muted truncate w-full text-right">{role ? t('role.' + role) : '…'}</span>
            </div>
            <Link
              to="/settings"
              title={t('nav.settings')}
              className="w-8 h-8 rounded-full text-white grid place-items-center font-semibold text-sm shrink-0"
              style={{ background: 'var(--brand)' }}
            >
              {initials}
            </Link>
            <button
              onClick={async () => { await signOut(); nav('/login'); }}
              title={t('nav.signout')}
              aria-label={t('nav.signout')}
              className="hidden sm:inline-flex neu-btn-ghost shrink-0"
            >
              {t('nav.signout')}
            </button>
            <button
              onClick={async () => { await signOut(); nav('/login'); }}
              title={t('nav.signout')}
              aria-label={t('nav.signout')}
              className="sm:hidden w-8 h-8 rounded-md grid place-items-center border t-soft hover:t-ink shrink-0"
              style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
            >
              <SignOutIcon />
            </button>
          </div>
        </div>

        {items.length > 0 && (
          <nav className="lg:hidden border-t overflow-x-auto" style={{ borderColor: 'var(--border)' }}>
            <div className="px-4 flex gap-1">
              {items.map((i) => (
                <NavLink
                  key={i.to}
                  to={i.to}
                  end
                  className={({ isActive }) =>
                    `px-3 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition ${
                      isActive
                        ? 'border-[color:var(--brand)] text-[color:var(--brand)]'
                        : 'border-transparent t-soft hover:t-ink'
                    }`
                  }
                >
                  {i.label}
                </NavLink>
              ))}
            </div>
          </nav>
        )}
      </header>

      <OfflineBanner />

      <main className="relative z-10 flex-1">
        <div className="max-w-[1600px] mx-auto px-3 sm:px-4 md:px-8 py-4 sm:py-6 md:py-8">
          {children}
        </div>
      </main>

      <footer className="relative z-10 shrink-0 border-t border-black/10 bg-white mt-auto">
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

function navByRole(role, t) {
  const settings = { to: '/settings', label: t('nav.settings') };
  switch (role) {
    case 'agent':
      return [
        { to: '/agent', label: t('nav.intake') },
        { to: '/agent/patients', label: t('nav.patients') },
        settings,
      ];
    case 'mo':
      return [
        { to: '/mo', label: t('nav.queue') },
        { to: '/mo/appointments', label: t('nav.appointments') },
        settings,
      ];
    case 'admin':
      return [
        { to: '/admin', label: t('nav.metrics') },
        { to: '/admin/users', label: t('nav.users') },
        { to: '/admin/audit', label: t('nav.audit') },
        settings,
      ];
    default:
      return [settings];
  }
}

function Logo() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v6" /><path d="M9 7h6" /><path d="M3 17h3l2-4 3 8 2-6 2 2h6" />
    </svg>
  );
}

function HomeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}

