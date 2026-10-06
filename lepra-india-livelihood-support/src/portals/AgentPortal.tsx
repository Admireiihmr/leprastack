import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UserRoundCheck } from 'lucide-react';
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
import AgentDashboard from '../components/AgentDashboard';
import NotificationPanel from '../components/NotificationPanel';
import PortalShell from './PortalShell';

export default function AgentPortal() {
  const { t } = useTranslation('agentPortal');
  const { user } = useAuth();
  const [beneficiaries, setBeneficiaries] = useState<Beneficiary[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => subscribeBeneficiaries(setBeneficiaries), []);
  useEffect(() => subscribeNotifications(setNotifications), []);

  const handleAddBeneficiary = async (newBen: Beneficiary) => {
    console.log('[Intake] Submitting beneficiary:', newBen);
    console.log('[Intake] Current auth user:', user);
    try {
      const { id: _generated, ...payload } = newBen;
      const newId = await addBeneficiary(payload);
      console.log('[Intake] Beneficiary saved with id:', newId);
      await addNotification({
        type: 'warning',
        title: 'New Ground Registration',
        message: `${user?.displayName || 'A field agent'} submitted [${newBen.name}] for business plan: "${newBen.businessName}".`,
        timestamp: new Date().toISOString(),
        read: false,
        targetRole: 'Admin'
      });
      console.log('[Intake] Notification created');
      return newId;
    } catch (err) {
      console.error('[Intake] Firebase write failed:', err);
      throw err;
    }
  };

  const handleUpdateBeneficiary = async (updated: Beneficiary) => {
    await updateBeneficiary(updated.id, updated);
  };

  return (
    <PortalShell roleBadge={t('roleBadge')} accent="bg-[#0284c7]">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-2 mb-1.5">
              <div className="w-7 h-7 rounded-full bg-sky-50 flex items-center justify-center shrink-0">
                <UserRoundCheck className="w-3.5 h-3.5 text-[#0284c7]" />
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
            onClearAll={() => clearNotificationsForRole(notifications, 'Agent')}
            currentRole="Agent"
          />
        </div>

        <div className="lg:col-span-3 space-y-4">
          <div className="bg-gradient-to-r from-[#115e59] to-[#0f766e] text-white rounded-xl p-4 shadow-md border-l-4 border-[#0284c7]">
            <span className="text-white/70 text-[11px] font-bold uppercase tracking-widest block font-mono">{t('workspaceLabel')}</span>
            <h2 className="text-base font-bold">{t('workspaceTitle')}</h2>
            <p className="text-xs text-white/80 max-w-xl">
              {t('workspaceSubtitle')}
            </p>
          </div>

          <AgentDashboard
            beneficiaries={beneficiaries}
            agentDisplayName={user?.displayName || user?.email || t('roleBadge')}
            onAddBeneficiary={handleAddBeneficiary}
            onUpdateBeneficiary={handleUpdateBeneficiary}
          />
        </div>
      </div>
    </PortalShell>
  );
}


