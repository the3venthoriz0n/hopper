import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import LoadingScreen from '../common/LoadingScreen';

/**
 * Protected route component - handles authentication checks
 * @param {object} props
 * @param {React.ReactNode} props.children - Child component to render
 * @param {boolean} props.requireAdmin - Whether admin access is required
 */
export default function ProtectedRoute({ children, requireAdmin = false }) {
  const location = useLocation();
  const { user, isAdmin, setUser, authLoading } = useAuth();

  if (authLoading) {
    return <LoadingScreen />;
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/app" replace />;
  }

  return React.cloneElement(children, { user, isAdmin, setUser, authLoading });
}
