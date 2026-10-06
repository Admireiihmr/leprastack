import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import DashboardStats from './components/DashboardStats';
import { Beneficiary } from './types';
import './i18n/config';
import './index.css';

function mkBen(overrides: Partial<Beneficiary>): Beneficiary {
  return {
    id: Math.random().toString(36).slice(2),
    type: 'Individual',
    name: 'Sample Person',
    contactNumber: '9999999999',
    gender: 'Male',
    age: 30,
    address: 'Some address',
    district: 'Guntur',
    state: 'Andhra Pradesh',
    projectName: 'Livelihood Project',
    diseaseType: 'Leprosy',
    diagnosisYear: 2020,
    treatmentStatus: 'Completed',
    physicalLimitations: [],
    businessName: 'Tea Stall',
    businessSector: 'Food',
    requestedAmount: 20000,
    businessDescription: 'desc',
    expectedMonthlyRevenue: 5000,
    status: 'Disbursed',
    registeredAt: new Date().toISOString(),
    registeredByAgent: 'Agent 1',
    approvedAmount: 20000,
    emiSchedule: [],
    payments: [],
    ...overrides,
  };
}

const beneficiaries: Beneficiary[] = [
  mkBen({ name: 'Ravi Kumar', district: 'Guntur', state: 'Andhra Pradesh' }),
  mkBen({ name: 'Lakshmi Devi', district: 'Guntur', state: 'Andhra Pradesh', diseaseType: 'LF' }),
  mkBen({ name: 'Suresh Babu', district: 'Krishna', state: 'Andhra Pradesh', diseaseType: 'Leptospirosis' }),
  mkBen({ name: 'Anitha Reddy', district: 'Krishna', state: 'Andhra Pradesh' }),
  mkBen({ name: 'Mohan Rao', district: 'Krishna', state: 'Andhra Pradesh' }),
];

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div style={{ padding: 16 }}>
      <DashboardStats beneficiaries={beneficiaries} />
    </div>
  </StrictMode>,
);
