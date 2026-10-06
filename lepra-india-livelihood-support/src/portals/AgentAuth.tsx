import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Users, Loader2, ArrowLeft } from 'lucide-react';
import { useAuth } from '../AuthContext';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { assetUrl } from '../utils/assetUrl';

export default function AgentAuth() {
  const { t } = useTranslation(['agentAuth', 'landing']);
  const navigate = useNavigate();
  const bullets = t('landing:portals.agent.bullets', { returnObjects: true }) as string[];
  const { signUpAgent, signInWithRole } = useAuth();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === 'signup') {
        if (!displayName.trim()) throw new Error(t('nameRequiredError'));
        if (password.length < 6) throw new Error(t('passwordLengthError'));
        await signUpAgent(email.trim(), password, displayName.trim());
      } else {
        await signInWithRole(email.trim(), password, 'agent');
      }
    } catch (err: any) {
      setError(err?.message || t('authFailedError'));
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
          <Users className="w-4 h-4 text-teal-700" />
          <span className="font-bold text-xs sm:text-sm text-black truncate">{t('portalTitle')}</span>
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
          <div className="bg-teal-50/70 text-teal-900 p-5 border-b border-black/5 flex items-start justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-teal-700/70">{t('landing:portals.agent.subtitle')}</div>
              <div className="text-base font-bold mt-1">{t('landing:portals.agent.title')}</div>
            </div>
            <div className="bg-white text-teal-700 ring-1 ring-teal-100 p-2 rounded-lg shrink-0">
              <Users className="w-5 h-5" />
            </div>
          </div>

          <div className="p-4 border-b border-gray-100">
            <p className="text-xs text-gray-600 leading-relaxed">{t('landing:portals.agent.description')}</p>
            <ul className="space-y-1.5 mt-2.5">
              {bullets.map((b) => (
                <li key={b} className="text-[11px] text-gray-700 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#0284c7]" />
                  {b}
                </li>
              ))}
            </ul>
          </div>

          <div className="px-5 pt-4">
            <div className="flex bg-[#ffffff] p-1 rounded-lg border border-gray-200">
              <button
                onClick={() => { setMode('signin'); setError(null); }}
                className={`flex-1 py-1.5 text-xs font-bold rounded-md transition-colors cursor-pointer ${
                  mode === 'signin' ? 'bg-teal-700 text-white' : 'text-black/60'
                }`}
              >
                {t('signInTab')}
              </button>
              <button
                onClick={() => { setMode('signup'); setError(null); }}
                className={`flex-1 py-1.5 text-xs font-bold rounded-md transition-colors cursor-pointer ${
                  mode === 'signup' ? 'bg-teal-700 text-white' : 'text-black/60'
                }`}
              >
                {t('signUpTab')}
              </button>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="p-5 space-y-3">
            {mode === 'signup' && (
              <div>
                <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('fullNameLabel')}</label>
                <input
                  type="text"
                  required
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={t('fullNamePlaceholder')}
                  className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
                />
              </div>
            )}

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('emailLabel')}</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('emailPlaceholder')}
                className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('passwordLabel')}</label>
              <input
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('passwordPlaceholder')}
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
              {mode === 'signin' ? t('signInSubmit') : t('signUpSubmit')}
            </button>

            <p className="text-[10px] text-gray-500 text-center mt-1">
              {t('sopNotice')}
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}
