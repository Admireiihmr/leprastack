import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function ProtectedRoute({ roles, children }) {
  const { user, role, loading } = useAuth();
  if (loading) return <div className="p-8 t-muted">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  // Role missing — let Home render the "account not configured" recovery UI.
  if (!role) return <Navigate to="/" replace />;
  if (roles && !roles.includes(role))
    return <Navigate to="/" replace />;
  return children;
}
