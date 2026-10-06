import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  User,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  updateProfile
} from 'firebase/auth';
import { ref, get, set, serverTimestamp } from 'firebase/database';
import { auth, db, UserRole, DB_PATHS } from './firebase';

export interface AuthUserProfile {
  uid: string;
  email: string;  
  displayName: string;
  role: UserRole;
}

interface AuthContextValue {
  user: AuthUserProfile | null;
  initializing: boolean;
  signUpAgent: (email: string, password: string, displayName: string) => Promise<void>;
  signInWithRole: (email: string, password: string, expectedRole: UserRole) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

async function loadProfile(fbUser: User): Promise<AuthUserProfile | null> {
  const snap = await get(ref(db, `${DB_PATHS.users}/${fbUser.uid}`));
  if (!snap.exists()) return null;
  const data = snap.val();
  return {
    uid: fbUser.uid,
    email: fbUser.email || data.email || '',
    displayName: fbUser.displayName || data.displayName || '',
    role: data.role as UserRole
  };
}



export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUserProfile | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (fbUser) => {
      if (!fbUser) {
        setUser(null);
        setInitializing(false);
        return;
      }
      try {
        const profile = await loadProfile(fbUser);
        setUser(profile);
      } catch (err) {
        console.error('Failed to load profile', err);
        setUser(null);
      } finally {
        setInitializing(false);
      }
    });
    return () => unsub();
  }, []);


  

  const signUpAgent = async (email: string, password: string, displayName: string) => {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    await updateProfile(cred.user, { displayName });
    await set(ref(db, `${DB_PATHS.users}/${cred.user.uid}`), {
      email,
      displayName,
      role: 'agent' as UserRole,
      createdAt: serverTimestamp()
    });
    const profile = await loadProfile(cred.user);
    setUser(profile);
  };

  const signInWithRole = async (email: string, password: string, expectedRole: UserRole) => {
    const cred = await signInWithEmailAndPassword(auth, email, password);
    const profile = await loadProfile(cred.user);
    if (!profile) {
      await signOut(auth);
      throw new Error('No profile found for this account. Ask the administrator to provision your access.');
    }
    if (profile.role !== expectedRole) {
      await signOut(auth);
      throw new Error(`This account is not authorized for the ${expectedRole} portal.`);
    }
    setUser(profile);
  };

  const logout = async () => {
    await signOut(auth);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, initializing, signUpAgent, signInWithRole, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
