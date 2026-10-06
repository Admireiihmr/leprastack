import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Home() {
  const { user, role, loading, profileError, signOut } = useAuth();
  if (loading) return <div className="p-8 t-muted">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;

  // Authenticated but no role on profile — this happens when /auth/me
  // failed or when the Firestore user doc wasn't bootstrapped. Don't
  // silently demote the user to a patient view; show what's happening.
  if (!role) {
    return (
      <div className="min-h-[60vh] grid place-items-center p-6">
        <div className="card-elev w-full max-w-md">
          <div className="section-title">Account</div>
          <h2 className="text-2xl font-semibold tracking-tight t-ink mt-1">Account not configured</h2>
          <p className="text-sm t-muted mt-3">
            We couldn't load your profile. This usually means the backend is unreachable or your
            account was not finished setting up. Sign out and sign in again, or contact an admin.
          </p>
          {profileError && (
            <div className="mt-4 rounded-md border border-[color:var(--border)] bg-[color:var(--surface-2)] px-3 py-2 text-xs font-mono t-soft">
              {profileError}
            </div>
          )}
          <div className="mt-5 flex justify-end">
            <button onClick={signOut} className="btn-primary">Sign out</button>
          </div>
        </div>
      </div>
    );
  }

  const dest = {
    agent: '/agent',
    mo: '/mo',
    admin: '/admin',
  }[role] || '/login';
  return <Navigate to={dest} replace />;
}
