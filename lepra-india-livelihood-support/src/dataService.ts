import { ref, push, set, update, onValue, off, DataSnapshot } from 'firebase/database';
import { db, DB_PATHS } from './firebase';
import { Beneficiary, Notification } from './types';
import { beneficiaryToFhirPatient } from './fhir';

function snapshotToArray<T extends { id: string }>(snap: DataSnapshot): T[] {
  const out: T[] = [];
  snap.forEach((child) => {
    const val = child.val();
    if (val) out.push({ ...(val as T), id: child.key as string });
  });
  return out;
}

function stripUndefined<T>(value: T): T {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(stripUndefined) as unknown as T;
  if (typeof value !== 'object') return value;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (v === undefined) continue;
    out[k] = stripUndefined(v);
  }
  return out as T;
}




export function subscribeBeneficiaries(cb: (rows: Beneficiary[]) => void) {
  const r = ref(db, DB_PATHS.beneficiaries);
  const handler = (snap: DataSnapshot) => {
    const list = snapshotToArray<Beneficiary>(snap);
    list.sort((a, b) => (b.registeredAt || '').localeCompare(a.registeredAt || ''));
    cb(list);
  };
  onValue(r, handler);
  return () => off(r, 'value', handler);
}





export function subscribeNotifications(cb: (rows: Notification[]) => void) {
  const r = ref(db, DB_PATHS.notifications);
  const handler = (snap: DataSnapshot) => {
    const list = snapshotToArray<Notification>(snap);
    list.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
    cb(list);
  };
  onValue(r, handler);
  return () => off(r, 'value', handler);
}

export async function addBeneficiary(ben: Omit<Beneficiary, 'id'>): Promise<string> {
  const r = push(ref(db, DB_PATHS.beneficiaries));
  const id = r.key as string;
  await set(r, stripUndefined(ben));

  // FHIR view of this beneficiary, written to its own node. Existing data at
  // DB_PATHS.beneficiaries is never modified or removed by this.
  const fhirPatient = beneficiaryToFhirPatient(id, { ...ben, id });
  await set(ref(db, `${DB_PATHS.beneficiariesFhir}/${id}`), stripUndefined(fhirPatient));

  return id;
}



export async function updateBeneficiary(id: string, updates: Partial<Beneficiary>): Promise<void> {
  const { id: _ignore, ...rest } = updates as Beneficiary;
  await update(ref(db, `${DB_PATHS.beneficiaries}/${id}`), stripUndefined(rest));
}

export async function addNotification(n: Omit<Notification, 'id'>): Promise<string> {
  const r = push(ref(db, DB_PATHS.notifications));
  await set(r, stripUndefined(n));
  return r.key as string;
}

export async function markNotificationRead(id: string): Promise<void> {
  await update(ref(db, `${DB_PATHS.notifications}/${id}`), { read: true });
}

export async function clearNotificationsForRole(notifications: Notification[], role: 'Admin' | 'Agent'): Promise<void> {
  const updates: Record<string, null> = {};
  notifications.forEach((n) => {
    if (n.targetRole === role) updates[`${DB_PATHS.notifications}/${n.id}`] = null;
  });
  if (Object.keys(updates).length > 0) {
    await update(ref(db), updates);
  }
}
