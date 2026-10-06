import React from 'react';
import { useTranslation } from 'react-i18next';
import { Users, ShieldCheck, LineChart, ArrowLeft, ArrowRight, Sparkles } from 'lucide-react';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { assetUrl } from '../utils/assetUrl';

export type PortalChoice = 'agent' | 'approver' | 'superadmin' | 'setup';

interface LandingProps {
  onChoose: (choice: PortalChoice) => void;
}

// Each portal keeps its own hue, as before, but as a light tint with the icon
// carrying the colour — reads cleaner than solid blocks against the hero photo.
const PORTAL_KEYS: Array<{ key: PortalChoice; icon: React.ReactNode; badge: string; dot: string; hover: string }> = [
  { key: 'agent', icon: <Users className="w-6 h-6" />, badge: 'bg-teal-50 text-teal-700 ring-teal-100', dot: 'bg-teal-500', hover: 'hover:border-teal-200' },
  { key: 'approver', icon: <ShieldCheck className="w-6 h-6" />, badge: 'bg-sky-50 text-sky-700 ring-sky-100', dot: 'bg-sky-500', hover: 'hover:border-sky-200' },
  { key: 'superadmin', icon: <LineChart className="w-6 h-6" />, badge: 'bg-indigo-50 text-indigo-700 ring-indigo-100', dot: 'bg-indigo-400', hover: 'hover:border-indigo-200' }
];

export default function Landing({ onChoose }: LandingProps) {
  const { t } = useTranslation(['landing', 'common']);

  return (
    <div className="min-h-screen bg-white flex flex-col">
      <header className="sticky top-0 z-30 w-full border-b border-black/5 bg-white/80 backdrop-blur-md">
        <div className="flex w-full items-center justify-between gap-2 sm:gap-3 px-4 sm:px-6 lg:px-10 xl:px-16 py-3 sm:py-4">
          <div className="flex items-center gap-2.5 sm:gap-3.5 min-w-0 flex-1">
            <a
              href="/"
              title="Back to Lepra Stack"
              aria-label="Back to Lepra Stack"
              className="inline-flex items-center justify-center w-8 h-8 rounded-full border border-black/10 text-black/50 hover:text-black/80 hover:border-black/20 transition-colors shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
            </a>
            <div className="h-6 w-px bg-black/10 shrink-0" />
            <img src={assetUrl("lepra-logo.png")} alt="LEPRA" className="h-7 sm:h-9 w-auto shrink-0" />
            <div className="h-10 w-px bg-black/10 hidden sm:block" />
            <div className="min-w-0">
              {/* Decorative trust badge — dropped on narrow screens so the
                  product name keeps a single line instead of wrapping. */}
              <span className="hidden sm:inline-flex items-center rounded-full border border-teal-200 bg-teal-50 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-teal-800">
                {t('landing:sopApproved')}
              </span>
              <h1 className="text-sm sm:text-lg font-bold tracking-tight text-black truncate">
                {/* The full name needs ~230px; on a phone show the short form
                    rather than truncating the brand mid-word. */}
                <span className="sm:hidden">{t('common:appName')}</span>
                <span className="hidden sm:inline">{t('common:appNameFull')}</span>
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <LanguageSwitcher dark={false} />
            <img src={assetUrl("iihmr-update.png")} alt="IIHMR" className="h-9 w-auto shrink-0 hidden md:block" />
            <img src={assetUrl("kind.jpeg")} alt="Kind Cares" className="h-9 w-auto shrink-0 rounded hidden md:block" />
          </div>
        </div>
      </header>

      <main
        className="flex-1 w-full relative bg-cover bg-[30%_65%]"
        style={{ backgroundImage: `url(${assetUrl('hero-bg.jpg')})` }}
      >
        <div className="absolute inset-0 bg-white/40" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-white" />

        <div className="relative mx-auto max-w-6xl w-full px-4 sm:px-6 py-16 sm:py-20">
          <div className="text-center max-w-2xl mx-auto">
            <span className="inline-flex items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-3.5 py-1.5 text-xs font-medium text-teal-800">
              <Sparkles className="w-3 h-3" />
              {t('landing:chooseYourPortal')}
            </span>
            <h2 className="mt-6 text-3xl sm:text-4xl font-bold tracking-tight text-black">
              {t('landing:roleBasedAccess')}
            </h2>
            <p className="mt-3 text-black/60 leading-relaxed">
              {t('landing:intro')}
            </p>
          </div>

          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {PORTAL_KEYS.map((p) => {
              const bullets = t(`landing:portals.${p.key}.bullets`, { returnObjects: true }) as string[];
              return (
                <button
                  key={p.key}
                  onClick={() => onChoose(p.key)}
                  className={`group relative flex h-full flex-col overflow-hidden rounded-2xl border border-black/[0.07] bg-white/95 p-7 text-left shadow-[0_1px_2px_rgba(16,24,40,0.04),0_8px_24px_-12px_rgba(16,24,40,0.10)] hover:shadow-[0_1px_2px_rgba(16,24,40,0.04),0_16px_40px_-16px_rgba(16,24,40,0.18)] hover:-translate-y-0.5 ${p.hover} transition-all cursor-pointer`}
                >
                  <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ring-1 ${p.badge}`}>
                    {p.icon}
                  </div>

                  <div className="mt-5 text-[10px] font-bold uppercase tracking-widest text-black/40">
                    {t(`landing:portals.${p.key}.subtitle`)}
                  </div>
                  <h3 className="mt-1 font-semibold text-lg text-black transition-colors">
                    {t(`landing:portals.${p.key}.title`)}
                  </h3>
                  <p className="mt-2 text-sm text-black/60 leading-relaxed">
                    {t(`landing:portals.${p.key}.description`)}
                  </p>

                  <ul className="mt-4 space-y-1.5">
                    {bullets.map((b) => (
                      <li key={b} className="text-xs text-black/55 flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${p.dot}`} />
                        {b}
                      </li>
                    ))}
                  </ul>

                  <span className="mt-auto pt-6 inline-flex items-center gap-1.5 text-sm font-medium text-teal-700">
                    {t('landing:continue')}
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </main>

      <footer className="bg-white border-t border-black/10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-3 sm:py-3.5 flex flex-col items-center gap-2 text-center text-[10px] sm:text-[11px] text-black/55 sm:flex-row sm:justify-between sm:text-left sm:gap-4">
          <div className="flex flex-wrap items-center justify-center gap-3">
            <span>{t('common:copyright')}</span>
            <span className="text-black/20">&middot;</span>
            <button
              onClick={() => onChoose('setup')}
              className="text-teal-700 hover:text-sky-700 underline font-medium cursor-pointer"
            >
              {t('landing:provisionAdmin')}
            </button>
          </div>
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
