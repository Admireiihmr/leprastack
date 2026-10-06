import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import Landing from './portals/Landing';
import AgentAuth from './portals/AgentAuth';
import AdminLogin from './portals/AdminLogin';
import AdminSetup from './portals/AdminSetup';
import AgentPortal from './portals/AgentPortal';
import ApproverPortal from './portals/ApproverPortal';
import SuperAdminPortal from './portals/SuperAdminPortal';
import { Loader2, HeartPulse } from 'lucide-react';

function LoadingScreen() {
  return (
    <div className="min-h-screen bg-[#ffffff] flex flex-col items-center justify-center gap-3 text-[#115e59]">
      <HeartPulse className="w-8 h-8 text-[#0284c7] animate-pulse" />
      <Loader2 className="w-4 h-4 animate-spin" />
      <span className="text-xs uppercase tracking-widest font-bold">Initializing secure session</span>
    </div>
  );
}

function roleHomePath(role: 'agent' | 'approver' | 'superadmin'): string {
  if (role === 'agent') return '/field-agent';
  if (role === 'approver') return '/approval';
  return '/superadmin';
}

function LandingRoute() {
  const navigate = useNavigate();
  const { user } = useAuth();
  if (user) return <Navigate to={roleHomePath(user.role)} replace />;

  return (
    <Landing
      onChoose={(choice) => {
        if (choice === 'agent') navigate('/field-agent');
        else if (choice === 'approver') navigate('/approval');
        else if (choice === 'superadmin') navigate('/superadmin');
        else navigate('/admin-setup');
      }}
    />
  );
}

function FieldAgentRoute() {
  const { user } = useAuth();
  if (user) return user.role === 'agent' ? <AgentPortal /> : <Navigate to={roleHomePath(user.role)} replace />;
  return <AgentAuth />;
}

function ApprovalRoute() {
  const { user } = useAuth();
  if (user) return user.role === 'approver' ? <ApproverPortal /> : <Navigate to={roleHomePath(user.role)} replace />;
  return <AdminLogin role="approver" />;
}

function SuperAdminRoute() {
  const { user } = useAuth();
  if (user) return user.role === 'superadmin' ? <SuperAdminPortal /> : <Navigate to={roleHomePath(user.role)} replace />;
  return <AdminLogin role="superadmin" />;
}

function AdminSetupRoute() {
  const navigate = useNavigate();
  return <AdminSetup onBack={() => navigate('/')} />;
}

function AppRoutes() {
  const { initializing } = useAuth();
  if (initializing) return <LoadingScreen />;

  return (
    <Routes>
      <Route path="/" element={<LandingRoute />} />
      <Route path="/field-agent" element={<FieldAgentRoute />} />
      <Route path="/approval" element={<ApprovalRoute />} />
      <Route path="/superadmin" element={<SuperAdminRoute />} />
      <Route path="/admin-setup" element={<AdminSetupRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/+$/, '') || '/'}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
