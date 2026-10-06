import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';
import { Beneficiary, Notification } from '../types';
import {
  subscribeBeneficiaries,
  subscribeNotifications,
  updateBeneficiary,
  addNotification,
  markNotificationRead,
  clearNotificationsForRole
} from '../dataService';
import { useAuth } from '../AuthContext';
import AdminDashboard from '../components/AdminDashboard';
import NotificationPanel from '../components/NotificationPanel';
import PortalShell from './PortalShell';

export default function ApproverPortal() {
  const { t } = useTranslation('approverPortal');
  const { user } = useAuth();
  const [beneficiaries, setBeneficiaries] = useState<Beneficiary[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => subscribeBeneficiaries(setBeneficiaries), []);
  useEffect(() => subscribeNotifications(setNotifications), []);

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
      type,
      title,
      message,
      timestamp: new Date().toISOString(),
      read: false,
      targetRole: target
    });
  };

  return (
    <PortalShell roleBadge={t('roleBadge')} accent="bg-emerald-700">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-2 mb-1.5">
              <div className="w-7 h-7 rounded-full bg-emerald-50 flex items-center justify-center shrink-0">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
              </div>
              <h3 className="font-bold text-[#115e59] text-xs uppercase tracking-wider">{t('sessionTitle')}</h3>
            </div>
            <p className="text-[11px] text-gray-600 leading-relaxed">
              {t('sessionDescriptionPrefix')} <span className="font-bold">{user?.displayName || user?.email}</span>. {t('sessionDescriptionSuffix')}
            </p>
          </div>

          <NotificationPanel
            notifications={notifications}
            onMarkAsRead={markNotificationRead}
            onClearAll={() => clearNotificationsForRole(notifications, 'Admin')}
            currentRole="Admin"
          />
        </div>

        <div className="lg:col-span-3 space-y-4">
          <div className="bg-gradient-to-r from-emerald-700 to-emerald-800 text-white rounded-xl p-4 shadow-md border-l-4 border-[#0284c7]">
            <span className="text-white/70 text-[11px] font-bold uppercase tracking-widest block font-mono">{t('workspaceLabel')}</span>
            <h2 className="text-base font-bold">{t('workspaceTitle')}</h2>
            <p className="text-xs text-white/80 max-w-xl">
              {t('workspaceSubtitle')}
            </p>
          </div>

          <AdminDashboard
            mode="approver"
            beneficiaries={beneficiaries}
            onUpdateBeneficiary={handleUpdateBeneficiary}
            onSendNotification={handleSendNotification}
          />
        </div>
      </div>
    </PortalShell>
  );
}
