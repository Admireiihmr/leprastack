import React from 'react';
import { useTranslation } from 'react-i18next';
import { Home, LogOut } from 'lucide-react';
import { useAuth } from '../AuthContext';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { assetUrl } from '../utils/assetUrl';

interface PortalShellProps {
  roleBadge: string;
  accent: string;
  children: React.ReactNode;
}

export default function PortalShell({ roleBadge, accent, children }: PortalShellProps) {
  const { t } = useTranslation('common');
  const { user, logout } = useAuth();
  return (
    <div
      className="min-h-screen bg-white bg-cover bg-fixed bg-center text-[#171717] font-sans flex flex-col"
      style={{ backgroundImage: `url(${assetUrl('app-bg.svg')})` }}
    >
      {/* Same shell as the Lepra Stack portal navbar: translucent white, one
          row, branding hard left and controls hard right. */}
      <header className="sticky top-0 z-30 w-full shrink-0 border-b border-black/5 bg-white/80 backdrop-blur-md">
        <div className="flex w-full items-center justify-between gap-2 sm:gap-3 px-4 sm:px-6 lg:px-10 xl:px-16 py-2.5 sm:py-3.5">
          <div className="flex items-center gap-2.5 sm:gap-3.5 min-w-0 flex-1">
            <a
              href="/"
              title="Lepra Stack Home"
              aria-label="Lepra Stack Home"
              className="inline-flex items-center justify-center w-8 h-8 rounded-full border border-black/10 text-black/50 hover:text-black/80 hover:border-black/20 transition-colors shrink-0"
            >
              <Home className="w-3.5 h-3.5" />
            </a>
            <div className="h-6 w-px bg-black/10 shrink-0" />
            <img src={assetUrl("lepra-logo.png")} alt="LEPRA" className="h-7 sm:h-9 w-auto shrink-0" />
            <div className="h-10 w-px bg-black/10 hidden sm:block" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] ${accent} text-white font-bold px-2 py-0.5 rounded-full tracking-wider uppercase`}>{roleBadge}</span>
                <span className="text-black/40 text-xs font-mono hidden sm:inline">{t('systemName')}</span>
              </div>
              <h1 className="text-sm sm:text-lg font-bold tracking-tight text-black truncate">{t('appName')}</h1>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 sm:gap-3 shrink-0">
            <LanguageSwitcher dark={false} />
            <img src={assetUrl("iihmr-update.png")} alt="IIHMR Bangalore" title={t('inPartnershipWith')} className="h-9 w-auto shrink-0 hidden lg:block" />
            <img src={assetUrl("kind.jpeg")} alt="Kind Cares" title="Kind Cares" className="h-9 w-auto shrink-0 rounded hidden lg:block" />

            <div className="flex items-center gap-2 sm:gap-3 rounded-xl sm:border sm:border-black/10 sm:bg-black/[0.03] sm:hover:bg-black/[0.06] transition-colors px-0 sm:px-3 py-1.5">
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-teal-600 to-sky-600 text-white flex items-center justify-center text-xs font-bold uppercase shrink-0">
                {(user?.email || '?').charAt(0)}
              </div>
              <div className="text-right text-xs hidden sm:block">
                <span className="text-black/45 block text-[11px] uppercase tracking-wide">{t('signedIn')}</span>
                <span className="font-semibold text-black/80 font-mono">{user?.email}</span>
              </div>
              <div className="h-6 w-px bg-black/10 hidden sm:block" />
              <button
                onClick={logout}
                title={t('signOut')}
                className="inline-flex items-center gap-1 p-1.5 px-2 rounded-lg border border-black/10 text-black/70 hover:bg-rose-50 hover:text-rose-700 hover:border-rose-200 transition-colors cursor-pointer text-[10px] uppercase font-bold tracking-wider"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">{t('logout')}</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5">{children}</main>

      <footer className="bg-white/70 backdrop-blur-sm border-t border-black/10 shrink-0">
        <div className="max-w-7xl mx-auto px-4 py-3 sm:py-3.5 flex flex-col items-center gap-2 text-center sm:flex-row sm:justify-between sm:text-left sm:gap-4">
          <span className="text-[11px] text-black/55">{t('copyright')}</span>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <span className="hidden sm:inline text-[10px] uppercase tracking-wide text-black/35">In partnership with</span>
            <a href="https://leprasociety.in/" target="_blank" rel="noopener noreferrer">
              <img src={assetUrl("lepra-logo.png")} alt="LEPRA Society" className="h-6 w-auto object-contain rounded" />
            </a>
            <img src={assetUrl("iihmr-update.png")} alt="IIHMR Bangalore" className="h-6 w-auto object-contain rounded" />
            <img src={assetUrl("kind.jpeg")} alt="Kind Care" className="h-6 w-auto object-contain rounded" />
          </div>
        </div>
      </footer>
    </div>
  );
}
