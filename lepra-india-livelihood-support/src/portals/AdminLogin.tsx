import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, LineChart, Loader2, ArrowLeft } from 'lucide-react';
import { useAuth } from '../AuthContext';
import { UserRole } from '../firebase';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { assetUrl } from '../utils/assetUrl';

interface AdminLoginProps {
  role: 'approver' | 'superadmin';
}

const ROLE_META: Record<UserRole, { icon: React.ReactNode; accent: string }> = {
  agent: { icon: <ShieldCheck className="w-4 h-4 text-teal-700" />, accent: 'bg-teal-50/70 text-teal-900' },
  approver: {
    icon: <ShieldCheck className="w-4 h-4 text-emerald-700" />,
    accent: 'bg-emerald-50/70 text-emerald-900'
  },
  superadmin: {
    icon: <LineChart className="w-4 h-4 text-sky-700" />,
    accent: 'bg-sky-50/70 text-sky-900'
  }
};

export default function AdminLogin({ role }: AdminLoginProps) {
  const { t } = useTranslation(['adminLogin', 'landing']);
  const navigate = useNavigate();
  const { signInWithRole } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const meta = ROLE_META[role];
  const title = t(`roles.${role}.title`);
  const portalSubtitle = t(`landing:portals.${role}.subtitle`);
  const portalDescription = t(`landing:portals.${role}.description`);
  const bullets = t(`landing:portals.${role}.bullets`, { returnObjects: true }) as string[];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signInWithRole(email.trim(), password, role);
    } catch (err: any) {
      setError(err?.message || t('loginFailed'));
    } finally {
      setBusy(false);
    }
  };


  return (
    <div className="min-h-screen bg-[#ffffff] flex flex-col">
      <header className="sticky top-0 z-30 w-full border-b border-black/5 bg-white/80 backdrop-blur-md">
        <div className="flex w-full items-center gap-2 sm:gap-3 px-4 sm:px-6 lg:px-10 xl:px-16 py-2.5 sm:py-3.5">
          <button onClick={() => navigate('/')} className="text-black/60 hover:text-black inline-flex items-center gap-1 text-xs cursor-pointer">
            <ArrowLeft className="w-4 h-4" /> {t('back')}
          </button>
          <div className="h-5 w-px bg-black/10 shrink-0" />
          {meta.icon}
          <span className="font-bold text-xs sm:text-sm text-black truncate">{title}</span>
          <div className="ml-auto shrink-0">
            <LanguageSwitcher dark={false} />
          </div>
        </div>
      </header>

      <main
        className="flex-1 flex items-center justify-center p-4 relative overflow-hidden bg-cover bg-center"
        style={{ backgroundImage: `url(${assetUrl('login-bg.jpg')})` }}
      >
        <div className="absolute inset-0 bg-white/35" />
        <div className="relative z-10 bg-white rounded-2xl border border-black/[0.07] shadow-[0_1px_2px_rgba(16,24,40,0.04),0_16px_40px_-16px_rgba(16,24,40,0.18)] max-w-md w-full overflow-hidden">
          <div className={`${meta.accent} p-5 border-b border-black/5 flex items-start justify-between`}>
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold opacity-70">{portalSubtitle}</div>
              <div className="text-base font-bold mt-1">{title}</div>
            </div>
            <div className="bg-white ring-1 ring-black/5 p-2 rounded-lg shrink-0">
              {meta.icon}
            </div>
          </div>

          <div className="p-4 border-b border-gray-100">
            <p className="text-xs text-gray-600 leading-relaxed">{portalDescription}</p>
            <ul className="space-y-1.5 mt-2.5">
              {bullets.map((b) => (
                <li key={b} className="text-[11px] text-gray-700 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#0284c7]" />
                  {b}
                </li>
              ))}
            </ul>
          </div>

          <form onSubmit={handleSubmit} className="p-5 space-y-3">
            <div className="bg-amber-50 border border-amber-100 text-amber-900 text-[11px] px-3 py-2 rounded-lg">
              {t('signupDisabled')}
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('emailLabel')}</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.org"
                className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('passwordLabel')}</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
              />
            </div>

            {error && (
              <div className="bg-rose-50 border border-rose-100 text-rose-700 text-xs px-3 py-2 rounded-lg">
                {error}
              </div>
            )}
                 
            <button
              type="submit"
              disabled={busy}
              className="w-full bg-gradient-to-r from-teal-600 to-sky-600 hover:from-teal-700 hover:to-sky-700 disabled:opacity-60 text-white font-bold text-xs py-2.5 rounded-lg shadow-sm flex items-center justify-center gap-2 cursor-pointer uppercase tracking-wider"
            >
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {t('loginButton')}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
