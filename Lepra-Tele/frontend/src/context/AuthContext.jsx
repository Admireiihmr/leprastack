import { createContext, useContext, useEffect, useState } from 'react';
import { onAuthStateChanged, signOut as fbSignOut } from 'firebase/auth';
import { auth } from '../lib/firebase';
import { api } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [profileError, setProfileError] = useState(null);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (u) => {
      // Re-enter the loading state every time the auth identity changes so
      // downstream components don't fall back to a stale/default role while
      // the new profile is being fetched.
      setLoading(true);
      setProfileError(null);
      setUser(u);
      if (u) {
        try {
          // Force refresh so newly-set custom claims (role) are picked up.
          const tokenResult = await u.getIdTokenResult(true);
          const me = await api('/auth/me');
          setProfile(me);
          // If the canonical role from the backend (Firestore profile) differs
          // from the token's claim, the backend will have re-synced the claim.
          // Force one more refresh so subsequent API calls carry the right role.
          if (me?.role && tokenResult?.claims?.role !== me.role) {
            await u.getIdToken(true);
          }
        } catch (e) {
          console.error('Failed to load profile', e);
          setProfile(null);
          setProfileError(e?.message || 'Failed to load profile');
        }
      } else {
        setProfile(null);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  const signOut = () => fbSignOut(auth);

  // role is undefined until the profile actually loads — callers must check
  // `loading` first. Never default to a privileged role like "patient" here;
  // that would silently misroute agents/MOs/admins when /auth/me lags.
  const role = profile?.role;
  return (
    <AuthContext.Provider value={{ user, profile, role, loading, profileError, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
