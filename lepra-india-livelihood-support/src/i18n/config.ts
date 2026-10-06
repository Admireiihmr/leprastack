import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import enCommon from './locales/en/common.json';
import enLanding from './locales/en/landing.json';
import enAdminLogin from './locales/en/adminLogin.json';
import enAgentAuth from './locales/en/agentAuth.json';
import enAdminSetup from './locales/en/adminSetup.json';
import enAgentPortal from './locales/en/agentPortal.json';
import enApproverPortal from './locales/en/approverPortal.json';
import enSuperAdminPortal from './locales/en/superAdminPortal.json';
import enNotificationPanel from './locales/en/notificationPanel.json';
import enDashboardStats from './locales/en/dashboardStats.json';
import enReimbursementTracker from './locales/en/reimbursementTracker.json';
import enWelfareSchemes from './locales/en/welfareSchemes.json';
import enAdminDashboard from './locales/en/adminDashboard.json';
import enAgentDashboard from './locales/en/agentDashboard.json';

import hiCommon from './locales/hi/common.json';
import hiLanding from './locales/hi/landing.json';
import hiAdminLogin from './locales/hi/adminLogin.json';
import hiAgentAuth from './locales/hi/agentAuth.json';
import hiAdminSetup from './locales/hi/adminSetup.json';
import hiAgentPortal from './locales/hi/agentPortal.json';
import hiApproverPortal from './locales/hi/approverPortal.json';
import hiSuperAdminPortal from './locales/hi/superAdminPortal.json';
import hiNotificationPanel from './locales/hi/notificationPanel.json';
import hiDashboardStats from './locales/hi/dashboardStats.json';
import hiReimbursementTracker from './locales/hi/reimbursementTracker.json';
import hiWelfareSchemes from './locales/hi/welfareSchemes.json';
import hiAdminDashboard from './locales/hi/adminDashboard.json';
import hiAgentDashboard from './locales/hi/agentDashboard.json';

import mrCommon from './locales/mr/common.json';
import mrLanding from './locales/mr/landing.json';
import mrAdminLogin from './locales/mr/adminLogin.json';
import mrAgentAuth from './locales/mr/agentAuth.json';
import mrAdminSetup from './locales/mr/adminSetup.json';
import mrAgentPortal from './locales/mr/agentPortal.json';
import mrApproverPortal from './locales/mr/approverPortal.json';
import mrSuperAdminPortal from './locales/mr/superAdminPortal.json';
import mrNotificationPanel from './locales/mr/notificationPanel.json';
import mrDashboardStats from './locales/mr/dashboardStats.json';
import mrReimbursementTracker from './locales/mr/reimbursementTracker.json';
import mrWelfareSchemes from './locales/mr/welfareSchemes.json';
import mrAdminDashboard from './locales/mr/adminDashboard.json';
import mrAgentDashboard from './locales/mr/agentDashboard.json';

import orCommon from './locales/or/common.json';
import orLanding from './locales/or/landing.json';
import orAdminLogin from './locales/or/adminLogin.json';
import orAgentAuth from './locales/or/agentAuth.json';
import orAdminSetup from './locales/or/adminSetup.json';
import orAgentPortal from './locales/or/agentPortal.json';
import orApproverPortal from './locales/or/approverPortal.json';
import orSuperAdminPortal from './locales/or/superAdminPortal.json';
import orNotificationPanel from './locales/or/notificationPanel.json';
import orDashboardStats from './locales/or/dashboardStats.json';
import orReimbursementTracker from './locales/or/reimbursementTracker.json';
import orWelfareSchemes from './locales/or/welfareSchemes.json';
import orAdminDashboard from './locales/or/adminDashboard.json';
import orAgentDashboard from './locales/or/agentDashboard.json';

import teCommon from './locales/te/common.json';
import teLanding from './locales/te/landing.json';
import teAdminLogin from './locales/te/adminLogin.json';
import teAgentAuth from './locales/te/agentAuth.json';
import teAdminSetup from './locales/te/adminSetup.json';
import teAgentPortal from './locales/te/agentPortal.json';
import teApproverPortal from './locales/te/approverPortal.json';
import teSuperAdminPortal from './locales/te/superAdminPortal.json';
import teNotificationPanel from './locales/te/notificationPanel.json';
import teDashboardStats from './locales/te/dashboardStats.json';
import teReimbursementTracker from './locales/te/reimbursementTracker.json';
import teWelfareSchemes from './locales/te/welfareSchemes.json';
import teAdminDashboard from './locales/te/adminDashboard.json';
import teAgentDashboard from './locales/te/agentDashboard.json';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'mr', label: 'मराठी' },
  { code: 'or', label: 'ଓଡ଼ିଆ' },
  { code: 'te', label: 'తెలుగు' }
] as const;

export const LANGUAGE_STORAGE_KEY = 'lepra_language';

const storedLanguage = typeof window !== 'undefined' ? window.localStorage.getItem(LANGUAGE_STORAGE_KEY) : null;

i18n.use(initReactI18next).init({
  lng: storedLanguage || 'en',
  fallbackLng: 'en',
  ns: [
    'common', 'landing', 'adminLogin', 'agentAuth', 'adminSetup', 'agentPortal',
    'approverPortal', 'superAdminPortal', 'notificationPanel', 'dashboardStats',
    'reimbursementTracker', 'welfareSchemes', 'adminDashboard', 'agentDashboard'
  ],
  defaultNS: 'common',
  interpolation: { escapeValue: false },
  resources: {
    en: {
      common: enCommon, landing: enLanding, adminLogin: enAdminLogin, agentAuth: enAgentAuth,
      adminSetup: enAdminSetup, agentPortal: enAgentPortal, approverPortal: enApproverPortal,
      superAdminPortal: enSuperAdminPortal, notificationPanel: enNotificationPanel,
      dashboardStats: enDashboardStats, reimbursementTracker: enReimbursementTracker,
      welfareSchemes: enWelfareSchemes, adminDashboard: enAdminDashboard, agentDashboard: enAgentDashboard
    },
    hi: {
      common: hiCommon, landing: hiLanding, adminLogin: hiAdminLogin, agentAuth: hiAgentAuth,
      adminSetup: hiAdminSetup, agentPortal: hiAgentPortal, approverPortal: hiApproverPortal,
      superAdminPortal: hiSuperAdminPortal, notificationPanel: hiNotificationPanel,
      dashboardStats: hiDashboardStats, reimbursementTracker: hiReimbursementTracker,
      welfareSchemes: hiWelfareSchemes, adminDashboard: hiAdminDashboard, agentDashboard: hiAgentDashboard
    },
    mr: {
      common: mrCommon, landing: mrLanding, adminLogin: mrAdminLogin, agentAuth: mrAgentAuth,
      adminSetup: mrAdminSetup, agentPortal: mrAgentPortal, approverPortal: mrApproverPortal,
      superAdminPortal: mrSuperAdminPortal, notificationPanel: mrNotificationPanel,
      dashboardStats: mrDashboardStats, reimbursementTracker: mrReimbursementTracker,
      welfareSchemes: mrWelfareSchemes, adminDashboard: mrAdminDashboard, agentDashboard: mrAgentDashboard
    },
    or: {
      common: orCommon, landing: orLanding, adminLogin: orAdminLogin, agentAuth: orAgentAuth,
      adminSetup: orAdminSetup, agentPortal: orAgentPortal, approverPortal: orApproverPortal,
      superAdminPortal: orSuperAdminPortal, notificationPanel: orNotificationPanel,
      dashboardStats: orDashboardStats, reimbursementTracker: orReimbursementTracker,
      welfareSchemes: orWelfareSchemes, adminDashboard: orAdminDashboard, agentDashboard: orAgentDashboard
    },
    te: {
      common: teCommon, landing: teLanding, adminLogin: teAdminLogin, agentAuth: teAgentAuth,
      adminSetup: teAdminSetup, agentPortal: teAgentPortal, approverPortal: teApproverPortal,
      superAdminPortal: teSuperAdminPortal, notificationPanel: teNotificationPanel,
      dashboardStats: teDashboardStats, reimbursementTracker: teReimbursementTracker,
      welfareSchemes: teWelfareSchemes, adminDashboard: teAdminDashboard, agentDashboard: teAgentDashboard
    }
  }
});

export default i18n;
