import React, { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Beneficiary, EMIScheduleItem, PaymentRecord } from '../types';
import DashboardStats from './DashboardStats';
import { normalizeStateName } from '../utils/normalizeState';
import { normalizeDistrictName } from '../utils/districts';
import {
  Users, CheckCircle2, XCircle, TrendingUp, DollarSign, Calendar,
  MapPin, NotebookTabs, ArrowRight, ShieldCheck, Award, MessageSquare, Plus, Save,
  ShieldAlert, CalendarRange, LineChart
} from 'lucide-react';

interface AdminDashboardProps {
  beneficiaries: Beneficiary[];
  onUpdateBeneficiary: (updated: Beneficiary) => void | Promise<void>;
  onSendNotification: (title: string, message: string, type: 'info' | 'success' | 'warning', target: 'Admin' | 'Agent') => void;
  mode?: 'approver' | 'superadmin';
}

export default function AdminDashboard({
  beneficiaries,
  onUpdateBeneficiary,
  onSendNotification,
  mode = 'superadmin'
}: AdminDashboardProps) {
  const { t } = useTranslation('adminDashboard');
  const showLedger = mode === 'superadmin';
  // Navigation tabs
  const [adminTab, setAdminTab] = useState<'pending' | 'emi'>('pending');

  // Currently reviewed application details
  const [reviewingBenId, setReviewingBenId] = useState<string | null>(null);
  const [approvedSupportAmount, setApprovedSupportAmount] = useState<number>(15000);
  const [repaymentTermMonths, setRepaymentTermMonths] = useState<number>(10);
  const [adminReviewNotes, setAdminReviewNotes] = useState<string>('');
  
  // Custom manual EMI schedules during SOP adjustment
  const [selectedEmiBenId, setSelectedEmiBenId] = useState<string | null>(null);
  const [manualEmiIndex, setManualEmiIndex] = useState<number | null>(null);
  const [manualEmiAmount, setManualEmiAmount] = useState<number>(0);

  // Quick payout disbursement state
  const [confirmingPayoutId, setConfirmingPayoutId] = useState<string | null>(null);

  // New Payment logger triggers
  const [loggingPaymentForId, setLoggingPaymentForId] = useState<string | null>(null);
  const [paymentAmountPaid, setPaymentAmountPaid] = useState<number>(0);
  const [paymentInstallmentIndex, setPaymentInstallmentIndex] = useState<number>(1);
  const [receiptNumber, setReceiptNumber] = useState<string>('');
  const [paymentNote, setPaymentNote] = useState<string>('');

  // Welfare-only beneficiaries (added directly from the Welfare Schemes module) never
  // go through the livelihood loan pipeline, so they're excluded from both queues here.
  const pendingList = beneficiaries.filter(b => b.status === 'Pending Eligibility Review' && !b.isWelfareOnly);
  const activeRecoveryList = beneficiaries.filter(b =>
    (b.status === 'Approved' || b.status === 'Disbursed' || b.status === 'Verified Active') && !b.isWelfareOnly
  );

  // Handler: Decision (Approve)
  const handleApproveApplication = async (ben: Beneficiary) => {
    // Generate initial flat EMI schedule according to SOP
    const flatEMI = Math.round(approvedSupportAmount / repaymentTermMonths);
    const schedule: EMIScheduleItem[] = [];
    
    // Set due dates separated by 30 days starting 30 days from now
    const startDate = new Date();
    for (let i = 1; i <= repaymentTermMonths; i++) {
      const dueDate = new Date();
      dueDate.setDate(startDate.getDate() + (30 * i));
      
      schedule.push({
        index: i,
        dueDate: dueDate.toISOString().slice(0, 10),
        promisedAmount: i === repaymentTermMonths 
          ? approvedSupportAmount - (flatEMI * (repaymentTermMonths - 1)) 
          : flatEMI, // ensure final balances match exactly due to rounding
        amountPaid: 0,
        status: 'Pending'
      });
    }

    const updatedBen: Beneficiary = {
      ...ben,
      status: 'Approved',
      approvedAmount: approvedSupportAmount,
      repaymentTermMonths: repaymentTermMonths,
      monthlyRepaymentEMI: flatEMI,
      emiSchedule: schedule,
      payments: [],
      approvalDate: new Date().toISOString()
    };

    try {
      await onUpdateBeneficiary(updatedBen);
    } catch (err) {
      console.error('Failed to approve application', err);
      alert(t('alerts.approveError'));
      return;
    }
    setReviewingBenId(null);
    setAdminReviewNotes('');

    // Send notifications to dashboard
    onSendNotification(
      "Intake Plan Approved",
      `Plan [${ben.businessName}] for beneficiary ${ben.name} Approved for support of ₹${approvedSupportAmount.toLocaleString('en-IN')}. Next: Process Disbursement.`,
      "success",
      "Agent"
    );
  };

  // Handler: Decision (Reject)
  const handleRejectApplication = async (ben: Beneficiary, reason: string) => {
    const updatedBen: Beneficiary = {
      ...ben,
      status: 'Rejected',
      rejectionReason: reason || "Does not satisfy eligibility criteria or business plan requires expansion"
    };

    try {
      await onUpdateBeneficiary(updatedBen);
    } catch (err) {
      console.error('Failed to reject application', err);
      alert(t('alerts.rejectError'));
      return;
    }
    setReviewingBenId(null);
    setAdminReviewNotes('');

    onSendNotification(
      "Application Needs Correction",
      `The plan submitted for ${ben.name} has been returned by admin. Reason: ${reason}`,
      "warning",
      "Agent"
    );
  };

  // Handler: Mark as Disbursed when funds are physically handed over/deposited
  const handleDisburseSupport = async (ben: Beneficiary) => {
    const updatedBen: Beneficiary = {
      ...ben,
      status: 'Disbursed',
      disbursementDate: new Date().toISOString()
    };

    try {
      await onUpdateBeneficiary(updatedBen);
    } catch (err) {
      console.error('Failed to disburse support', err);
      alert(t('alerts.disburseError'));
      return;
    }
    setConfirmingPayoutId(null);

    // Send user notification trigger!
    onSendNotification(
      "Support Material & Fund Disbursed",
      `Funds disbursed for ${ben.name}. Auto-alert sent to beneficiary. Agent has been instructed to track starting geo-tag.`,
      "success",
      "Agent"
    );
  };

  // Handler: Adjust unique EMI installment amounts (SOP compliant slider / custom scheduler)
  const handleSaveEmiAdjustment = async (ben: Beneficiary, scheduleIdx: number, newAmt: number) => {
    const schedule = Array.isArray(ben.emiSchedule) ? [...ben.emiSchedule] : [];
    const targetItem = schedule.find(item => item.index === scheduleIdx);
    if (!targetItem) return;

    const oldAmt = targetItem.promisedAmount;
    const diff = newAmt - oldAmt;

    // Adjust target item
    targetItem.promisedAmount = newAmt;
    targetItem.status = 'Adjusted';

    // To comply with SOP, overall total approved funds must remain matched.
    // Redistribute the difference (diff) across other non-paid downstream installments
    const nonPaidInstallments = schedule.filter(item => 
      item.index !== scheduleIdx && item.status !== 'Paid'
    );

    if (nonPaidInstallments.length > 0) {
      // split the reduction/increase across remaining unpaid milestones
      const partialAdjustment = Math.round(diff / nonPaidInstallments.length);
      let adjustedCount = 0;
      
      nonPaidInstallments.forEach((item, idx) => {
        if (idx === nonPaidInstallments.length - 1) {
          // ensure precision match
          const totalAccumulated = partialAdjustment * (nonPaidInstallments.length - 1);
          item.promisedAmount = Math.max(0, item.promisedAmount - (diff - totalAccumulated));
        } else {
          item.promisedAmount = Math.max(0, item.promisedAmount - partialAdjustment);
        }
        item.status = 'Adjusted';
      });
    }

    const updated: Beneficiary = {
      ...ben,
      emiSchedule: schedule
    };

    try {
      await onUpdateBeneficiary(updated);
    } catch (err) {
      console.error('Failed to save EMI adjustment', err);
      alert(t('alerts.emiAdjustError'));
      return;
    }
    setManualEmiIndex(null);

    onSendNotification(
      "SOP Compliance Recovery Plan Adjusted",
      `Admin adjusted EMI milestone #${scheduleIdx} for ${ben.name} to ₹${newAmt}. Dynamic schedule recalculated.`,
      "info",
      "Admin"
    );
  };

  // Handler: Log repayment receipt
  const handleLogRepayment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loggingPaymentForId) return;

    const target = beneficiaries.find(b => b.id === loggingPaymentForId);
    if (!target) return;

    if (!paymentAmountPaid || paymentAmountPaid <= 0) {
      alert(t('alerts.invalidAmount'));
      return;
    }

    const payment: PaymentRecord = {
      id: `PAY-${Math.floor(1001 + Math.random() * 8999)}`,
      installmentIndex: paymentInstallmentIndex,
      amount: paymentAmountPaid,
      datePaid: new Date().toISOString(),
      receiptNumber: receiptNumber || `RCP-${Math.floor(10000 + Math.random() * 90000)}`,
      loggedBy: "Admin Portal",
      notes: paymentNote
    };

    // Update Schedule item payment count (defensive: emiSchedule may be missing/non-array on legacy records)
    const existingSchedule = Array.isArray(target.emiSchedule) ? target.emiSchedule : [];
    const updatedSchedule = existingSchedule.map(item => {
      if (item.index === paymentInstallmentIndex) {
        const totalPaid = item.amountPaid + paymentAmountPaid;
        return {
          ...item,
          amountPaid: totalPaid,
          status: totalPaid >= item.promisedAmount ? 'Paid' as const : 'Pending' as const
        };
      }
      return item;
    });

    const existingPayments = Array.isArray(target.payments) ? target.payments : [];
    const updatedBeneficiary: Beneficiary = {
      ...target,
      emiSchedule: updatedSchedule,
      payments: [...existingPayments, payment]
    };

    // Persist first; only clear the form / notify if the write actually succeeded.
    try {
      await onUpdateBeneficiary(updatedBeneficiary);
    } catch (err) {
      console.error('Failed to log repayment', err);
      alert(t('alerts.repaymentError'));
      return;
    }

    // Clear log form
    setLoggingPaymentForId(null);
    setPaymentAmountPaid(0);
    setReceiptNumber('');
    setPaymentNote('');

    onSendNotification(
      "Payment Logged Successfully",
      `Verification payout logged for ${target.name} towards installment #${paymentInstallmentIndex}. Receipt registered.`,
      "success",
      "Admin"
    );
  };

  const getStatusStyle = (status: Beneficiary['status']) => {
    switch (status) {
      case 'Pending Eligibility Review': return 'indigo';
      case 'Approved': return 'emerald';
      case 'Disbursed': return 'amber';
      case 'Verified Active': return 'teal';
      case 'Rejected': return 'rose';
    }
  };

  const getStatusLabel = (status: Beneficiary['status']) => {
    switch (status) {
      case 'Pending Eligibility Review': return t('statusBadges.pendingEligibilityReview');
      case 'Approved': return t('statusBadges.approved');
      case 'Disbursed': return t('statusBadges.disbursed');
      case 'Verified Active': return t('statusBadges.verifiedActive');
      case 'Rejected': return t('statusBadges.rejected');
      default: return status;
    }
  };

  const effectiveTab = showLedger ? adminTab : 'pending';

  return (
    <div className="space-y-4" id="admin_dashboard_wrapper">
      {/* Sub tabs navigation */}
      {showLedger && (
        <div className="flex border-b border-gray-200 bg-white p-1 rounded-lg shadow-2xs gap-1">
          <button
            onClick={() => setAdminTab('pending')}
            className={`flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-wide rounded transition-all cursor-pointer ${
              adminTab === 'pending'
                ? 'bg-[#115e59] text-[#0284c7] border-l-4 border-[#0284c7]'
                : 'text-[#171717] hover:bg-slate-50'
            }`}
            id="admin_verification_tab"
          >
            <ShieldAlert className="w-3.5 h-3.5" />
            {t('tabs.eligibilityReviews', { count: pendingList.length })}
          </button>
          <button
            onClick={() => setAdminTab('emi')}
            className={`flex-1 sm:flex-none flex items-center justify-center gap-2 px-4 py-2 font-bold text-xs uppercase tracking-wide rounded transition-all cursor-pointer ${
              adminTab === 'emi'
                ? 'bg-[#115e59] text-[#0284c7] border-l-4 border-[#0284c7]'
                : 'text-[#171717] hover:bg-slate-50'
            }`}
            id="admin_ledger_tab"
          >
            <CalendarRange className="w-3.5 h-3.5" />
            {t('tabs.activeLoanRecoveryLedger')}
          </button>
        </div>
      )}

      {effectiveTab === 'pending' ? (
        /* Workspace 1: Verification panel */
        <div className="space-y-4" id="admin_verifications_pool">
          <div className="bg-white p-3 rounded-lg border border-gray-200 flex items-center justify-between shadow-xs">
            <div>
              <h4 className="font-bold text-[#115e59] text-xs uppercase tracking-wide">{t('verificationPanel.heading')}</h4>
              <p className="text-[11px] text-gray-500">{t('verificationPanel.subtitle')}</p>
            </div>
            {pendingList.length > 0 && (
              <span className="bg-sky-50 text-[#0284c7] border border-sky-100 font-bold px-2 py-0.5 rounded text-[10px] uppercase tracking-wider">
                {t('verificationPanel.pendingActions', { count: pendingList.length })}
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {pendingList.length === 0 ? (
              <div className="col-span-full border border-dashed border-gray-200 p-12 text-center rounded-xl bg-white text-gray-400">
                <ShieldCheck className="w-12 h-12 stroke-1 text-gray-300 mx-auto mb-2" />
                {t('verificationPanel.emptyState')}
              </div>
            ) : (
              pendingList.map((ben) => (
                <div key={ben.id} className="bg-white border border-gray-100 shadow-xs hover:shadow-sm transition-all rounded-xl overflow-hidden flex flex-col justify-between" id={`review_card_${ben.id}`}>
                  {/* Top sector */}
                  <div className="p-5 space-y-4">
                    <div className="flex justify-between items-start">
                      <div>
                        <h4 className="font-bold text-gray-900 text-sm">{ben.name}</h4>
                        <span className="text-[10px] text-gray-400 font-mono">{t('verificationPanel.appIdLabel', { id: ben.id })}</span>
                      </div>
                      <span className="text-[10px] bg-rose-50 text-rose-800 font-semibold px-2 py-0.5 rounded border border-rose-100">
                        {ben.diseaseType}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 pb-3 border-b border-gray-50 text-xs">
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('verificationPanel.livelihoodFormLabel')}</span>
                        <span className="font-semibold text-gray-700">
                          {ben.type} {t('verificationPanel.supportSuffix')}
                          {ben.type === 'Group' && !!ben.groupMembersCount && (
                            <span className="ml-1 text-[10px] text-sky-700 font-bold">
                              ({t('reviewModal.memberCountBadge', { count: ben.groupMembersCount })})
                            </span>
                          )}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('verificationPanel.groundLocationLabel')}</span>
                        <span className="font-semibold text-gray-700">{normalizeDistrictName(ben.district, ben.state)}, {normalizeStateName(ben.state)}</span>
                      </div>
                    </div>

                    {/* Proposed Business */}
                    <div>
                      <span className="text-[10px] text-indigo-600 font-bold uppercase tracking-wider block mb-1">{t('verificationPanel.proposedBusinessLabel')}</span>
                      <h5 className="font-semibold text-gray-800 text-xs">{ben.businessName}</h5>
                      <p className="text-xs text-gray-600 italic line-clamp-2 mt-1">"{ben.businessDescription}"</p>
                      <div className="flex items-center justify-between bg-slate-50 p-2 rounded-lg mt-3 text-xs">
                        <div>
                          <span className="text-gray-400 block text-[10px]">{t('verificationPanel.capitalRequestedLabel')}</span>
                          <span className="font-bold text-gray-900 font-mono">₹{ben.requestedAmount.toLocaleString('en-IN')}</span>
                        </div>
                        <div>
                          <span className="text-gray-400 block text-[10px]">{t('verificationPanel.expProfitPerMonthLabel')}</span>
                          <span className="font-medium text-emerald-600 font-mono">₹{ben.expectedMonthlyRevenue.toLocaleString('en-IN')}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Actions footer */}
                  <div className="bg-slate-50 border-t border-gray-50 p-4 shrink-0">
                    <button
                      onClick={() => {
                        setReviewingBenId(ben.id);
                        setApprovedSupportAmount(ben.requestedAmount);
                        setRepaymentTermMonths(10);
                      }}
                      className="w-full text-center bg-teal-800 hover:bg-teal-900 text-white font-semibold text-xs py-2 rounded-lg transition-colors cursor-pointer"
                    >
                      {t('verificationPanel.conductEvaluationBtn')}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Dialog popup modal for reviewing individual eligibility */}
          {reviewingBenId && (() => {
            const currentBen = beneficiaries.find(b => b.id === reviewingBenId);
            if (!currentBen) return null;
            return (
              <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div className="bg-white rounded-xl shadow-card border border-gray-100 max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                  <div className="p-4 bg-teal-950 text-white flex justify-between items-center sticky top-0">
                    <h3 className="font-semibold text-sm">{t('reviewModal.title')}</h3>
                    <button
                      onClick={() => setReviewingBenId(null)}
                      className="text-white hover:text-red-400 text-sm font-semibold cursor-pointer"
                    >
                      {t('reviewModal.close')}
                    </button>
                  </div>

                  <div className="p-6 space-y-6">
                    {/* Identification detail summary */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                      <div>
                        <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.beneficiaryNameLabel')}</span>
                        <span className="font-bold text-gray-900">{currentBen.name}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.mobileContactLabel')}</span>
                        <span className="font-mono text-gray-700">{currentBen.contactNumber}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.diseaseStatusLabel')}</span>
                        <span className="font-semibold text-rose-700">{currentBen.diseaseType} ({currentBen.treatmentStatus})</span>
                      </div>
                      <div>
                        <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.agentRegisteredLabel')}</span>
                        <span className="font-semibold text-gray-700">{currentBen.registeredByAgent}</span>
                      </div>
                    </div>

                    {/* Cooperative Group / JLG member details */}
                    {currentBen.type === 'Group' && (
                      <div className="bg-sky-50/60 p-4 rounded-lg text-xs space-y-3 border border-sky-200">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-sky-800 text-[11px] uppercase block tracking-wider">{t('reviewModal.groupDetailsLabel')}</span>
                          {!!currentBen.groupMembersCount && (
                            <span className="text-[10px] bg-sky-100 text-sky-800 font-bold px-2 py-0.5 rounded">
                              {t('reviewModal.memberCountBadge', { count: currentBen.groupMembersCount })}
                            </span>
                          )}
                        </div>
                        {currentBen.groupMembers && currentBen.groupMembers.length > 0 ? (
                          <div className="space-y-1.5">
                            {currentBen.groupMembers.map((m, i) => (
                              <div key={i} className="bg-white p-2 rounded border border-sky-100 space-y-2">
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                                  <div>
                                    <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.memberLabel', { index: i + 1 })}</span>
                                    <span className="font-semibold text-gray-800">{m.name || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.ageLabel')}</span>
                                    <span className="font-semibold text-gray-800">{m.age || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.genderLabel')}</span>
                                    <span className="font-semibold text-gray-800">{m.gender}</span>
                                  </div>
                                  <div>
                                    <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.contactLabel')}</span>
                                    <span className="font-mono text-gray-700">{m.contactNumber || '—'}</span>
                                  </div>
                                </div>
                                {m.diseaseType && (
                                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 border-t border-sky-50 pt-2">
                                    <div>
                                      <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.diseaseTypeLabel')}</span>
                                      <span className={`font-semibold ${m.diseaseType === 'LF' ? 'text-teal-700' : 'text-rose-700'}`}>{m.diseaseType}</span>
                                    </div>
                                    <div>
                                      <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.yearDiagnosedLabel')}</span>
                                      <span className="font-semibold text-gray-800">{m.diagnosisYear || '—'}</span>
                                    </div>
                                    <div>
                                      <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.treatmentStatusLabel')}</span>
                                      <span className="font-semibold text-gray-800">{m.treatmentStatus || '—'}</span>
                                    </div>
                                    <div>
                                      <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.physicalLimitationsLabel')}</span>
                                      <span className="font-semibold text-gray-800">
                                        {!m.physicalLimitations || m.physicalLimitations.length === 0 ? t('reviewModal.noneIdentified') : m.physicalLimitations.join(', ')}
                                      </span>
                                    </div>
                                    {m.diseaseType === 'LF' && m.lfIndicators && (
                                      <div className="col-span-2 md:col-span-4 grid grid-cols-2 md:grid-cols-4 gap-2 bg-teal-50/50 rounded p-2 mt-1">
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.gradeOfDiseaseLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.lfIndicators.diseaseGrade}</span>
                                        </div>
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.mobilityStatusLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.lfIndicators.mobilityStatus}</span>
                                        </div>
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.acuteAttacksLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.lfIndicators.acuteAttackFrequency}</span>
                                        </div>
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.entryLesionsLabel')}</span>
                                          <span className={`font-semibold ${m.lfIndicators.entryLesionsPresent ? 'text-rose-700' : 'text-emerald-700'}`}>
                                            {m.lfIndicators.entryLesionsPresent ? t('reviewModal.present') : t('reviewModal.absent')}
                                          </span>
                                        </div>
                                      </div>
                                    )}
                                    {m.diseaseType === 'HIV/AIDS' && m.hivIndicators && (
                                      <div className="col-span-2 md:col-span-4 grid grid-cols-2 md:grid-cols-4 gap-2 bg-violet-50/50 rounded p-2 mt-1">
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.hrgMemberLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.hivIndicators.isHrgMember ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                                        </div>
                                        {m.hivIndicators.isHrgMember && (
                                          <div>
                                            <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.hrgTypeLabel')}</span>
                                            <span className="font-semibold text-gray-800">{m.hivIndicators.hrgType || t('reviewModal.notApplicable')}</span>
                                          </div>
                                        )}
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.livingWithHivLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.hivIndicators.isLivingWithHiv ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                                        </div>
                                        {m.hivIndicators.isLivingWithHiv && (
                                          <>
                                            <div>
                                              <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.onArtLabel')}</span>
                                              <span className="font-semibold text-gray-800">{m.hivIndicators.onArt ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                                            </div>
                                            {m.hivIndicators.onArt && (
                                              <div>
                                                <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.artDurationLabel')}</span>
                                                <span className="font-semibold text-gray-800">{m.hivIndicators.artDuration || t('reviewModal.notApplicable')}</span>
                                              </div>
                                            )}
                                          </>
                                        )}
                                        <div>
                                          <span className="text-gray-400 block text-[11px] uppercase font-medium">{t('reviewModal.safeSexLabel')}</span>
                                          <span className="font-semibold text-gray-800">{m.hivIndicators.practicesSafeSex ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-500 italic block">{t('reviewModal.noMemberDetails')}</span>
                        )}
                      </div>
                    )}

                    {/* Limitations check */}
                    <div className="bg-slate-50 p-4 rounded-lg text-xs space-y-2 border border-gray-100">
                      <span className="font-bold text-gray-700 text-[11px] uppercase block tracking-wider">{t('reviewModal.physicalLimitationsLabel')}</span>
                      <div className="flex flex-wrap gap-2">
                        {!currentBen.physicalLimitations || currentBen.physicalLimitations.length === 0 ? (
                          <span className="text-gray-500 italic block">{t('reviewModal.noneIdentified')}</span>
                        ) : (
                          currentBen.physicalLimitations.map((lim, i) => (
                            <span key={i} className="bg-sky-100 text-sky-800 font-semibold px-2 py-1 rounded">
                              {lim}
                            </span>
                          ))
                        )}
                      </div>
                    </div>

                    {/* LF (Lymphatic Filariasis) impairment indicators */}
                    {currentBen.diseaseType === 'LF' && currentBen.lfIndicators && (
                      <div className="bg-teal-50/60 p-4 rounded-lg text-xs space-y-2 border border-teal-200">
                        <span className="font-bold text-teal-800 text-[11px] uppercase block tracking-wider">{t('reviewModal.lfIndicatorsLabel')}</span>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.gradeOfDiseaseLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.lfIndicators.diseaseGrade}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.mobilityStatusLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.lfIndicators.mobilityStatus}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.acuteAttacksLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.lfIndicators.acuteAttackFrequency}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.entryLesionsLabel')}</span>
                            <span className={`font-semibold ${currentBen.lfIndicators.entryLesionsPresent ? 'text-rose-700' : 'text-emerald-700'}`}>
                              {currentBen.lfIndicators.entryLesionsPresent ? t('reviewModal.present') : t('reviewModal.absent')}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* HIV/AIDS & High-Risk Group (HRG) indicators */}
                    {currentBen.diseaseType === 'HIV/AIDS' && currentBen.hivIndicators && (
                      <div className="bg-violet-50/60 p-4 rounded-lg text-xs space-y-2 border border-violet-200">
                        <span className="font-bold text-violet-800 text-[11px] uppercase block tracking-wider">{t('reviewModal.hivIndicatorsLabel')}</span>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.hrgMemberLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.hivIndicators.isHrgMember ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                          </div>
                          {currentBen.hivIndicators.isHrgMember && (
                            <div>
                              <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.hrgTypeLabel')}</span>
                              <span className="font-semibold text-gray-800">{currentBen.hivIndicators.hrgType || t('reviewModal.notApplicable')}</span>
                            </div>
                          )}
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.livingWithHivLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.hivIndicators.isLivingWithHiv ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                          </div>
                          {currentBen.hivIndicators.isLivingWithHiv && (
                            <>
                              <div>
                                <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.yearOfDiagnosisLabel')}</span>
                                <span className="font-semibold text-gray-800">{currentBen.hivIndicators.yearOfDiagnosis || t('reviewModal.notApplicable')}</span>
                              </div>
                              <div>
                                <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.onArtLabel')}</span>
                                <span className="font-semibold text-gray-800">{currentBen.hivIndicators.onArt ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                              </div>
                              {currentBen.hivIndicators.onArt && (
                                <div>
                                  <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.artDurationLabel')}</span>
                                  <span className="font-semibold text-gray-800">{currentBen.hivIndicators.artDuration || t('reviewModal.notApplicable')}</span>
                                </div>
                              )}
                            </>
                          )}
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.safeSexLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.hivIndicators.practicesSafeSex ? t('reviewModal.yes') : t('reviewModal.no')}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Guarantor / co-applicant details */}
                    {currentBen.guarantor && currentBen.guarantor.name && (
                      <div className="bg-violet-50/60 p-4 rounded-lg text-xs space-y-2 border border-violet-200">
                        <span className="font-bold text-violet-800 text-[11px] uppercase block tracking-wider">{t('reviewModal.guarantorLabel')}</span>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.nameLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.guarantor.name}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.relationshipLabel')}</span>
                            <span className="font-semibold text-gray-800">{currentBen.guarantor.relationship || '—'}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.contactLabel')}</span>
                            <span className="font-mono text-gray-700">{currentBen.guarantor.contactNumber || '—'}</span>
                          </div>
                          {currentBen.guarantor.idProof && (
                            <div>
                              <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.idRefLabel')}</span>
                              <span className="font-mono text-gray-700">{currentBen.guarantor.idProof}</span>
                            </div>
                          )}
                          {currentBen.guarantor.address && (
                            <div className="col-span-2 md:col-span-4">
                              <span className="text-gray-400 text-[10px] block uppercase font-medium">{t('reviewModal.addressLabel')}</span>
                              <span className="font-semibold text-gray-800">{currentBen.guarantor.address}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* business plan details */}
                    <div>
                      <span className="font-bold text-gray-700 text-[11px] uppercase block tracking-wider mb-2">{t('reviewModal.enterpriseProposalLabel')}</span>
                      <div className="p-4 border border-gray-100 rounded-lg space-y-3">
                        <div>
                          <span className="text-indigo-600 text-xs font-semibold block mb-0.5">{currentBen.businessSector}</span>
                          <h4 className="font-bold text-slate-800 text-sm mb-2">{currentBen.businessName}</h4>
                          <p className="text-slate-600 text-xs leading-relaxed">"{currentBen.businessDescription}"</p>
                        </div>

                        {/* Display Proof of Business Establishment & Geotag if logged at intake */}
                        {currentBen.businessEstablishmentPhotoUrl && (
                          <div className="bg-slate-50 p-2.5 rounded-lg border border-gray-200 mt-2 space-y-2 animate-fade-in">
                            <span className="text-[10px] font-bold text-[#115e59] uppercase tracking-wide block">{t('reviewModal.onSiteProofLabel')}</span>
                            <img
                              src={currentBen.businessEstablishmentPhotoUrl}
                              alt={t('reviewModal.establishmentPhotoAlt')}
                              className="w-full h-32 object-cover rounded border border-gray-300 shadow-3xs"
                              referrerPolicy="no-referrer"
                            />
                            {currentBen.establishmentLatitude && (
                              <div className="flex items-center gap-1 font-mono text-xs text-gray-500 bg-white px-2 py-1 rounded border border-gray-150 justify-center">
                                <MapPin className="w-3.5 h-3.5 text-rose-500 shrink-0" />
                                {t('reviewModal.latLng', { lat: currentBen.establishmentLatitude, longitude: currentBen.establishmentLongitude })}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Adjust approval support configuration */}
                    <div className="bg-indigo-50/50 p-5 rounded-lg border border-indigo-100 space-y-4">
                      <span className="font-bold text-indigo-900 text-xs uppercase block tracking-wider">{t('reviewModal.sopConfigLabel')}</span>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs font-semibold text-indigo-950 mb-1.5">{t('reviewModal.approvedAmountLabel')}</label>
                          <input
                            type="number"
                            step={1000}
                            min={5000}
                            max={currentBen.type === 'Group' ? undefined : 50000}
                            value={approvedSupportAmount}
                            onChange={(e) => setApprovedSupportAmount(Number(e.target.value))}
                            className="w-full text-sm font-bold border border-gray-200 p-2 rounded bg-white text-indigo-700 font-mono"
                          />
                          <span className="text-[10px] text-gray-400 block mt-1">{t('reviewModal.requestedAmountNote', { amount: currentBen.requestedAmount.toLocaleString('en-IN') })}</span>
                        </div>

                        <div>
                          <label className="block text-xs font-semibold text-indigo-950 mb-1.5">{t('reviewModal.repaymentTermLabel')}</label>
                          <select
                            value={repaymentTermMonths}
                            onChange={(e) => setRepaymentTermMonths(Number(e.target.value))}
                            className="w-full text-sm border border-gray-200 p-2 rounded bg-white"
                          >
                            <option value={6}>{t('reviewModal.termOptions.m6')}</option>
                            <option value={10}>{t('reviewModal.termOptions.m10')}</option>
                            <option value={12}>{t('reviewModal.termOptions.m12')}</option>
                            <option value={15}>{t('reviewModal.termOptions.m15')}</option>
                            <option value={18}>{t('reviewModal.termOptions.m18')}</option>
                          </select>
                        </div>
                      </div>

                      {/* Display prospective interest-free EMI */}
                      <div className="pt-3 border-t border-indigo-200/50 flex justify-between items-center text-xs">
                        <span className="font-semibold text-indigo-900">{t('reviewModal.prospectiveEmiLabel')}</span>
                        <span className="font-bold text-indigo-800 font-mono text-base">
                          ₹{Math.round(approvedSupportAmount / repaymentTermMonths).toLocaleString('en-IN')} {t('reviewModal.perMonth')}
                        </span>
                      </div>
                    </div>

                    {/* Notes logic */}
                    <div>
                      <label className="block text-xs font-semibold text-gray-500 uppercase mb-1">{t('reviewModal.notesLabel')}</label>
                      <input
                        type="text"
                        value={adminReviewNotes}
                        onChange={(e) => setAdminReviewNotes(e.target.value)}
                        placeholder={t('reviewModal.notesPlaceholder')}
                        className="w-full text-sm border border-gray-200 p-2.5 rounded-lg focus:outline-hidden"
                      />
                    </div>

                    {/* Audit decisions buttons */}
                    <div className="flex justify-between items-center pt-4 border-t border-gray-100">
                      <button
                        type="button"
                        onClick={() => handleRejectApplication(currentBen, adminReviewNotes)}
                        className="bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 text-xs font-semibold px-4 py-2.5 rounded-lg cursor-pointer transition-colors"
                      >
                        {t('reviewModal.rejectBtn')}
                      </button>

                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => setReviewingBenId(null)}
                          className="text-xs text-gray-500 font-semibold px-4 py-2 rounded"
                        >
                          {t('reviewModal.cancelBtn')}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleApproveApplication(currentBen)}
                          className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs py-2.5 px-6 rounded-lg shadow-2xs cursor-pointer transition-colors"
                        >
                          {t('reviewModal.approveBtn')}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      ) : (
        /* Workspace 2: LEDGER WITH RECOVERY MILESTONES */
        <div className="space-y-6" id="admin_recovery_tracker">
          <div className="bg-slate-50 p-4 rounded-xl border border-gray-100/75 text-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h4 className="font-semibold text-gray-800 text-sm">{t('ledger.heading')}</h4>
              <p className="text-xs text-gray-500">{t('ledger.subtitle')}</p>
            </div>

            <div className="flex gap-2">
              <span className="bg-emerald-50 text-emerald-800 border border-emerald-100 px-3 py-1 font-semibold rounded block">
                {t('ledger.sopBadge')}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Beneficiary List Selection Column */}
            <div className="lg:col-span-1 space-y-3 bg-slate-50 p-4 rounded-xl border border-gray-100">
              <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider">{t('ledger.selectPortfolioLabel')}</h4>

              <div className="space-y-2.5 max-h-[500px] overflow-y-auto">
                {activeRecoveryList.length === 0 ? (
                  <span className="text-gray-400 text-xs italic block p-4 text-center">{t('ledger.noApprovedCases')}</span>
                ) : (
                  activeRecoveryList.map((ben) => {
                    const recovered = ben.payments?.reduce((sum, p) => sum + p.amount, 0) || 0;
                    const balance = (ben.approvedAmount || 0) - recovered;
                    const isSelected = selectedEmiBenId === ben.id;

                    return (
                      <button
                        key={ben.id}
                        onClick={() => {
                          setSelectedEmiBenId(ben.id);
                          setLoggingPaymentForId(null);
                        }}
                        className={`w-full text-left p-3 rounded-lg border text-xs transition-all flex flex-col justify-between cursor-pointer ${
                          isSelected 
                            ? 'bg-white border-[#115e59] ring-1 ring-[#115e59] shadow-2xs' 
                            : 'bg-white/80 border-gray-100 hover:bg-white'
                        }`}
                        id={`emi_selector_${ben.id}`}
                      >
                        <div className="flex justify-between items-start w-full">
                          <div>
                            <span className="font-bold text-gray-900 block">{ben.name}</span>
                            <span className="text-[10px] text-gray-400 mt-0.5 font-semibold italic">{ben.businessName}</span>
                          </div>
                          <span className={`px-1.5 py-0.5 rounded text-[11px] font-bold bg-${getStatusStyle(ben.status)}-50 text-${getStatusStyle(ben.status)}-800`}>
                            {getStatusLabel(ben.status)}
                          </span>
                        </div>

                        <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2 border-t border-gray-50/50 w-full text-[10px]">
                          <div>
                            <span className="text-gray-400 block">{t('ledger.fundsOutstandingLabel')}</span>
                            <span className="font-bold text-amber-600">₹{balance.toLocaleString('en-IN')}</span>
                          </div>
                          <div>
                            <span className="text-gray-400 block">{t('ledger.paidMilestoneLabel')}</span>
                            <span className="font-semibold text-emerald-600">
                              {t('ledger.milestoneCount', { paid: (ben.emiSchedule ?? []).filter(s => s.status === 'Paid').length, total: ben.repaymentTermMonths || 0 })}
                            </span>
                          </div>
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            </div>

            {/* Individual Repayment tracking & edit column */}
            <div className="lg:col-span-2">
              {!selectedEmiBenId ? (
                <div className="border border-dashed border-gray-200 rounded-xl p-12 text-center bg-white text-gray-400 h-full flex flex-col items-center justify-center">
                  <NotebookTabs className="w-12 h-12 stroke-1 text-gray-300 mb-2" />
                  {t('ledger.selectPrompt')}
                </div>
              ) : (() => {
                const ben = beneficiaries.find(b => b.id === selectedEmiBenId);
                if (!ben) return null;

                // Firebase RTDB drops empty arrays, so a fresh Approved case can come back
                // with payments/emiSchedule === undefined. Normalize before rendering.
                const schedule = Array.isArray(ben.emiSchedule) ? ben.emiSchedule : [];
                const paymentsList = Array.isArray(ben.payments) ? ben.payments : [];
                const recovered = paymentsList.reduce((sum, p) => sum + p.amount, 0);
                const outstanding = (ben.approvedAmount || 0) - recovered;

                return (
                  <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-6" id={`emi_ledger_panel_${ben.id}`}>
                    {/* Header and disburse check */}
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-gray-50">
                      <div>
                        <span className="text-[10px] bg-slate-100 text-slate-800 px-2 py-0.5 rounded font-bold font-mono">{t('ledger.idLabel', { id: ben.id })}</span>
                        <h3 className="font-bold text-gray-800 text-sm mt-1">{ben.name}</h3>
                        <span className="text-xs text-indigo-600 font-medium italic block">{ben.businessName}</span>
                      </div>

                      <div className="flex gap-2">
                        {ben.status === 'Approved' && (
                          <button
                            onClick={() => setConfirmingPayoutId(ben.id)}
                            className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs py-1.5 px-4 rounded-md shadow-xs cursor-pointer"
                          >
                            {t('ledger.markDisbursedBtn')}
                          </button>
                        )}

                        {(ben.status === 'Disbursed' || ben.status === 'Verified Active') && (
                          <button
                            onClick={() => {
                              setLoggingPaymentForId(ben.id);
                              setPaymentAmountPaid(ben.monthlyRepaymentEMI || 2000);
                              // Auto set to first unpaid installment index index
                              const firstUnpaid = schedule.find(s => s.status !== 'Paid');
                              setPaymentInstallmentIndex(firstUnpaid ? firstUnpaid.index : 1);
                            }}
                            className="bg-[#115e59] hover:bg-[#0f766e] border-b-2 border-[#0284c7] text-white font-bold text-xs py-1.5 px-4 rounded shadow-xs cursor-pointer transition-colors uppercase tracking-wider"
                          >
                            {t('ledger.logRepaymentBtn')}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Financial stats ribbon */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-slate-50 p-4 rounded-lg text-center text-xs">
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('ledger.stats.approvedSupportLabel')}</span>
                        <span className="font-bold text-gray-900 text-sm font-mono">₹{ben.approvedAmount?.toLocaleString('en-IN')}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('ledger.stats.repaymentTermLabel')}</span>
                        <span className="font-semibold text-gray-800 text-sm">{ben.repaymentTermMonths} {t('ledger.stats.monthsSuffix')}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('ledger.stats.totalRecoveredLabel')}</span>
                        <span className="font-bold text-emerald-600 text-sm font-mono">₹{recovered.toLocaleString('en-IN')}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 block text-[10px] uppercase font-medium">{t('ledger.stats.outstandingBalanceLabel')}</span>
                        <span className="font-bold text-amber-600 text-sm font-mono">₹{outstanding.toLocaleString('en-IN')}</span>
                      </div>
                    </div>

                    {/* Milestone Installments list (Adjustable according to SOP) */}
                    <div>
                      <div className="flex justify-between items-center mb-3">
                        <div>
                          <h4 className="font-semibold text-gray-800 text-xs uppercase tracking-wider">{t('ledger.milestones.heading')}</h4>
                          <p className="text-[10px] text-gray-400">{t('ledger.milestones.subtitle')}</p>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[250px] overflow-y-auto pr-1">
                        {schedule.map((item) => (
                          <div key={item.index} className="p-3 bg-white border border-gray-100 rounded-lg flex items-center justify-between text-xs hover:border-indigo-100 transition-colors">
                            <div>
                              <div className="flex items-center gap-1.5 font-bold text-gray-800">
                                <span>{t('ledger.milestones.installment', { index: item.index })}</span>
                                {item.status === 'Paid' && (
                                  <span className="text-[11px] bg-emerald-100 text-emerald-800 py-0.5 px-1 rounded">{t('ledger.milestones.paidBadge')}</span>
                                )}
                                {item.status === 'Adjusted' && (
                                  <span className="text-[11px] bg-sky-100 text-sky-800 py-0.5 px-1 rounded font-normal">{t('ledger.milestones.adjustedBadge')}</span>
                                )}
                              </div>
                              <span className="text-[10px] text-gray-400 block mt-0.5">{t('ledger.milestones.dueDate', { date: item.dueDate })}</span>
                            </div>

                            <div className="flex items-center gap-3">
                              <div className="text-right">
                                <span className="font-bold text-slate-800 block font-mono text-sm">₹{item.promisedAmount}</span>
                                <span className="text-[10px] text-slate-400 block">{t('ledger.milestones.paidAmount', { amount: item.amountPaid })}</span>
                              </div>

                              {item.status !== 'Paid' && (
                                <button
                                  onClick={() => {
                                    setManualEmiIndex(item.index);
                                    setManualEmiAmount(item.promisedAmount);
                                  }}
                                  title={t('ledger.milestones.tweakBtnTitle')}
                                  className="text-[10px] font-bold text-[#115e59] border border-[#115e59]/20 hover:border-[#115e59] px-2 py-0.5 rounded bg-slate-50 cursor-pointer transition-colors"
                                  id={`adjust_emi_btn_${item.index}`}
                                >
                                  {t('ledger.milestones.tweakBtn')}
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Repayment payments ledger list */}
                    <div>
                      <h4 className="font-semibold text-gray-800 text-xs uppercase tracking-wider mb-2">{t('ledger.history.heading')}</h4>

                      {paymentsList.length === 0 ? (
                        <div className="p-4 bg-slate-50 text-center rounded-lg text-xs text-gray-400">
                          {t('ledger.history.empty')}
                        </div>
                      ) : (
                        <div className="space-y-3 max-h-[220px] overflow-y-auto pr-1">
                          {paymentsList.map((p) => (
                            <div key={p.id} className="p-2.5 bg-slate-50 rounded-lg flex flex-col gap-1.5 text-xs font-mono border border-gray-200">
                              <div className="flex justify-between items-center">
                                <div>
                                  <div className="font-semibold text-gray-800">{t('ledger.history.receiptLabel', { number: p.receiptNumber })}</div>
                                  <span className="text-[10px] text-gray-400 block mt-0.5">{t('ledger.history.installmentDate', { index: p.installmentIndex, date: new Date(p.datePaid).toLocaleDateString() })}</span>
                                </div>
                                <div className="font-bold text-emerald-700 text-sm">₹{p.amount.toLocaleString('en-IN')}</div>
                              </div>
                              {p.notes && (
                                <div className="text-[11px] text-gray-500 bg-white p-1.5 rounded border border-gray-100 font-sans leading-relaxed">
                                  <span className="font-bold text-[#115e59]">{t('ledger.history.staffLogLabel')}</span> {p.notes}
                                </div>
                              )}
                              {p.proofUrl && (
                                <div className="mt-1">
                                  <span className="text-[11px] text-gray-404 font-semibold uppercase block mb-1">{t('ledger.history.attachedReceiptLabel')}</span>
                                  <img
                                    src={p.proofUrl}
                                    alt={t('ledger.history.receiptImageAlt')}
                                    className="w-full max-h-[110px] object-cover rounded border border-gray-300 shadow-3xs"
                                    referrerPolicy="no-referrer"
                                  />
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Inline Manual Tweak popup */}
                    {manualEmiIndex !== null && (
                      <div className="bg-slate-50 p-3 rounded border border-gray-200 mt-4 space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="text-xs font-bold text-[#115e59] uppercase tracking-wider">{t('ledger.tweakPopup.title', { index: manualEmiIndex })}</span>
                          <button onClick={() => setManualEmiIndex(null)} className="text-red-500 font-bold text-[10px] uppercase tracking-wider cursor-pointer">{t('ledger.tweakPopup.cancelBtn')}</button>
                        </div>
                        <div className="flex items-center gap-4">
                          <input
                            type="range"
                            min={0}
                            step={100}
                            max={ben.approvedAmount || 30000}
                            value={manualEmiAmount}
                            onChange={(e) => setManualEmiAmount(Number(e.target.value))}
                            className="flex-1 accent-[#0284c7]"
                          />
                          <span className="font-mono font-bold text-xs text-[#115e59] min-w-[70px] bg-sky-50 px-2 py-1 rounded text-right">₹{manualEmiAmount.toLocaleString('en-IN')}</span>
                        </div>
                        <p className="text-[10px] text-slate-500 italic">
                          {t('ledger.tweakPopup.validationRule')}
                        </p>
                        <button
                          type="button"
                          onClick={() => handleSaveEmiAdjustment(ben, manualEmiIndex, manualEmiAmount)}
                          className="w-full bg-[#115e59] hover:bg-[#0f766e] border-b-2 border-[#0284c7] text-white font-bold text-xs py-2 rounded cursor-pointer uppercase tracking-wider"
                        >
                          {t('ledger.tweakPopup.applyBtn')}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>

          {/* Dialog Modal: DISBURSE CONFIRMATION */}
          {confirmingPayoutId && (() => {
            const currentDisbursingBen = beneficiaries.find(b => b.id === confirmingPayoutId);
            if (!currentDisbursingBen) return null;
            return (
              <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div className="bg-white rounded-xl shadow-card max-w-sm w-full p-6 text-center space-y-4">
                  <div className="w-12 h-12 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mx-auto text-lg">✓</div>
                  <h4 className="font-bold text-slate-800 text-sm">{t('disburseModal.title')}</h4>
                  <p className="text-slate-500 text-xs">
                    <Trans
                      t={t}
                      i18nKey="disburseModal.confirmText"
                      values={{ amount: currentDisbursingBen.approvedAmount?.toLocaleString('en-IN'), name: currentDisbursingBen.name }}
                      components={{ b: <b /> }}
                    />
                  </p>
                  <div className="flex gap-2 pt-2">
                    <button
                      onClick={() => setConfirmingPayoutId(null)}
                      className="flex-1 bg-slate-50 border border-gray-200 py-2 rounded-lg text-xs font-semibold text-slate-500 hover:bg-slate-100 cursor-pointer"
                    >
                      {t('disburseModal.cancelBtn')}
                    </button>
                    <button
                      onClick={() => handleDisburseSupport(currentDisbursingBen)}
                      className="flex-1 bg-emerald-600 text-white py-2 rounded-lg text-xs font-semibold hover:bg-emerald-700 cursor-pointer shadow-2xs"
                    >
                      {t('disburseModal.processBtn')}
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Dialog Modal: LOG REPAYMENT RECEIVED */}
          {loggingPaymentForId && (() => {
            const targetRef = beneficiaries.find(b => b.id === loggingPaymentForId);
            if (!targetRef) return null;
            return (
              <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div className="bg-white rounded-xl shadow-card border border-gray-100 max-w-sm w-full overflow-hidden">
                  <div className="p-4 bg-teal-950 text-white flex justify-between items-center">
                    <h3 className="font-semibold text-sm">{t('logRepaymentModal.title')}</h3>
                    <button onClick={() => setLoggingPaymentForId(null)} className="text-white">✕</button>
                  </div>

                  <form onSubmit={handleLogRepayment} className="p-5 space-y-4 text-xs">
                    <p className="text-gray-500">
                      <Trans
                        t={t}
                        i18nKey="logRepaymentModal.recordText"
                        values={{ name: targetRef.name }}
                        components={{ b: <b /> }}
                      />
                    </p>

                    <div>
                      <label className="block text-gray-400 mb-1">{t('logRepaymentModal.targetInstallmentLabel')}</label>
                      <select
                        value={paymentInstallmentIndex}
                        onChange={(e) => setPaymentInstallmentIndex(Number(e.target.value))}
                        className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                      >
                        {(targetRef.emiSchedule ?? []).map((s) => (
                          <option key={s.index} value={s.index} disabled={s.status === 'Paid'}>
                            {t('logRepaymentModal.installmentOption', { index: s.index })} {s.status === 'Paid' ? t('logRepaymentModal.paidSuffix') : t('logRepaymentModal.amountSuffix', { amount: s.promisedAmount })}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-gray-400 mb-1">{t('logRepaymentModal.amountCollectedLabel')}</label>
                      <input
                        type="number"
                        required
                        min={1}
                        value={paymentAmountPaid}
                        onChange={(e) => setPaymentAmountPaid(Number(e.target.value))}
                        className="w-full text-xs font-semibold border border-gray-200 p-2 rounded"
                      />
                    </div>


                    

                    <div>
                      <label className="block text-gray-400 mb-1">{t('logRepaymentModal.receiptVoucherLabel')}</label>
                      <input
                        type="text"
                        placeholder={t('logRepaymentModal.receiptPlaceholder')}
                        value={receiptNumber}
                        onChange={(e) => setReceiptNumber(e.target.value)}
                        className="w-full text-xs border border-gray-200 p-2 rounded"
                      />
                    </div>

                    <div>
                      <label className="block text-gray-400 mb-1">{t('logRepaymentModal.remarksLabel')}</label>
                      <input
                        type="text"
                        placeholder={t('logRepaymentModal.remarksPlaceholder')}
                        value={paymentNote}
                        onChange={(e) => setPaymentNote(e.target.value)}
                        className="w-full text-xs border border-gray-200 p-2 rounded"
                      />
                    </div>

                    <div className="flex gap-2 pt-3">
                      <button
                        type="button"
                        onClick={() => setLoggingPaymentForId(null)}
                        className="flex-1 bg-slate-50 border py-2 rounded text-slate-500 cursor-pointer"
                      >
                        {t('logRepaymentModal.cancelBtn')}
                      </button>
                      <button
                        type="submit"
                        className="flex-1 bg-teal-800 hover:bg-teal-900 text-white py-2 rounded font-semibold cursor-pointer shadow-xs transition-colors"
                      >
                        {t('logRepaymentModal.submitBtn')}
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
