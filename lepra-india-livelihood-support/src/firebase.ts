import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import { getDatabase } from 'firebase/database';
import { getStorage } from 'firebase/storage';

const firebaseConfig = {
  apiKey: "AIzaSyAbt_lz38xOrLZhOQ2AnaAjhehUYAsKuQE",
  authDomain: "contact-4252f.firebaseapp.com",
  databaseURL: "https://contact-4252f-default-rtdb.firebaseio.com",
  projectId: "contact-4252f",
  storageBucket: "contact-4252f.firebasestorage.app",
  messagingSenderId: "672173182552",
  appId: "1:672173182552:web:a5722ad6443a3973c0842d"
};

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getDatabase(app);
export const storage = getStorage(app);

export const DB_ROOT = 'livelihood';
export const DB_PATHS = {
  users: `${DB_ROOT}/users`,
  beneficiaries: `${DB_ROOT}/beneficiaries`,
  // FHIR (Patient/Condition) representation of new beneficiaries, kept alongside
  // the existing flat records above — never a replacement for them.
  beneficiariesFhir: `${DB_ROOT}/beneficiariesFhir`,
  notifications: `${DB_ROOT}/notifications`
} as const;

export const STORAGE_PATHS = {
  establishment: 'livelihood/establishment',
  verification: 'livelihood/verification',
  recoveryProofs: 'livelihood/recovery'
} as const;

export type UserRole = 'agent' | 'approver' | 'superadmin';
