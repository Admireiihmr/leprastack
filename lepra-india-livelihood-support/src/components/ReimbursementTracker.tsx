import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Beneficiary, EMIScheduleItem } from '../types';
import {
  CalendarClock, AlertTriangle, CheckCircle2, Clock, Wallet, UserRoundCheck, Phone
} from 'lucide-react';

interface ReimbursementTrackerProps {
  beneficiaries: Beneficiary[];
}

type RepaymentHealth = 'On Track' | 'Due Soon' | 'Overdue' | 'Completed' | 'Awaiting Disbursement';

interface Row {
  ben: Beneficiary;
  approved: number;
  recovered: number;
  outstanding: number;
  paidMilestones: number;
  totalMilestones: number;
  nextDueDate: string | null;
  nextDueAmount: number;
  overdueCount: number;
  overdueAmount: number;
  health: RepaymentHealth;
}


const todayStr = () => new Date().toISOString().slice(0, 10);

function daysBetween(a: string, b: string): number {
  const d1 = new Date(a + 'T00:00:00').getTime();
  const d2 = new Date(b + 'T00:00:00').getTime();
  return Math.round((d1 - d2) / (1000 * 60 * 60 * 24));
}

export default function ReimbursementTracker({ beneficiaries }: ReimbursementTrackerProps) {
  const { t } = useTranslation('reimbursementTracker');
  const [filter, setFilter] = useState<'all' | 'overdue' | 'dueSoon'>('all');
  const today = todayStr();

  const rows: Row[] = useMemo(() => {
    const active = beneficiaries.filter(b =>
      b.status === 'Approved' || b.status === 'Disbursed' || b.status === 'Verified Active'
    );

    return active.map((ben) => {
      const schedule: EMIScheduleItem[] = Array.isArray(ben.emiSchedule) ? ben.emiSchedule : [];
      const payments = Array.isArray(ben.payments) ? ben.payments : [];
      const approved = ben.approvedAmount || 0;
      const recovered = payments.reduce((s, p) => s + p.amount, 0);
      const outstanding = Math.max(0, approved - recovered);
      const paidMilestones = schedule.filter(s => s.status === 'Paid').length;
      const totalMilestones = schedule.length || (ben.repaymentTermMonths || 0);

      const unpaid = schedule
        .filter(s => s.status !== 'Paid')
        .sort((a, b) => a.dueDate.localeCompare(b.dueDate));

      const overdueItems = unpaid.filter(s => daysBetween(s.dueDate, today) < 0);
      const overdueAmount = overdueItems.reduce((s, i) => s + Math.max(0, i.promisedAmount - i.amountPaid), 0);

      const next = unpaid[0] || null;
      const nextDueDate = next ? next.dueDate : null;
      const nextDueAmount = next ? Math.max(0, next.promisedAmount - next.amountPaid) : 0;

      let health: RepaymentHealth;
      if (ben.status === 'Approved') {
        health = 'Awaiting Disbursement';
      } else if (unpaid.length === 0 || outstanding <= 0) {
        health = 'Completed';
      } else if (overdueItems.length > 0) {
        health = 'Overdue';
      } else if (next && daysBetween(next.dueDate, today) <= 7) {
        health = 'Due Soon';
      } else {
        health = 'On Track';
      }

      return {
        ben, approved, recovered, outstanding, paidMilestones, totalMilestones,
        nextDueDate, nextDueAmount, overdueCount: overdueItems.length, overdueAmount, health
      };
    });
  }, [beneficiaries, today]);

  const summary = useMemo(() => {
    const overdue = rows.filter(r => r.health === 'Overdue').length;
    const dueSoon = rows.filter(r => r.health === 'Due Soon').length;
    const totalOutstanding = rows.reduce((s, r) => s + r.outstanding, 0);
    const totalRecovered = rows.reduce((s, r) => s + r.recovered, 0);
    return { overdue, dueSoon, totalOutstanding, totalRecovered, count: rows.length };
  }, [rows]);

  const visibleRows = rows.filter(r => {
    if (filter === 'overdue') return r.health === 'Overdue';
    if (filter === 'dueSoon') return r.health === 'Due Soon';
    return true;
  }).sort((a, b) => {
    // Overdue first, then by next due date
    const rank: Record<RepaymentHealth, number> = {
      'Overdue': 0, 'Due Soon': 1, 'On Track': 2, 'Awaiting Disbursement': 3, 'Completed': 4
    };
    if (rank[a.health] !== rank[b.health]) return rank[a.health] - rank[b.health];
    return (a.nextDueDate || '9999').localeCompare(b.nextDueDate || '9999');
  });

  const healthBadge = (h: RepaymentHealth) => {
    switch (h) {
      case 'Overdue':
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold uppercase bg-rose-50 text-rose-700 border border-rose-100"><AlertTriangle className="w-3 h-3" />{t('badgeOverdue')}</span>;
      case 'Due Soon':
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold uppercase bg-amber-50 text-amber-700 border border-amber-100"><Clock className="w-3 h-3" />{t('badgeDueSoon')}</span>;
      case 'On Track':
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold uppercase bg-emerald-50 text-emerald-700 border border-emerald-100"><CheckCircle2 className="w-3 h-3" />{t('badgeOnTrack')}</span>;
      case 'Completed':
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold uppercase bg-teal-50 text-teal-700 border border-teal-100"><CheckCircle2 className="w-3 h-3" />{t('badgeCompleted')}</span>;
      case 'Awaiting Disbursement':
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold uppercase bg-slate-100 text-slate-600 border border-slate-200"><Wallet className="w-3 h-3" />{t('badgePreDisbursal')}</span>;
    }
  };

  return (
    <div className="space-y-4" id="reimbursement_tracker_panel">
      {/* Header */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
        <div className="p-3 bg-[#115e59] text-white border-b-2 border-[#0284c7] flex items-center gap-2">
          <CalendarClock className="w-4 h-4 text-[#0284c7]" />
          <h3 className="font-bold text-xs uppercase tracking-wider">{t('headerTitle')}</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-gray-100 text-center">
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('activePortfolios')}</span>
            <span className="font-bold text-[#115e59] text-lg font-mono">{summary.count}</span>
          </div>
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('overdueCases')}</span>
            <span className="font-bold text-rose-600 text-lg font-mono">{summary.overdue}</span>
          </div>
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('totalRecovered')}</span>
            <span className="font-bold text-emerald-700 text-lg font-mono">₹{summary.totalRecovered.toLocaleString('en-IN')}</span>
          </div>
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('outstanding')}</span>
            <span className="font-bold text-amber-600 text-lg font-mono">₹{summary.totalOutstanding.toLocaleString('en-IN')}</span>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {([
          { key: 'all', label: t('filterAll', { count: rows.length }) },
          { key: 'overdue', label: t('filterOverdue', { count: summary.overdue }) },
          { key: 'dueSoon', label: t('filterDueSoon', { count: summary.dueSoon }) }
        ] as Array<{ key: typeof filter; label: string }>).map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide rounded border transition-colors cursor-pointer ${
              filter === f.key
                ? 'bg-[#115e59] text-white border-[#115e59]'
                : 'bg-white text-gray-600 border-gray-200 hover:bg-slate-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-slate-50 text-[10px] uppercase tracking-wider text-gray-500 border-b border-gray-100">
              <th className="p-2.5 px-3">{t('colBeneficiary')}</th>
              <th className="p-2.5 px-3 text-right">{t('colApproved')}</th>
              <th className="p-2.5 px-3 text-right">{t('colRecovered')}</th>
              <th className="p-2.5 px-3 text-right">{t('colOutstanding')}</th>
              <th className="p-2.5 px-3 text-center">{t('colMilestones')}</th>
              <th className="p-2.5 px-3">{t('colNextDue')}</th>
              <th className="p-2.5 px-3">{t('colStatus')}</th>
              <th className="p-2.5 px-3">{t('colGuarantor')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {visibleRows.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-8 text-center text-gray-400">
                  {t('noMatchingPortfolios')}
                </td>
              </tr>
            ) : (
              visibleRows.map((r) => {
                const overdueDays = r.nextDueDate ? -daysBetween(r.nextDueDate, today) : 0;
                return (
                  <tr key={r.ben.id} className={`hover:bg-slate-50/60 transition-colors ${r.health === 'Overdue' ? 'bg-rose-50/30' : ''}`}>
                    <td className="p-2.5 px-3">
                      <span className="font-bold text-gray-900 block">{r.ben.name}</span>
                      <span className="text-[10px] text-gray-400 italic">{r.ben.businessName}</span>
                    </td>
                    <td className="p-2.5 px-3 text-right font-mono text-gray-700">₹{r.approved.toLocaleString('en-IN')}</td>
                    <td className="p-2.5 px-3 text-right font-mono text-emerald-700">₹{r.recovered.toLocaleString('en-IN')}</td>
                    <td className="p-2.5 px-3 text-right font-mono font-bold text-amber-600">₹{r.outstanding.toLocaleString('en-IN')}</td>
                    <td className="p-2.5 px-3 text-center">
                      <span className="font-semibold text-gray-700">{r.paidMilestones}/{r.totalMilestones}</span>
                      <span className="block text-[11px] text-gray-400">{t('moTerm', { months: r.ben.repaymentTermMonths || r.totalMilestones })}</span>
                    </td>
                    <td className="p-2.5 px-3">
                      {r.health === 'Completed' ? (
                        <span className="text-teal-600 font-semibold">{t('fullyRecovered')}</span>
                      ) : r.nextDueDate ? (
                        <div>
                          <span className="font-mono text-gray-800 block">{r.nextDueDate}</span>
                          <span className="text-[10px] text-gray-500">₹{r.nextDueAmount.toLocaleString('en-IN')}
                            {r.health === 'Overdue' && (
                              <span className="text-rose-600 font-bold"> {t('lateBy', { days: overdueDays })}</span>
                            )}
                          </span>
                        </div>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="p-2.5 px-3">{healthBadge(r.health)}</td>
                    <td className="p-2.5 px-3">
                      {r.ben.guarantor && r.ben.guarantor.name ? (
                        <div className="text-[11px]">
                          <span className="flex items-center gap-1 font-semibold text-violet-800">
                            <UserRoundCheck className="w-3 h-3" />{r.ben.guarantor.name}
                          </span>
                          <span className="text-[10px] text-gray-500 block">{r.ben.guarantor.relationship}</span>
                          {r.ben.guarantor.contactNumber && (
                            <span className="flex items-center gap-1 font-mono text-gray-600 mt-0.5">
                              <Phone className="w-2.5 h-2.5" />{r.ben.guarantor.contactNumber}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-[10px] text-gray-400 italic">{t('noGuarantorOnFile')}</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
