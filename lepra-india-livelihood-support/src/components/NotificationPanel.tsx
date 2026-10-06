import React from 'react';
import { useTranslation } from 'react-i18next';
import { Notification } from '../types';
import { Bell, Check, X, Info, AlertTriangle, AlertCircle, ArrowRight } from 'lucide-react';

interface NotificationPanelProps {
  notifications: Notification[];
  onMarkAsRead: (id: string) => void;
  onClearAll: () => void;
  currentRole: 'Admin' | 'Agent';
}

export default function NotificationPanel({
  notifications,
  onMarkAsRead,
  onClearAll,
  currentRole
}: NotificationPanelProps) {
  const { t } = useTranslation('notificationPanel');

  const filteredNotifications = notifications.filter(
    n => n.targetRole === currentRole
  );
  

  const unreadCount = filteredNotifications.filter(n => !n.read).length;

  const getIcon = (type: Notification['type']) => {
    switch (type) {
      case 'success':
        return <Check className="w-5 h-5 text-emerald-500 bg-emerald-50 p-1 rounded-full" />;
      case 'warning':
        return <AlertTriangle className="w-5 h-5 text-amber-500 bg-amber-50 p-1 rounded-full" />;
      case 'error':
        return <AlertCircle className="w-5 h-5 text-rose-500 bg-rose-50 p-1 rounded-full" />;
      case 'info':
      default:
        return <Info className="w-5 h-5 text-blue-500 bg-blue-50 p-1 rounded-full" />;
    }
  };


  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-xs overflow-hidden" id="notification_panel_container">
      <div className="p-3 border-b border-[#0284c7] flex items-center justify-between bg-[#115e59] text-white">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Bell className="w-4 h-4 text-white" id="notification_bell_icon" />
            {unreadCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 bg-[#0284c7] text-[8px] font-bold text-white rounded-full flex items-center justify-center animate-pulse">
                {unreadCount}
              </span>
            )}
          </div>
          <h3 className="font-bold text-[11px] uppercase tracking-wider text-white">
            {t('operationalAlerts', { role: currentRole })}
          </h3>
        </div>

        {filteredNotifications.length > 0 && (
          <button
            onClick={onClearAll}
            className="text-[10px] text-white/90 hover:text-[#0284c7] transition-colors bg-white/10 px-2 py-0.5 rounded border border-white/10 cursor-pointer font-bold uppercase"
            id="clear_notifications_btn"
          >
            {t('clear')}
          </button>
        )}
      </div>

      <div className="max-h-[250px] overflow-y-auto divide-y divide-gray-100" id="notification_list">
        {filteredNotifications.length === 0 ? (
          <div className="p-6 text-center text-gray-400 text-[11px]">
            <Bell className="w-6 h-6 mx-auto stroke-1 mb-1.5 text-gray-300" />
            {t('noActiveAlerts', { role: currentRole })}
          </div>
        ) : (
          filteredNotifications.map((notif) => (
            <div 
              key={notif.id} 
              className={`p-2.5 transition-colors flex gap-2.5 items-start ${notif.read ? 'bg-white opacity-70' : 'bg-sky-50/40'}`}
              id={`notif_item_${notif.id}`}
            >
              <div className="mt-0.5 shrink-0">
                {getIcon(notif.type)}
              </div>
              
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between mb-0.5">
                  <span className={`text-[11px] text-[#171717] ${notif.read ? 'font-medium' : 'font-bold'}`}>
                    {notif.title}
                  </span>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {new Date(notif.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                <p className="text-[11px] text-gray-650 leading-tight break-words">
                  {notif.message}
                </p>
                
                {notif.title.includes("Approved") && (
                  <div className="mt-1 text-[11px] bg-emerald-50 text-emerald-800 rounded px-1.5 py-0.5 inline-flex items-center gap-1 font-bold border border-emerald-100">
                    <span>{t('beneficiaryEnrollmentSmsSent')}</span>
                    <ArrowRight className="w-2.5 h-2.5" />
                  </div>
                )}
              </div>

              {!notif.read && (
                <button 
                  onClick={() => onMarkAsRead(notif.id)}
                  title={t('markAsRead')}
                  className="shrink-0 p-1 hover:bg-white rounded text-gray-400 hover:text-[#115e59] transition-colors cursor-pointer"
                  id={`mark_read_btn_${notif.id}`}
                >
                  <Check className="w-3 h-3" />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
