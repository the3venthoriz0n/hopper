import { useState, useCallback } from 'react';
import * as platformService from '../services/platformService';
import { PLATFORM_CONFIG } from '../utils/platformConfig';

/**
 * Hook for managing platform state (YouTube, TikTok, Instagram)
 * @returns {object} Platform state and functions
 */
export function usePlatforms(setMessage) {
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

  // Unified account loading logic for all platforms
  const loadPlatformAccount = useCallback(async (platform, setState, identifierKeys) => {
    try {
      const data = await platformService.loadPlatformAccount(platform);
      
      if (data.error) {
        console.error(`Error loading ${platform} account:`, data.error);
        return;
      }
      
      if (platform === 'tiktok') {
        setState(prev => ({
          ...prev,
          account: data.account,
          token_status: data.token_status || 'valid',
          token_expired: data.token_expired || false,
          token_expires_soon: data.token_expires_soon || false
        }));
        if (data.creator_info) {
          setTiktokCreatorInfo(data.creator_info);
        } else {
          setTiktokCreatorInfo(null);
        }
      } else {
        setState(prev => {
          const newAccount = data.account;
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
      }
    } catch (error) {
      console.error(`Error loading ${platform} account:`, error.response?.data || error.message);
    }
  }, []);

  const loadYoutubeAccount = useCallback(() => {
    return loadPlatformAccount('youtube', setYoutube, ['channel_name', 'email']);
  }, [loadPlatformAccount]);

  const loadTiktokAccount = useCallback(async () => {
    try {
      const data = await platformService.loadPlatformAccount('tiktok');
      if (data.account) {
        setTiktok(prev => ({
          ...prev,
          account: data.account,
          token_status: data.token_status || 'valid',
          token_expired: data.token_expired || false,
          token_expires_soon: data.token_expires_soon || false
        }));
        if (data.creator_info) {
          setTiktokCreatorInfo(data.creator_info);
        } else {
          setTiktokCreatorInfo(null);
        }
      } else {
        setTiktok(prev => ({
          ...prev,
          account: null,
          token_status: data.token_status || prev.token_status || 'valid',
          token_expired: data.token_expired || false,
          token_expires_soon: data.token_expires_soon || false
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
  }, []);

  const loadInstagramAccount = useCallback(() => {
    return loadPlatformAccount('instagram', setInstagram, ['username']);
  }, [loadPlatformAccount]);

  const loadDestinations = useCallback(async () => {
    try {
      const data = await platformService.loadDestinations();
      
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
      
      updatePlatformState(setYoutube, data.youtube);
      updatePlatformState(setTiktok, data.tiktok);
      updatePlatformState(setInstagram, data.instagram);
      
      if (data.youtube.connected) loadYoutubeAccount();
      if (data.tiktok.connected) loadTiktokAccount();
      if (data.instagram.connected) loadInstagramAccount();
    } catch (error) {
      console.error('Error loading destinations:', error);
    }
  }, [loadYoutubeAccount, loadTiktokAccount, loadInstagramAccount]);

  const connectPlatform = useCallback(async (platform, platformName) => {
    try {
      const url = await platformService.connectPlatform(platform);
      window.location.href = url;
    } catch (err) {
      if (setMessage) {
        setMessage(`❌ Error connecting to ${platformName}: ${err.response?.data?.detail || err.message}`);
      }
      console.error(`Error connecting ${platform}:`, err);
    }
  }, [setMessage]);

  const connectYoutube = useCallback(() => connectPlatform('youtube', 'YouTube'), [connectPlatform]);
  const connectTiktok = useCallback(() => connectPlatform('tiktok', 'TikTok'), [connectPlatform]);
  const connectInstagram = useCallback(() => connectPlatform('instagram', 'Instagram'), [connectPlatform]);

  const disconnectPlatform = useCallback(async (platform, setState, platformName) => {
    try {
      await platformService.disconnectPlatform(platform);
      setState({ connected: false, enabled: false, account: null, token_status: 'valid', token_expired: false, token_expires_soon: false });
      if (setMessage) setMessage(`✅ Disconnected from ${platformName}`);
    } catch (err) {
      if (setMessage) setMessage(`❌ Error disconnecting from ${platformName}`);
      console.error(`Error disconnecting ${platform}:`, err);
    }
  }, [setMessage]);

  const disconnectYoutube = useCallback(() => disconnectPlatform('youtube', setYoutube, 'YouTube'), [disconnectPlatform]);
  const disconnectTiktok = useCallback(() => disconnectPlatform('tiktok', setTiktok, 'TikTok'), [disconnectPlatform]);
  const disconnectInstagram = useCallback(() => disconnectPlatform('instagram', setInstagram, 'Instagram'), [disconnectPlatform]);

  const togglePlatform = useCallback(async (platform, currentState, setState) => {
    if (currentState.token_expired) {
      const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);
      if (setMessage) setMessage(`⚠️ Token expired - reconnect your ${platformName} account before enabling uploads`);
      return;
    }

    const newEnabled = !currentState.enabled;
    setState(prev => ({ ...prev, enabled: newEnabled }));
    
    try {
      await platformService.togglePlatform(platform, newEnabled);
    } catch (err) {
      console.error(`Error toggling ${platform}:`, err);
      setState(prev => ({ ...prev, enabled: !newEnabled }));
    }
  }, [setMessage]);

  const toggleYoutube = useCallback(() => togglePlatform('youtube', youtube, setYoutube), [togglePlatform, youtube]);
  const toggleTiktok = useCallback(() => togglePlatform('tiktok', tiktok, setTiktok), [togglePlatform, tiktok]);
  const toggleInstagram = useCallback(() => togglePlatform('instagram', instagram, setInstagram), [togglePlatform, instagram]);

  return {
    youtube,
    tiktok,
    instagram,
    tiktokCreatorInfo,
    setYoutube,
    setTiktok,
    setInstagram,
    loadDestinations,
    loadYoutubeAccount,
    loadTiktokAccount,
    loadInstagramAccount,
    connectYoutube,
    connectTiktok,
    connectInstagram,
    disconnectYoutube,
    disconnectTiktok,
    disconnectInstagram,
    toggleYoutube,
    toggleTiktok,
    toggleInstagram,
  };
}
