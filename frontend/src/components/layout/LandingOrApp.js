import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import LoadingScreen from '../common/LoadingScreen';
import PublicLanding from '../auth/PublicLanding';

/**
 * Landing or App - smart redirect based on auth state
 */
export default function LandingOrApp() {
  const { user, authLoading } = useAuth();
  
  if (authLoading) {
    return <LoadingScreen />;
  }
  
  return user ? <Navigate to="/app" replace /> : <PublicLanding />;
}

