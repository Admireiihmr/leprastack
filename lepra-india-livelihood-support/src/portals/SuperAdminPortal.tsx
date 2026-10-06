import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LineChart, ShieldCheck, Users, HandHeart, CalendarClock, FileSpreadsheet, Loader2 } from 'lucide-react';
import { Beneficiary, Notification } from '../types';
import {
  subscribeBeneficiaries,
  subscribeNotifications,
  addBeneficiary,
  updateBeneficiary,
  addNotification,
  markNotificationRead,
  clearNotificationsForRole
} from '../dataService';
import { useAuth } from '../AuthContext';
import AdminDashboard from '../components/AdminDashboard';
import DashboardStats from '../components/DashboardStats';
import NotificationPanel from '../components/NotificationPanel';
import WelfareSchemes from '../components/WelfareSchemes';
import ReimbursementTracker from '../components/ReimbursementTracker';
import PortalShell from './PortalShell';
import { exportBeneficiariesToExcel } from '../utils/exportBeneficiaries';

type SuperTab = 'dashboard' | 'approvals' | 'reimbursement' | 'welfare' | 'agents';

export default function SuperAdminPortal() {
  const { t } = useTranslation('superAdminPortal');
  const { user } = useAuth();
  const [beneficiaries, setBeneficiaries] = useState<Beneficiary[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [tab, setTab] = useState<SuperTab>('dashboard');
  const [exporting, setExporting] = useState(false);

  useEffect(() => subscribeBeneficiaries(setBeneficiaries), []);
  useEffect(() => subscribeNotifications(setNotifications), []);

  const handleExportExcel = async () => {
    setExporting(true);
    try {
      await exportBeneficiariesToExcel(beneficiaries);
    } catch (err) {
      console.error('[SuperAdminPortal] Excel export failed:', err);
      alert(t('exportExcel.failed'));
    } finally {
      setExporting(false);
    }
  };

  const handleAddBeneficiary = async (newBen: Beneficiary) => {
    const { id: _generated, ...payload } = newBen;
    return addBeneficiary(payload);
  };

  const handleUpdateBeneficiary = async (updated: Beneficiary) => {
    await updateBeneficiary(updated.id, updated);
  };

  const handleSendNotification = async (
    title: string,
    message: string,
    type: 'info' | 'success' | 'warning' | 'error',
    target: 'Admin' | 'Agent'
  ) => {
    await addNotification({
      type, title, message,
      timestamp: new Date().toISOString(),
      read: false, targetRole: target
    });
  };

  const agentStats = useMemo(() => {
    const map = new Map<string, { count: number; approved: number; disbursed: number }>();
    beneficiaries.forEach((b) => {
      const key = b.registeredByAgent || 'Unattributed';
      const cur = map.get(key) || { count: 0, approved: 0, disbursed: 0 };
      cur.count += 1;
      if (b.status === 'Approved' || b.status === 'Disbursed' || b.status === 'Verified Active') cur.approved += 1;
      if (b.status === 'Disbursed' || b.status === 'Verified Active') cur.disbursed += 1;
      map.set(key, cur);
    });
    return Array.from(map.entries()).map(([agent, stats]) => ({ agent, ...stats }));
  }, [beneficiaries]);

  const superAdminTabs: Array<{ key: SuperTab; label: string; icon: React.ReactNode }> = [
    { key: 'dashboard', label: t('tabs.dashboard'), icon: <LineChart className="w-3.5 h-3.5" /> },
    { key: 'approvals', label: t('tabs.approvals'), icon: <ShieldCheck className="w-3.5 h-3.5" /> },
    { key: 'reimbursement', label: t('tabs.reimbursement'), icon: <CalendarClock className="w-3.5 h-3.5" /> },
    { key: 'welfare', label: t('tabs.welfare'), icon: <HandHeart className="w-3.5 h-3.5" /> },
    { key: 'agents', label: t('tabs.agents'), icon: <Users className="w-3.5 h-3.5" /> }
  ];

  return (
    <PortalShell roleBadge={t('roleBadge')} accent="bg-[#0284c7]">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-2 mb-1.5">
              <div className="w-7 h-7 rounded-full bg-sky-50 flex items-center justify-center shrink-0">
                <LineChart className="w-3.5 h-3.5 text-[#0284c7]" />
              </div>
              <h3 className="font-bold text-[#115e59] text-xs uppercase tracking-wider">{t('roleBadge')}</h3>
            </div>
            <p className="text-[11px] text-gray-600 leading-relaxed">
              {t('sessionDescriptionPrefix')} <span className="font-bold">{user?.displayName || user?.email}</span>. {t('sessionDescriptionSuffix')}
            </p>
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-2 shadow-sm flex flex-col gap-1">
            {superAdminTabs.map((tabItem) => (
              <button
                key={tabItem.key}
                onClick={() => setTab(tabItem.key)}
                className={`flex items-center gap-2 px-3 py-2 text-xs font-bold rounded-lg transition-all cursor-pointer uppercase tracking-wide ${
                  tab === tabItem.key
                    ? 'bg-[#115e59] text-white shadow-sm'
                    : 'text-gray-700 hover:bg-slate-50'
                }`}
              >
                {tabItem.icon}
                {tabItem.label}
              </button>
            ))}
          </div>

          <button
            onClick={handleExportExcel}
            disabled={exporting || beneficiaries.length === 0}
            className="w-full flex items-center justify-center gap-2 bg-[#115e59] hover:bg-[#0f766e] disabled:opacity-50 disabled:cursor-not-allowed border-b-2 border-[#0284c7] text-white text-xs font-bold uppercase tracking-wide px-3 py-2.5 rounded-xl shadow-sm cursor-pointer transition-all"
            title={t('exportExcel.tooltip')}
          >
            {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5" />}
            {exporting ? t('exportExcel.exporting') : t('exportExcel.button')}
          </button>

          <NotificationPanel
            notifications={notifications}
            onMarkAsRead={markNotificationRead}
            onClearAll={() => clearNotificationsForRole(notifications, 'Admin')}
            currentRole="Admin"
          />
        </div>

        <div className="lg:col-span-3 space-y-4">
          <div className="bg-gradient-to-r from-[#0284c7] to-[#0369a1] text-white rounded-xl p-4 shadow-md border-l-4 border-[#115e59]">
            <span className="text-white/80 text-[11px] font-bold uppercase tracking-widest block font-mono">{t('workspaceLabel')}</span>
            <h2 className="text-base font-bold">{t('workspaceTitle')}</h2>
            <p className="text-xs text-white/90 max-w-xl">
              {t('workspaceSubtitle')}
            </p>
          </div>

          {tab === 'dashboard' && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-xs p-5">
              <DashboardStats beneficiaries={beneficiaries} />
            </div>
          )}

          {tab === 'approvals' && (
            <AdminDashboard
              mode="superadmin"
              beneficiaries={beneficiaries}
              onUpdateBeneficiary={handleUpdateBeneficiary}
              onSendNotification={handleSendNotification}
            />
          )}

          {tab === 'reimbursement' && (
            <ReimbursementTracker beneficiaries={beneficiaries} />
          )}

          {tab === 'welfare' && (
            <WelfareSchemes
              beneficiaries={beneficiaries}
              onAddBeneficiary={handleAddBeneficiary}
              onUpdateBeneficiary={handleUpdateBeneficiary}
              loggedBy={user?.displayName || user?.email || t('roleBadge')}
            />
          )}

          {tab === 'agents' && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-md overflow-hidden">
              <div className="p-3.5 bg-gradient-to-r from-[#115e59] to-[#0f766e] text-white border-b-2 border-[#0284c7] flex items-center gap-2">
                <Users className="w-4 h-4 text-[#0284c7]" />
                <h3 className="font-bold text-xs uppercase tracking-wider">{t('agentMonitoring.title')}</h3>
              </div>
              <table className="w-full text-left border-collapse text-xs">
                <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-gray-500">
                  <tr>
                    <th className="p-3 px-3.5">{t('agentMonitoring.tableHeaders.agent')}</th>
                    <th className="p-3 px-3.5 text-right">{t('agentMonitoring.tableHeaders.submissions')}</th>
                    <th className="p-3 px-3.5 text-right">{t('agentMonitoring.tableHeaders.approvedPlus')}</th>
                    <th className="p-3 px-3.5 text-right">{t('agentMonitoring.tableHeaders.disbursedPlus')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {agentStats.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="p-8 text-center text-gray-400">
                        {t('agentMonitoring.emptyState')}
                      </td>
                    </tr>
                  ) : (
                    agentStats.map((row) => (
                      <tr key={row.agent} className="hover:bg-sky-50/30 transition-colors">
                        <td className="p-3 px-3.5 font-semibold text-[#115e59]">{row.agent}</td>
                        <td className="p-3 px-3.5 text-right font-mono">{row.count}</td>
                        <td className="p-3 px-3.5 text-right font-mono text-emerald-700">{row.approved}</td>
                        <td className="p-3 px-3.5 text-right font-mono text-amber-700">{row.disbursed}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </PortalShell>
  );
}
