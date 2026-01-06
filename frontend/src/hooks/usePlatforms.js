import { useState, useCallback } from 'react';
import axios from '../services/api';
import { getApiUrl } from '../services/api';

/**
 * Hook for managing platform state (YouTube, TikTok, Instagram)
 * Handles connection, enabling/disabling, account loading, and settings
 */
export function usePlatforms() {
  const [youtube, setYoutube] = useState({ 
    connected: false, 
    enabled: false, 
    account: null, 
    token_status: 'valid',
    token_expired: false,
    token_expires_soon: false
  });
  const [tiktok, setTiktok] = useState({ 
    connected: false, 
    enabled: false, 
    account: null, 
    token_status: 'valid',
    token_expired: false,
    token_expires_soon: false
  });
  const [tiktokCreatorInfo, setTiktokCreatorInfo] = useState(null);
  const [instagram, setInstagram] = useState({ 
    connected: false, 
    enabled: false, 
    account: null, 
    token_status: 'valid',
    token_expired: false,
    token_expires_soon: false
  });

  const API = getApiUrl();

  // Unified account loading logic for all platforms
  const loadPlatformAccount = useCallback(async (platform, setState, identifierKeys) => {
    try {
      const res = await axios.get(`${API}/auth/${platform}/account`);
      
      if (res.data.error) {
        console.error(`Error loading ${platform} account:`, res.data.error);
        return;
      }
      
      setState(prev => {
        const newAccount = res.data.account;
        const hasExistingData = identifierKeys.some(key => prev.account?.[key]);
        const hasNewData = newAccount && identifierKeys.some(key => newAccount[key]);
        
        if (hasNewData) {
          return { ...prev, account: newAccount };
        }
        
        if (!hasExistingData && newAccount === null) {
          return { ...prev, account: null };
        }
        
        return prev;
      });
    } catch (error) {
      console.error(`Error loading ${platform} account:`, error.response?.data || error.message);
    }
  }, [API]);

  const loadYoutubeAccount = useCallback(() => {
    return loadPlatformAccount('youtube', setYoutube, ['channel_name', 'email']);
  }, [loadPlatformAccount]);

  const loadTiktokAccount = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/tiktok/account`);
      if (res.data.account) {
        setTiktok(prev => ({
          ...prev,
          account: res.data.account,
          token_status: res.data.token_status || 'valid',
          token_expired: res.data.token_expired || false,
          token_expires_soon: res.data.token_expires_soon || false
        }));
        if (res.data.creator_info) {
          setTiktokCreatorInfo(res.data.creator_info);
        } else {
          setTiktokCreatorInfo(null);
        }
      } else {
        setTiktok(prev => ({
          ...prev,
          account: null,
          token_status: res.data.token_status || prev.token_status || 'valid',
          token_expired: res.data.token_expired || false,
          token_expires_soon: res.data.token_expires_soon || false
        }));
        setTiktokCreatorInfo(null);
      }
    } catch (err) {
      console.error('Error loading TikTok account:', err);
      setTiktok(prev => ({
        ...prev,
        token_status: err.response?.data?.token_status || prev.token_status || 'valid',
        token_expired: err.response?.data?.token_expired || prev.token_expired || false,
        token_expires_soon: err.response?.data?.token_expires_soon || prev.token_expires_soon || false
      }));
    }
  }, [API]);

  const loadInstagramAccount = useCallback(() => {
    return loadPlatformAccount('instagram', setInstagram, ['username']);
  }, [loadPlatformAccount]);

  const loadDestinations = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/destinations`);
      
      const updatePlatformState = (setState, platformData) => {
        setState(prev => {
          const tokenExpired = platformData.token_expired || false;
          const effectiveEnabled = tokenExpired ? false : platformData.enabled;

          return {
            connected: platformData.connected,
            enabled: effectiveEnabled,
            account: platformData.connected ? prev.account : null,
            token_status: platformData.token_status || 'valid',
            token_expired: tokenExpired,
            token_expires_soon: platformData.token_expires_soon || false
          };
        });
      };
      
      updatePlatformState(setYoutube, res.data.youtube);
      updatePlatformState(setTiktok, res.data.tiktok);
      updatePlatformState(setInstagram, res.data.instagram);
      
      if (res.data.youtube.connected) loadYoutubeAccount();
      if (res.data.tiktok.connected) loadTiktokAccount();
      if (res.data.instagram.connected) loadInstagramAccount();
    } catch (error) {
      console.error('Error loading destinations:', error);
    }
  }, [API, loadYoutubeAccount, loadTiktokAccount, loadInstagramAccount]);

  const connectPlatform = useCallback(async (platform, platformName, setMessage) => {
    try {
      const res = await axios.get(`${API}/auth/${platform}`);
      window.location.href = res.data.url;
    } catch (err) {
      if (setMessage) {
        setMessage(`❌ Error connecting to ${platformName}: ${err.response?.data?.detail || err.message}`);
      }
      console.error(`Error connecting ${platform}:`, err);
    }
  }, [API]);

  const connectYoutube = useCallback((setMessage) => connectPlatform('youtube', 'YouTube', setMessage), [connectPlatform]);
  const connectTiktok = useCallback((setMessage) => connectPlatform('tiktok', 'TikTok', setMessage), [connectPlatform]);
  const connectInstagram = useCallback((setMessage) => connectPlatform('instagram', 'Instagram', setMessage), [connectPlatform]);

  const disconnectPlatform = useCallback(async (platform, setState, platformName, setMessage) => {
    try {
      await axios.post(`${API}/auth/${platform}/disconnect`);
      setState({ connected: false, enabled: false, account: null });
      if (setMessage) {
        setMessage(`✅ Disconnected from ${platformName}`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage(`❌ Error disconnecting from ${platformName}`);
      }
      console.error(`Error disconnecting ${platform}:`, err);
    }
  }, [API]);

  const disconnectYoutube = useCallback((setMessage) => disconnectPlatform('youtube', setYoutube, 'YouTube', setMessage), [disconnectPlatform]);
  const disconnectTiktok = useCallback((setMessage) => disconnectPlatform('tiktok', setTiktok, 'TikTok', setMessage), [disconnectPlatform]);
  const disconnectInstagram = useCallback((setMessage) => disconnectPlatform('instagram', setInstagram, 'Instagram', setMessage), [disconnectPlatform]);

  const togglePlatform = useCallback(async (platform, currentState, setState, setMessage) => {
    if (currentState.token_expired) {
      if (setMessage) {
        setMessage(`⚠️ Token expired - reconnect your ${platform.charAt(0).toUpperCase() + platform.slice(1)} account before enabling uploads`);
      }
      return;
    }

    const newEnabled = !currentState.enabled;
    setState(prev => ({ ...prev, enabled: newEnabled }));
    
    try {
      await axios.post(`${API}/destinations/${platform}/toggle`, {
        enabled: newEnabled
      });
    } catch (err) {
      console.error(`Error toggling ${platform}:`, err);
      setState(prev => ({ ...prev, enabled: !newEnabled }));
    }
  }, [API]);

  const toggleYoutube = useCallback((setMessage) => togglePlatform('youtube', youtube, setYoutube, setMessage), [togglePlatform, youtube]);
  const toggleTiktok = useCallback((setMessage) => togglePlatform('tiktok', tiktok, setTiktok, setMessage), [togglePlatform, tiktok]);
  const toggleInstagram = useCallback((setMessage) => togglePlatform('instagram', instagram, setInstagram, setMessage), [togglePlatform, instagram]);

  return {
    // State
    youtube,
    tiktok,
    instagram,
    tiktokCreatorInfo,
    setYoutube,
    setTiktok,
    setInstagram,
    setTiktokCreatorInfo,
    // Load functions
    loadDestinations,
    loadYoutubeAccount,
    loadTiktokAccount,
    loadInstagramAccount,
    // Connect functions
    connectYoutube,
    connectTiktok,
    connectInstagram,
    // Disconnect functions
    disconnectYoutube,
    disconnectTiktok,
    disconnectInstagram,
    // Toggle functions
    toggleYoutube,
    toggleTiktok,
    toggleInstagram,
  };
}

