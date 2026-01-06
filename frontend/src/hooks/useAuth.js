import { useState, useEffect, useCallback } from 'react';
import axios from '../services/api';
import { getApiUrl } from '../services/api';

/**
 * Custom hook for authentication state management
 * @returns {object} { user, isAdmin, setUser, authLoading, checkAuth }
 */
export function useAuth() {
  const [user, setUser] = useState(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  
  const API = getApiUrl();
  
  const checkAuth = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/me`);
      if (res.data.user) {
        setUser(res.data.user);
        setIsAdmin(res.data.user.is_admin || false);
      } else {
        setUser(null);
        setIsAdmin(false);
      }
    } catch (err) {
      console.error('Auth check failed:', err);
      setUser(null);
      setIsAdmin(false);
    } finally {
      setAuthLoading(false);
    }
  }, [API]);
  
  useEffect(() => {
    checkAuth();
  }, [checkAuth]);
  
  return { user, isAdmin, setUser, authLoading, checkAuth };
}
