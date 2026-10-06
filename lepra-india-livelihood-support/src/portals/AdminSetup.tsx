import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ShieldAlert, Loader2, CheckCircle } from 'lucide-react';
import { signInWithEmailAndPassword, signOut, updateProfile } from 'firebase/auth';
import { ref, set, serverTimestamp } from 'firebase/database';
import { auth, db, DB_PATHS, UserRole } from '../firebase';
import LanguageSwitcher from '../components/LanguageSwitcher';
import { assetUrl } from '../utils/assetUrl';

interface AdminSetupProps {
  onBack?: () => void;
}

export default function AdminSetup({ onBack }: AdminSetupProps) {
  const { t } = useTranslation('adminSetup');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<UserRole>('approver');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const roleLabel = (r: UserRole) => (r === 'approver' ? t('roleApprover') : t('roleSuperAdmin'));

  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const cred = await signInWithEmailAndPassword(auth, email.trim(), password);
      if (displayName.trim()) {
        try { await updateProfile(cred.user, { displayName: displayName.trim() }); } catch {}
      }
      await set(ref(db, `${DB_PATHS.users}/${cred.user.uid}`), {
        email: email.trim(),
        displayName: displayName.trim() || cred.user.displayName || email.trim(),
        role,
        createdAt: serverTimestamp()
      });
      await signOut(auth);
      setSuccess(t('provisionedSuccess', { email: email.trim(), role: roleLabel(role) }));
      setEmail('');
      setPassword('');
      setDisplayName('');
    } catch (err: any) {
      console.error('[AdminSetup] failed:', err);
      setError(err?.code || err?.message || t('provisioningFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#ffffff] flex flex-col">
      <header className="sticky top-0 z-30 w-full border-b border-black/5 bg-white/80 backdrop-blur-md">
        <div className="flex w-full items-center gap-2 sm:gap-3 px-4 sm:px-6 lg:px-10 xl:px-16 py-2.5 sm:py-3.5">
          <button onClick={onBack} className="text-black/60 hover:text-black inline-flex items-center gap-1 text-xs cursor-pointer">
            <ArrowLeft className="w-4 h-4" /> {t('back')}
          </button>
          <div className="h-5 w-px bg-black/10 shrink-0" />
          <ShieldAlert className="w-4 h-4 text-teal-700" />
          <span className="font-bold text-xs sm:text-sm text-black truncate">{t('headerTitle')}</span>
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
          <div className="bg-teal-50/70 text-teal-900 p-5 border-b border-black/5">
            <h2 className="font-bold text-base">{t('cardTitle')}</h2>
            <p className="text-xs text-white/80 mt-0.5">
              {t('cardSubtitle')}
            </p>
          </div>

          <form onSubmit={handleProvision} className="p-5 space-y-3">
            <div className="bg-amber-50 border border-amber-100 text-amber-900 text-[11px] px-3 py-2 rounded-lg leading-relaxed">
              <b>{t('howItWorksLabel')}</b> {t('howItWorksBefore')} <code>livelihood/users/&lt;uid&gt;</code>{t('howItWorksAfter')}
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('emailLabel')}</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="ratna@example.org"
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

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('displayNameLabel')}</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t('displayNamePlaceholder')}
                className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
              />
            </div>

            <div>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">{t('roleToAssignLabel')}</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setRole('approver')}
                  className={`py-2 text-xs font-bold rounded border transition-colors cursor-pointer ${
                    role === 'approver' ? 'bg-emerald-700 border-emerald-700 text-white' : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {t('roleApprover')}
                </button>
                <button
                  type="button"
                  onClick={() => setRole('superadmin')}
                  className={`py-2 text-xs font-bold rounded border transition-colors cursor-pointer ${
                    role === 'superadmin' ? 'bg-[#0284c7] border-[#0284c7] text-white' : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {t('roleSuperAdmin')}
                </button>
              </div>
            </div>

            {error && (
              <div className="bg-rose-50 border border-rose-100 text-rose-700 text-xs px-3 py-2 rounded-lg">
                {error}
              </div>
            )}
            {success && (
              <div className="bg-emerald-50 border border-emerald-100 text-emerald-800 text-xs px-3 py-2 rounded-lg flex items-start gap-2">
                <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{success}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full bg-gradient-to-r from-teal-600 to-sky-600 hover:from-teal-700 hover:to-sky-700 disabled:opacity-60 text-white font-bold text-xs py-2.5 rounded-lg shadow-sm flex items-center justify-center gap-2 cursor-pointer uppercase tracking-wider"
            >
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {t('submitButton')}
            </button>

            <p className="text-[10px] text-gray-500 text-center">
              {t('footerNote')}
            </p>
          </form>
        </div>
      </main>
    </div>
  );
}
