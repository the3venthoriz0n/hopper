import React from 'react';
import { useLocation, Navigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import LoadingScreen from '../common/LoadingScreen';

/**
 * Protected Route Component - handles authentication checks
 * @param {React.ReactElement} children - Child component to render if authenticated
 * @param {boolean} requireAdmin - Whether admin access is required
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

