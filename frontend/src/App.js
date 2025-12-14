import React, { useState, useEffect, useCallback } from 'react';
import { Routes, Route, Link, useNavigate, useLocation, Navigate } from 'react-router-dom';
import axios from 'axios';
import './App.css';
import Terms from './Terms';
import Privacy from './Privacy';
import DeleteYourData from './DeleteYourData';
import Login from './Login';
import AdminDashboard from './AdminDashboard';

// Configure axios to send cookies with every request
axios.defaults.withCredentials = true;

// CSRF Token Management
let csrfToken = null;

// Intercept GET responses to extract CSRF token
axios.interceptors.response.use(
  (response) => {
    // Extract CSRF token from response header
    // Axios normalizes headers to lowercase
    const token = response.headers['x-csrf-token'] || response.headers['X-CSRF-Token'];
    if (token) {
      csrfToken = token;
    }
    return response;
  },
  (error) => {
    // Handle 401 errors globally - force re-authentication
    if (error.response?.status === 401 && !error.config.url?.includes('/auth/')) {
      // Clear user state and let the auth check redirect to login
      window.location.reload();
    }
    return Promise.reject(error);
  }
);

// Intercept POST/PATCH/DELETE/PUT requests to add CSRF token
axios.interceptors.request.use(
  (config) => {
    // Add CSRF token to state-changing requests
    if (['post', 'patch', 'delete', 'put'].includes(config.method?.toLowerCase())) {
      if (csrfToken) {
        config.headers['X-CSRF-Token'] = csrfToken;
      }
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

function Home() {
  const navigate = useNavigate();
  
  // Build API URL at runtime - always use HTTPS
  const getApiUrl = () => {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
    return `${backendUrl}/api`;
  };
  
  const API = getApiUrl();
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';
  
  // Authentication state
  const [user, setUser] = useState(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  
  // All state hooks must be declared before any conditional returns (Rules of Hooks)
  const [youtube, setYoutube] = useState({ connected: false, enabled: false, account: null, token_status: 'valid' });
  const [tiktok, setTiktok] = useState({ connected: false, enabled: false, account: null, token_status: 'valid' });
  const [instagram, setInstagram] = useState({ connected: false, enabled: false, account: null, token_status: 'valid' });
  const [videos, setVideos] = useState([]);
  const [message, setMessage] = useState('');
  const [globalSettings, setGlobalSettings] = useState({
    title_template: '{filename}',
    description_template: 'Uploaded via Hopper',
    wordbank: [],
    upload_immediately: true,
    schedule_mode: 'spaced',
    schedule_interval_value: 1,
    schedule_interval_unit: 'hours',
    schedule_start_time: '',
    upload_first_immediately: true,
    allow_duplicates: false
  });
  const [youtubeSettings, setYoutubeSettings] = useState({ 
    visibility: 'private', 
    made_for_kids: false,
    title_template: '',
    description_template: '',
    tags_template: ''
  });
  const [youtubeVideos, setYoutubeVideos] = useState([]);
  const [youtubeVideosPage, setYoutubeVideosPage] = useState(1);
  const [youtubeVideosTotalPages, setYoutubeVideosTotalPages] = useState(0);
  const [loadingYoutubeVideos, setLoadingYoutubeVideos] = useState(false);
  const [expandedVideos, setExpandedVideos] = useState(new Set());
  const [tiktokSettings, setTiktokSettings] = useState({
    privacy_level: 'private',
    allow_comments: true,
    allow_duet: true,
    allow_stitch: true,
    title_template: '',
    description_template: ''
  });
  const [instagramSettings, setInstagramSettings] = useState({
    caption_template: '',
    location_id: '',
    disable_comments: false,
    disable_likes: false
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showTiktokSettings, setShowTiktokSettings] = useState(false);
  const [showInstagramSettings, setShowInstagramSettings] = useState(false);
  const [showGlobalSettings, setShowGlobalSettings] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [newWord, setNewWord] = useState('');
  const [wordbankExpanded, setWordbankExpanded] = useState(false);
  const [maxFileSize, setMaxFileSize] = useState(null);
  
  // Subscription & token state
  const [subscription, setSubscription] = useState(null);
  const [tokenBalance, setTokenBalance] = useState(null);
  const [availablePlans, setAvailablePlans] = useState([]);
  const [loadingSubscription, setLoadingSubscription] = useState(false);
  const [notification, setNotification] = useState(null); // For popup notifications
  const [confirmDialog, setConfirmDialog] = useState(null); // For confirmation dialogs

  // Check if user is authenticated
  useEffect(() => {
    // Check for Google login callback
    const urlParams = new URLSearchParams(window.location.search);
    const googleLogin = urlParams.get('google_login');
    
    if (googleLogin === 'success') {
      setMessage('✅ Successfully logged in with Google!');
      window.history.replaceState({}, '', '/');
      // Close popup if this is a popup window
      if (window.opener) {
        window.close();
      }
    } else if (googleLogin === 'error') {
      setMessage('❌ Google login failed. Please try again.');
      window.history.replaceState({}, '', '/');
      // Close popup if this is a popup window
      if (window.opener) {
        window.close();
      }
    }
    
    checkAuth();
  }, []);
  
  const checkAuth = async () => {
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
  };
  
  const handleLogout = async () => {
    try {
      await axios.post(`${API}/auth/logout`);
      setUser(null);
      setMessage('✅ Logged out successfully');
      setShowAccountSettings(false);
    } catch (err) {
      console.error('Logout failed:', err);
      setMessage('❌ Logout failed');
    }
  };

  const handleDeleteAccount = async () => {
    try {
      await axios.delete(`${API}/auth/account`, {
        headers: { 'X-CSRF-Token': csrfToken }
      });
      setMessage('✅ Your account has been permanently deleted');
      setShowDeleteConfirm(false);
      setShowAccountSettings(false);
      // Redirect to login after a short delay
      setTimeout(() => {
        window.location.href = '/login';
      }, 1500);
    } catch (err) {
      console.error('Error deleting account:', err);
      setMessage(err.response?.data?.detail || '❌ Failed to delete account');
      setShowDeleteConfirm(false);
    }
  };
  
  // Set document title based on environment
  useEffect(() => {
    document.title = isProduction ? 'hopper' : 'DEV HOPPER';
  }, [isProduction]);

  // Tooltip positioning handler to keep tooltips on screen
  // This useEffect must be declared before conditional returns (Rules of Hooks)
  useEffect(() => {
    // Only set up tooltips if user is authenticated
    if (!user) return;
    
    const adjustTooltipPosition = (tooltipWrapper) => {
      const tooltip = tooltipWrapper.querySelector('.tooltip-text');
      if (!tooltip) return;
      
      // Don't force visibility - let CSS hover handle it
      // Only adjust positioning, not visibility/opacity
      const wrapperRect = tooltipWrapper.getBoundingClientRect();
      const margin = 10;
      
      // Find if we're inside a modal - use modal bounds instead of window
      const modal = tooltipWrapper.closest('.modal');
      let viewportWidth, viewportHeight, viewportLeft, viewportTop;
      
      if (modal) {
        const modalRect = modal.getBoundingClientRect();
        viewportWidth = modalRect.width;
        viewportHeight = modalRect.height;
        viewportLeft = modalRect.left;
        viewportTop = modalRect.top;
      } else {
        viewportWidth = window.innerWidth;
        viewportHeight = window.innerHeight;
        viewportLeft = 0;
        viewportTop = 0;
      }
      
      // Reset positioning (but keep visibility/opacity from CSS)
      tooltip.style.transform = '';
      tooltip.style.left = '';
      tooltip.style.right = '';
      tooltip.style.bottom = '';
      tooltip.style.top = '';
      tooltip.style.maxHeight = '';
      tooltip.style.overflowY = '';
      tooltip.classList.remove('tooltip-below');
      
      // Get tooltip dimensions after reset
      const rect = tooltip.getBoundingClientRect();
      const tooltipHeight = rect.height;
      
      // Calculate available space relative to viewport
      const spaceAbove = wrapperRect.top - viewportTop;
      const spaceBelow = (viewportTop + viewportHeight) - wrapperRect.bottom;
      
      // Decide vertical position
      let showBelow = spaceAbove < tooltipHeight + margin && spaceBelow > spaceAbove;
      if (showBelow) {
        tooltip.classList.add('tooltip-below');
        tooltip.style.bottom = 'auto';
        tooltip.style.top = '125%';
      } else {
        tooltip.style.top = 'auto';
        tooltip.style.bottom = '125%';
      }
      
      // Adjust horizontal position
      requestAnimationFrame(() => {
        const newRect = tooltip.getBoundingClientRect();
        const tooltipLeft = newRect.left - viewportLeft;
        const tooltipRight = newRect.right - viewportLeft;
        
        if (tooltipLeft < margin) {
          // Too far left - align to left edge
          tooltip.style.left = `${margin - (wrapperRect.left - viewportLeft)}px`;
          tooltip.style.transform = 'translateX(0)';
        } else if (tooltipRight > viewportWidth - margin) {
          // Too far right - align to right edge
          tooltip.style.left = 'auto';
          tooltip.style.right = `${margin}px`;
          tooltip.style.transform = 'translateX(0)';
        } else {
          // Center it
          tooltip.style.left = '50%';
          tooltip.style.transform = 'translateX(-50%)';
        }
        
        // Final vertical check
        requestAnimationFrame(() => {
          const finalRect = tooltip.getBoundingClientRect();
          const finalTop = finalRect.top - viewportTop;
          const finalBottom = finalRect.bottom - viewportTop;
          
          if (finalTop < margin) {
            tooltip.style.top = `${margin - (wrapperRect.top - viewportTop) + wrapperRect.height}px`;
            tooltip.style.bottom = 'auto';
          }
          if (finalBottom > viewportHeight - margin) {
            const availableHeight = viewportHeight - finalTop - margin - 10;
            if (availableHeight > 50) {
              tooltip.style.maxHeight = `${availableHeight}px`;
              tooltip.style.overflowY = 'auto';
            } else {
              // Not enough space, try showing above
              tooltip.style.top = 'auto';
              tooltip.style.bottom = '125%';
              tooltip.classList.remove('tooltip-below');
            }
          }
        });
      });
    };
    
    const handleTooltipHover = (e) => {
      const wrapper = e.currentTarget;
      // Wait for CSS hover to apply, then adjust position
      setTimeout(() => {
        const tooltip = wrapper.querySelector('.tooltip-text');
        if (tooltip) {
          // Check if tooltip is actually visible (CSS hover applied)
          const computedStyle = window.getComputedStyle(tooltip);
          if (computedStyle.visibility === 'visible' || computedStyle.opacity !== '0') {
            adjustTooltipPosition(wrapper);
          }
        }
      }, 10);
    };
    
    const handleTooltipLeave = (e) => {
      const wrapper = e.currentTarget;
      const tooltip = wrapper.querySelector('.tooltip-text');
      if (tooltip) {
        // Reset any positioning adjustments when leaving
        tooltip.style.maxHeight = '';
        tooltip.style.overflowY = '';
      }
    };
    
    // Add listeners to all tooltip wrappers
    const addListeners = () => {
      const tooltipWrappers = document.querySelectorAll('.tooltip-wrapper');
      tooltipWrappers.forEach(wrapper => {
        wrapper.removeEventListener('mouseenter', handleTooltipHover);
        wrapper.removeEventListener('mouseleave', handleTooltipLeave);
        wrapper.addEventListener('mouseenter', handleTooltipHover);
        wrapper.addEventListener('mouseleave', handleTooltipLeave);
      });
    };
    
    // Initial setup
    addListeners();
    
    // Re-setup when DOM changes
    const observer = new MutationObserver(addListeners);
    observer.observe(document.body, { childList: true, subtree: true });
    
    // Handle window resize and scroll
    const handleResize = () => {
      const visibleTooltips = document.querySelectorAll('.tooltip-wrapper:hover');
      visibleTooltips.forEach(wrapper => {
        adjustTooltipPosition(wrapper);
      });
    };
    
    window.addEventListener('resize', handleResize);
    window.addEventListener('scroll', handleResize, true);
    
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('scroll', handleResize, true);
      const tooltipWrappers = document.querySelectorAll('.tooltip-wrapper');
      tooltipWrappers.forEach(wrapper => {
        wrapper.removeEventListener('mouseenter', handleTooltipHover);
        wrapper.removeEventListener('mouseleave', handleTooltipLeave);
      });
    };
  }, [videos, editingVideo, showSettings, showTiktokSettings, showGlobalSettings, showAccountSettings, showDeleteConfirm, user]);

  // Define all load functions using useCallback BEFORE the useEffect that uses them
  // This ensures they're available when the useEffect runs
  const loadUploadLimits = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/upload/limits`);
      setMaxFileSize(res.data);
    } catch (err) {
      console.error('Error loading upload limits:', err);
    }
  }, [API]);

  // Load subscription and token balance
  const loadSubscription = useCallback(async () => {
    if (!user) return;
    
    try {
      const [subscriptionRes, plansRes] = await Promise.all([
        axios.get(`${API}/subscription/current`),
        axios.get(`${API}/subscription/plans`)
      ]);
      
      setSubscription(subscriptionRes.data.subscription);
      setTokenBalance(subscriptionRes.data.token_balance);
      setAvailablePlans(plansRes.data.plans || []);
    } catch (err) {
      console.error('Error loading subscription:', err);
    }
  }, [API, user]);

  // Load subscription when user changes
  useEffect(() => {
    if (user) {
      loadSubscription();
    }
  }, [user, loadSubscription]);

  // Refresh token balance periodically (every 5 seconds) to keep it updated
  useEffect(() => {
    if (!user) return;
    
    const tokenRefreshInterval = setInterval(() => {
      loadSubscription();
    }, 5000);
    
    return () => clearInterval(tokenRefreshInterval);
  }, [user, loadSubscription]);

  // Handle subscription upgrade
  const handleUpgrade = async (planKey) => {
    setLoadingSubscription(true);
    try {
      const res = await axios.post(`${API}/subscription/create-checkout`, { plan_key: planKey });
      if (res.data.url) {
        window.location.href = res.data.url;
      }
    } catch (err) {
      console.error('Error creating checkout session:', err);
      setMessage('❌ Failed to start checkout. Please try again.');
    } finally {
      setLoadingSubscription(false);
    }
  };

  // Handle manage subscription (Stripe customer portal)
  const handleManageSubscription = async () => {
    setLoadingSubscription(true);
    try {
      const res = await axios.get(`${API}/subscription/portal`);
      if (res.data.url) {
        window.location.href = res.data.url;
      }
    } catch (err) {
      console.error('Error opening customer portal:', err);
      setMessage('❌ Failed to open subscription portal. Please try again.');
    } finally {
      setLoadingSubscription(false);
    }
  };

  const loadVideos = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/videos`);
      const newData = res.data;
      
      setVideos(prevVideos => {
        // Check for new token-related failures
        if (prevVideos && prevVideos.length > 0) {
          newData.forEach(newVideo => {
            const prevVideo = prevVideos.find(v => v.id === newVideo.id);
            // If video status changed to "failed" with token error
            if (prevVideo && prevVideo.status !== 'failed' && newVideo.status === 'failed') {
              if (newVideo.error && newVideo.error.toLowerCase().includes('insufficient tokens')) {
                // Show popup notification
                setNotification({
                  type: 'error',
                  title: 'Insufficient Tokens',
                  message: newVideo.error || `Not enough tokens to upload "${newVideo.filename}". Please upgrade your plan or wait for your token balance to reset.`,
                  videoFilename: newVideo.filename
                });
                // Auto-dismiss after 10 seconds
                setTimeout(() => setNotification(null), 10000);
              }
            }
          });
        }
        
        if (JSON.stringify(prevVideos) === JSON.stringify(newData)) {
          return prevVideos;
        }
        
        return newData;
      });
      
      // Refresh token balance when videos change (in case tokens were deducted)
      // Do this outside setState to avoid dependency issues
      if (user) {
        loadSubscription();
      }
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  }, [API, user, loadSubscription]);

  // Calculate tokens required for a file (1 token = 10MB)
  const calculateTokens = (fileSizeBytes) => {
    if (!fileSizeBytes) return 0;
    const sizeMB = fileSizeBytes / (1024 * 1024);
    const tokens = Math.ceil(sizeMB / 10);
    return Math.max(1, tokens); // Minimum 1 token
  };

  // Format file size for display
  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(2)} ${units[unitIndex]}`;
  };

  // Unified account loading logic for all platforms
  // Only updates account if new data is complete (has required identifier fields)
  const loadPlatformAccount = useCallback(async (platform, setState, identifierKeys) => {
    try {
      const res = await axios.get(`${API}/auth/${platform}/account`);
      
      if (res.data.error) {
        console.error(`Error loading ${platform} account:`, res.data.error);
        // Keep existing account info on error
        return;
      }
      
      setState(prev => {
        const newAccount = res.data.account;
        const hasExistingData = identifierKeys.some(key => prev.account?.[key]);
        const hasNewData = newAccount && identifierKeys.some(key => newAccount[key]);
        
        // Only update if new data has required identifier fields
        // This prevents "Unknown account" from showing when backend returns incomplete data
        if (hasNewData) {
          return { ...prev, account: newAccount };
        }
        
        // If new data is incomplete, only update if we have no existing data AND backend explicitly returned null
        if (!hasExistingData && newAccount === null) {
          return { ...prev, account: null };
        }
        
        // Otherwise keep existing state (shows "Loading account..." if no data yet)
        return prev;
      });
    } catch (error) {
      console.error(`Error loading ${platform} account:`, error.response?.data || error.message);
      // Keep existing account info on error - do nothing
    }
  }, [API]);

  const loadYoutubeAccount = useCallback(() => {
    return loadPlatformAccount('youtube', setYoutube, ['channel_name', 'email']);
  }, [loadPlatformAccount]);

  const loadTiktokAccount = useCallback(() => {
    return loadPlatformAccount('tiktok', setTiktok, ['display_name', 'username']);
  }, [loadPlatformAccount]);

  const loadInstagramAccount = useCallback(() => {
    return loadPlatformAccount('instagram', setInstagram, ['username']);
  }, [loadPlatformAccount]);

  const loadDestinations = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/destinations`);
      
      // Unified pattern for all platforms: Update connection/enabled status, preserve account info
      // Only clear account if explicitly disconnected
      const updatePlatformState = (setState, platformData) => {
        setState(prev => ({
          connected: platformData.connected,
          enabled: platformData.enabled,
          account: platformData.connected ? prev.account : null,
          token_status: platformData.token_status || 'valid',
          token_expired: platformData.token_expired || false,
          token_expires_soon: platformData.token_expires_soon || false
        }));
      };
      
      updatePlatformState(setYoutube, res.data.youtube);
      updatePlatformState(setTiktok, res.data.tiktok);
      updatePlatformState(setInstagram, res.data.instagram);
      
      // Load account info for connected platforms
      if (res.data.youtube.connected) loadYoutubeAccount();
      if (res.data.tiktok.connected) loadTiktokAccount();
      if (res.data.instagram.connected) loadInstagramAccount();
    } catch (error) {
      console.error('Error loading destinations:', error);
    }
  }, [API, loadYoutubeAccount, loadTiktokAccount, loadInstagramAccount]);

  const loadGlobalSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/global/settings`);
      setGlobalSettings(res.data);
    } catch (err) {
      console.error('Error loading global settings:', err);
    }
  }, [API]);

  const loadYoutubeSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/youtube/settings`);
      setYoutubeSettings(res.data);
    } catch (err) {
      console.error('Error loading settings:', err);
    }
  }, [API]);

  const loadTiktokSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/tiktok/settings`);
      setTiktokSettings(res.data);
    } catch (err) {
      console.error('Error loading TikTok settings:', err);
    }
  }, [API]);

  const loadInstagramSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/instagram/settings`);
      setInstagramSettings(res.data);
    } catch (err) {
      console.error('Error loading Instagram settings:', err);
    }
  }, [API]);

  // Unified OAuth callback handler for all platforms
  // Sets connection status and loads account info immediately
  const applyOAuthStatus = useCallback((platform, setState, loadAccount) => {
    const urlParams = new URLSearchParams(window.location.search);
    const statusParam = urlParams.get('status');
    
    // Parse status from OAuth callback
    let connected = true;
    let enabled = true;
    
    if (statusParam) {
      try {
        const status = JSON.parse(decodeURIComponent(statusParam));
        connected = status.connected !== false;
        enabled = status.enabled !== false;
      } catch (e) {
        console.error(`Error parsing ${platform} status:`, e);
      }
    }
    
    // Set connection status optimistically
    setState(prev => ({
      ...prev,
      connected,
      enabled
    }));
    
    // Load full destinations and account info
    loadDestinations();
    loadAccount();
  }, [loadDestinations]);

  // Data loading useEffect - must be declared before conditional returns (Rules of Hooks)
  useEffect(() => {
    // Only load data if user is authenticated
    if (!user) return;
    
    loadDestinations();
    loadGlobalSettings();
    loadYoutubeSettings();
    loadTiktokSettings();
    loadInstagramSettings();
    loadVideos();
    loadUploadLimits();
    
    // Check OAuth callbacks - use consistent pattern for all platforms
    if (window.location.search.includes('connected=youtube')) {
      setMessage('✅ YouTube connected!');
      applyOAuthStatus('youtube', setYoutube, loadYoutubeAccount);
      window.history.replaceState({}, '', '/');
    } else if (window.location.search.includes('connected=tiktok')) {
      setMessage('✅ TikTok connected!');
      applyOAuthStatus('tiktok', setTiktok, loadTiktokAccount);
      window.history.replaceState({}, '', '/');
    } else if (window.location.search.includes('connected=instagram')) {
      setMessage('✅ Instagram connected!');
      applyOAuthStatus('instagram', setInstagram, loadInstagramAccount);
      window.history.replaceState({}, '', '/');
    }
    
    // Poll for video updates every 5 seconds
    const pollInterval = setInterval(() => {
      loadVideos();
    }, 5000);
    
    return () => clearInterval(pollInterval);
  }, [user, loadDestinations, loadGlobalSettings, loadYoutubeSettings, loadTiktokSettings, loadInstagramSettings, loadVideos, loadYoutubeAccount, loadTiktokAccount, loadInstagramAccount, applyOAuthStatus, loadUploadLimits]);
  
  // Show login page if not authenticated (AFTER all hooks are declared)
  if (authLoading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: '#1a1a2e',
        color: 'white'
      }}>
        <div>Loading...</div>
      </div>
    );
  }
  
  if (!user) {
    return <Login onLoginSuccess={(userData) => {
      setUser(userData);
      checkAuth();
    }} />;
  }

  const updateGlobalSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      // URLSearchParams automatically converts booleans to strings
      // FastAPI Query() will convert them back to booleans
      params.append(key, value);
      const res = await axios.post(`${API}/global/settings?${params.toString()}`);
      setGlobalSettings(res.data);
      setMessage(`✅ Settings updated`);
    } catch (err) {
      setMessage('❌ Error updating settings');
      console.error('Error updating settings:', err);
    }
  };

  const updateYoutubeSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/youtube/settings?${params.toString()}`);
      setYoutubeSettings(res.data);
      
      if (key === 'visibility') {
        setMessage(`✅ Default visibility set to ${value}`);
      } else if (key === 'made_for_kids') {
        setMessage(`✅ Made for kids: ${value ? 'Yes' : 'No'}`);
      } else if (key === 'title_template' || key === 'description_template') {
        setMessage(`✅ Settings updated`);
      } else {
        setMessage(`✅ Settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating settings');
    }
  };

  const loadYoutubeVideos = async (page = 1, hideShorts = false) => {
    if (!youtube.connected) return;
    
    setLoadingYoutubeVideos(true);
    try {
      const res = await axios.get(`${API}/youtube/videos?page=${page}&per_page=50&hide_shorts=${hideShorts}`);
      setYoutubeVideos(res.data.videos);
      setYoutubeVideosPage(res.data.page);
      setYoutubeVideosTotalPages(res.data.total_pages);
    } catch (err) {
      console.error('Error loading YouTube videos:', err);
      setMessage('❌ Error loading YouTube videos');
    } finally {
      setLoadingYoutubeVideos(false);
    }
  };

  const updateTiktokSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/tiktok/settings?${params.toString()}`);
      setTiktokSettings(res.data);
      
      if (key === 'privacy_level') {
        setMessage(`✅ Privacy level set to ${value}`);
      } else {
        setMessage(`✅ TikTok settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating TikTok settings');
    }
  };

  const updateInstagramSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/instagram/settings?${params.toString()}`);
      setInstagramSettings(res.data);
      setMessage(`✅ Instagram settings updated`);
    } catch (err) {
      setMessage('❌ Error updating Instagram settings');
    }
  };

  // Unified connect function for all platforms
  const connectPlatform = async (platform, platformName) => {
    try {
      const res = await axios.get(`${API}/auth/${platform}`);
      window.location.href = res.data.url;
    } catch (err) {
      setMessage(`❌ Error connecting to ${platformName}: ${err.response?.data?.detail || err.message}`);
      console.error(`Error connecting ${platform}:`, err);
    }
  };

  const connectYoutube = () => connectPlatform('youtube', 'YouTube');
  const connectTiktok = () => connectPlatform('tiktok', 'TikTok');
  const connectInstagram = () => connectPlatform('instagram', 'Instagram');

  // Unified disconnect function for all platforms
  const disconnectPlatform = async (platform, setState, platformName) => {
    try {
      await axios.post(`${API}/auth/${platform}/disconnect`);
      setState({ connected: false, enabled: false, account: null });
      setMessage(`✅ Disconnected from ${platformName}`);
    } catch (err) {
      setMessage(`❌ Error disconnecting from ${platformName}`);
      console.error(`Error disconnecting ${platform}:`, err);
    }
  };

  const disconnectYoutube = () => disconnectPlatform('youtube', setYoutube, 'YouTube');
  const disconnectTiktok = () => disconnectPlatform('tiktok', setTiktok, 'TikTok');
  const disconnectInstagram = () => disconnectPlatform('instagram', setInstagram, 'Instagram');

  // Unified toggle function for all platforms
  const togglePlatform = async (platform, currentState, setState) => {
    const newEnabled = !currentState.enabled;
    setState({ ...currentState, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/${platform}/toggle?${params.toString()}`);
    } catch (err) {
      console.error(`Error toggling ${platform}:`, err);
      // Revert on error
      setState({ ...currentState, enabled: !newEnabled });
    }
  };

  const toggleYoutube = () => togglePlatform('youtube', youtube, setYoutube);
  const toggleTiktok = () => togglePlatform('tiktok', tiktok, setTiktok);
  const toggleInstagram = () => togglePlatform('instagram', instagram, setInstagram);

  const addWordToWordbank = async (input) => {
    try {
      // Split by comma, trim, and filter empty strings
      const words = input.split(',').map(w => w.trim()).filter(w => w);
      
      if (words.length === 0) {
        setMessage('❌ No valid words to add');
        return;
      }
      
      // Add each word individually (backend prevents duplicates)
      let addedCount = 0;
      for (const word of words) {
        try {
          const params = new URLSearchParams();
          params.append('word', word);
          const res = await axios.post(`${API}/global/wordbank?${params.toString()}`);
          setGlobalSettings({...globalSettings, wordbank: res.data.wordbank});
          addedCount++;
        } catch (err) {
          console.error(`Error adding word "${word}":`, err);
        }
      }
      
      setNewWord('');
      if (addedCount === words.length) {
        setMessage(`✅ Added ${addedCount} word${addedCount !== 1 ? 's' : ''} to wordbank`);
      } else {
        setMessage(`✅ Added ${addedCount} of ${words.length} words (some were duplicates)`);
      }
      
      // Reload settings to get final wordbank state
      await loadGlobalSettings();
    } catch (err) {
      setMessage('❌ Error adding words');
      console.error('Error adding words:', err);
    }
  };

  const removeWordFromWordbank = async (word) => {
    try {
      await axios.delete(`${API}/global/wordbank/${encodeURIComponent(word)}`);
      setGlobalSettings({...globalSettings, wordbank: globalSettings.wordbank.filter(w => w !== word)});
      setMessage('✅ Word removed from wordbank');
    } catch (err) {
      setMessage('❌ Error removing word');
      console.error('Error removing word:', err);
    }
  };

  const clearWordbank = async () => {
    if (!window.confirm(`Clear all ${globalSettings.wordbank.length} words from wordbank?`)) {
      return;
    }
    try {
      await axios.delete(`${API}/global/wordbank`);
      setGlobalSettings({...globalSettings, wordbank: []});
      setWordbankExpanded(false);
      setMessage('✅ Wordbank cleared');
    } catch (err) {
      setMessage('❌ Error clearing wordbank');
      console.error('Error clearing wordbank:', err);
    }
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => 
      f.type.startsWith('video/')
    );
    files.forEach(addVideo);
  };

  const addVideo = async (file) => {
    // Client-side file size validation (before upload)
    const maxSizeBytes = maxFileSize?.max_file_size_bytes || 10 * 1024 * 1024 * 1024; // Default 10GB
    if (file.size > maxSizeBytes) {
      const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
      const fileSizeGB = (file.size / (1024 * 1024 * 1024)).toFixed(2);
      const maxSizeDisplay = maxFileSize?.max_file_size_display || '10 GB';
      const errorMsg = `File too large: ${file.name} is ${fileSizeMB} MB (${fileSizeGB} GB). Maximum file size is ${maxSizeDisplay}.`;
      
      // Show popup notification immediately
      setNotification({
        type: 'error',
        title: 'File Too Large',
        message: errorMsg,
        videoFilename: file.name
      });
      setTimeout(() => setNotification(null), 10000);
      setMessage(`❌ ${errorMsg}`);
      return;
    }
    
    // Calculate tokens required for this file (for display purposes)
    const tokensRequired = calculateTokens(file.size);
    
    const form = new FormData();
    form.append('file', file);
    
    // Add CSRF token to form data as fallback (backend checks both header and form data)
    if (csrfToken) {
      form.append('csrf_token', csrfToken);
    }
    
    // Add temp entry with uploading status
    // Generate unique ID: timestamp + random to prevent collisions when adding multiple videos simultaneously
    const tempId = `temp-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const tempVideo = {
      id: tempId,
      filename: file.name,
      status: 'uploading',
      progress: 0,
      file_size_bytes: file.size,
      tokens_consumed: 0  // Tokens not consumed yet - only on successful upload to platforms
    };
    setVideos(prev => [...prev, tempVideo]);
    
      try {
        // Calculate timeout based on file size (allow 1 minute per 100MB, minimum 5 minutes, maximum 2 hours)
        const timeoutMs = Math.max(5 * 60 * 1000, Math.min(2 * 60 * 60 * 1000, (file.size / (100 * 1024 * 1024)) * 60 * 1000));
        
        const res = await axios.post(`${API}/videos`, form, {
          timeout: timeoutMs,
          maxContentLength: Infinity,
          maxBodyLength: Infinity,
          onUploadProgress: (progressEvent) => {
            if (progressEvent.total) {
              const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
              setVideos(prev => prev.map(v =>
                v.id === tempId ? { ...v, progress: percent } : v
              ));
            }
          }
        });
        
        // Replace temp with real video data - backend now returns full video object
        setVideos(prev => {
          // Remove temp entry and add the real video at the end (maintains order)
          const withoutTemp = prev.filter(v => v.id !== tempId);
          return [...withoutTemp, res.data];
        });
        
        setMessage(`✅ Added ${file.name} to queue (will cost ${tokensRequired} ${tokensRequired === 1 ? 'token' : 'tokens'} on upload)`);
      } catch (err) {
        setVideos(prev => prev.filter(v => v.id !== tempId));
        
        // Enhanced error detection
        const isTimeout = err.code === 'ECONNABORTED' || err.message?.includes('timeout') || err.message?.includes('Timeout');
        const isNetworkError = !err.response && (err.code === 'ERR_NETWORK' || err.code === 'ECONNRESET' || err.code === 'ETIMEDOUT');
        const isFileSizeError = err.response?.status === 413 || 
                                (!err.response && file.size > maxSizeBytes) ||
                                (err.message && (err.message.includes('413') || err.message.includes('Payload Too Large')));
        
        let errorMsg = err.response?.data?.detail || err.message || 'Error adding video';
        
        // Handle timeout errors
        if (isTimeout) {
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
          const timeoutMinutes = (timeoutMs / (60 * 1000)).toFixed(1);
          
          // Check if this might be a proxy timeout (Cloudflare free plan: 100s, paid: 600s)
          const isLikelyProxyTimeout = timeoutMs >= 100000 && fileSizeMB < 500; // If timeout is high but file is relatively small
          
          if (isLikelyProxyTimeout) {
            errorMsg = `Upload timeout: The file "${file.name}" (${fileSizeMB} MB) timed out after ${timeoutMinutes} minutes. This is likely due to a proxy timeout (e.g., Cloudflare has a 100-second limit on free plans). Please try again or contact support.`;
          } else {
            errorMsg = `Upload timeout: The file "${file.name}" (${fileSizeMB} MB) timed out after ${timeoutMinutes} minutes. The connection may be too slow or there may be a proxy timeout. Please try a smaller file or check your internet connection.`;
          }
          
          setNotification({
            type: 'error',
            title: 'Upload Timeout',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 20000);
        }
        // Handle network errors (connection reset, network failure, etc.)
        else if (isNetworkError) {
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
          errorMsg = `Network error: The upload of "${file.name}" (${fileSizeMB} MB) was interrupted. This may be due to file size limits, network issues, or server timeout. Please try a smaller file.`;
          
          setNotification({
            type: 'error',
            title: 'Upload Failed',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 15000);
        }
        // Handle file size errors
        else if (isFileSizeError) {
          // File too large - show popup notification
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
          const fileSizeGB = (file.size / (1024 * 1024 * 1024)).toFixed(2);
          const maxSizeDisplay = maxFileSize?.max_file_size_display || '10 GB';
          errorMsg = err.response?.data?.detail || `File too large: ${file.name} is ${fileSizeMB} MB (${fileSizeGB} GB). Maximum file size is ${maxSizeDisplay}.`;
          
          // Show popup notification for file size error
          setNotification({
            type: 'error',
            title: 'File Too Large',
            message: errorMsg,
            videoFilename: file.name
          });
          // Auto-dismiss after 10 seconds
          setTimeout(() => setNotification(null), 10000);
        } else if (err.response?.status === 402 || err.response?.status === 403) {
          // Payment required or forbidden - token-related errors
          if (errorMsg.includes('token') || errorMsg.includes('Insufficient')) {
            errorMsg = `${errorMsg}`;
          } else if (errorMsg.includes('CSRF')) {
            errorMsg = 'CSRF token error. Please refresh the page and try again.';
          }
        } else if (err.response?.status === 401) {
          errorMsg = 'Session expired. Please refresh the page.';
        } else if (!err.response && !isTimeout && !isNetworkError) {
          // Generic network error (not already handled)
          const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
          errorMsg = `Upload failed: "${file.name}" (${fileSizeMB} MB). Please check your connection and try again.`;
          
          setNotification({
            type: 'error',
            title: 'Upload Failed',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 10000);
        }
        
        // Only show message if we haven't shown a notification
        if (!isTimeout && !isNetworkError && !isFileSizeError && err.response?.status !== 401) {
          setMessage(`❌ ${errorMsg}`);
        } else if (!isTimeout && !isNetworkError && !isFileSizeError) {
          setMessage(`❌ ${errorMsg}`);
        }
        
        console.error('Error adding video:', {
          error: err,
          code: err.code,
          message: err.message,
          response: err.response?.status,
          fileSize: file.size,
          fileName: file.name
        });
      }
  };

  const removeVideo = async (id) => {
    await axios.delete(`${API}/videos/${id}`);
    setVideos(videos.filter(v => v.id !== id));
  };

  const clearAllVideos = async () => {
    // Filter out videos that are currently uploading
    const nonUploadingVideos = videos.filter(v => v.status !== 'uploading');
    
    if (nonUploadingVideos.length === 0) {
      setMessage('No videos to clear (all videos are currently uploading)');
      return;
    }
    
    // Show confirmation dialog
    setConfirmDialog({
      title: 'Clear All Videos',
      message: `Are you sure you want to clear all ${nonUploadingVideos.length} video(s) from the queue? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          const res = await axios.delete(`${API}/videos`);
          setVideos(videos.filter(v => v.status === 'uploading')); // Keep only uploading videos
          setMessage(`✅ Cleared ${res.data.deleted} video(s) from queue`);
        } catch (err) {
          const errorMsg = err.response?.data?.detail || err.message || 'Error clearing videos';
          setMessage(`❌ ${errorMsg}`);
          console.error('Error clearing videos:', err);
        }
      },
      onCancel: () => {
        setConfirmDialog(null);
      }
    });
  };

  const cancelScheduled = async () => {
    try {
      const res = await axios.post(`${API}/videos/cancel-scheduled`);
      setMessage(`✅ Cancelled ${res.data.cancelled} scheduled videos`);
      await loadVideos();
    } catch (err) {
      setMessage('❌ Error cancelling scheduled videos');
      console.error('Error cancelling scheduled videos:', err);
    }
  };

  const closeEditModal = () => {
    setEditingVideo(null);
    setEditTitleLength(0);
  };

  const updateVideoSettings = async (videoId, settings) => {
    try {
      const params = new URLSearchParams();
      Object.entries(settings).forEach(([key, value]) => {
        // Include empty strings (for clearing values like scheduled_time)
        if (value !== null && value !== undefined) {
          params.append(key, value);
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}?${params.toString()}`);
      
      // Reload videos to get updated computed titles
      await loadVideos();
      
      setMessage('✅ Video settings updated');
      closeEditModal();
    } catch (err) {
      setMessage('❌ Error updating video');
      console.error('Error updating video:', err);
    }
  };

  const recomputeVideoTitle = async (videoId) => {
    try {
      await axios.post(`${API}/videos/${videoId}/recompute-title`);
      
      // Reload videos to get updated title
      await loadVideos();
      
      setMessage('✅ Title recomputed from template');
      
      // Update the edit modal title field if it's open
      const titleInput = document.getElementById('edit-title');
      if (titleInput) {
        // Get the updated video data
        const videosRes = await axios.get(`${API}/videos`);
        const updatedVideo = videosRes.data.find(v => v.id === videoId);
        if (updatedVideo) {
          titleInput.value = updatedVideo.youtube_title || '';
          setEditTitleLength(titleInput.value.length);
        }
      }
    } catch (err) {
      setMessage('❌ Error recomputing title');
      console.error('Error recomputing title:', err);
    }
  };

  const handleDragStart = (e, video) => {
    // Only allow dragging if not uploading
    if (video.status === 'uploading') {
      e.preventDefault();
      return;
    }
    setDraggedVideo(video);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(video.id));
  };

  const handleDragEnd = (e) => {
    setDraggedVideo(null);
    // Remove any visual artifacts
    e.currentTarget.style.opacity = '1';
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDrop = async (e, targetVideo) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!draggedVideo || draggedVideo.id === targetVideo.id) {
      setDraggedVideo(null);
      return;
    }

    // Store original videos in case we need to revert
    const originalVideos = [...videos];
    
    const newVideos = [...videos];
    const draggedIdx = newVideos.findIndex(v => v.id === draggedVideo.id);
    const targetIdx = newVideos.findIndex(v => v.id === targetVideo.id);
    
    if (draggedIdx === -1 || targetIdx === -1) {
      setDraggedVideo(null);
      return;
    }
    
    // Remove dragged item from its current position
    const [draggedItem] = newVideos.splice(draggedIdx, 1);
    
    // Calculate correct insertion index after removal
    // If dragging down (original draggedIdx < targetIdx), 
    // the target has shifted up by 1, so we insert at targetIdx - 1
    // If dragging up (original draggedIdx > targetIdx),
    // the target hasn't shifted, so we insert at targetIdx
    const insertIdx = draggedIdx < targetIdx ? targetIdx - 1 : targetIdx;
    
    // Insert at new position  
    newVideos.splice(insertIdx, 0, draggedItem);
    
    // Clear dragged state immediately
    setDraggedVideo(null);
    
    // Update state optimistically for instant visual feedback
    setVideos(newVideos);
    
    // Save to backend
    try {
      const videoIds = newVideos.map(v => v.id);
      await axios.post(`${API}/videos/reorder`, { video_ids: videoIds });
    } catch (err) {
      console.error('Error reordering videos:', err);
      setMessage('❌ Error reordering videos');
      // Revert to original order on error
      setVideos(originalVideos);
    }
  };

  const upload = async () => {
    if (!youtube.enabled && !tiktok.enabled && !instagram.enabled) {
      setMessage('❌ Enable at least one destination first');
      return;
    }
    
    // Check token balance before uploading (only if not unlimited)
    if (tokenBalance && !tokenBalance.unlimited) {
      // Get pending videos (pending, failed, or uploading status)
      const pendingVideos = videos.filter(v => 
        v.status === 'pending' || v.status === 'failed' || v.status === 'uploading'
      );
      
      // Calculate total tokens required for all pending videos
      // Only count videos that haven't consumed tokens yet (tokens_consumed === 0)
      const totalTokensRequired = pendingVideos
        .filter(v => v.tokens_consumed === 0)
        .reduce((sum, video) => {
          const tokensForVideo = calculateTokens(video.file_size_bytes);
          return sum + tokensForVideo;
        }, 0);
      
      // Check if user has enough tokens
      if (totalTokensRequired > 0 && tokenBalance.tokens_remaining < totalTokensRequired) {
        const shortfall = totalTokensRequired - tokenBalance.tokens_remaining;
        setNotification({
          type: 'error',
          title: 'Insufficient Tokens',
          message: `You need ${totalTokensRequired} tokens to upload ${pendingVideos.length} video${pendingVideos.length === 1 ? '' : 's'}, but you only have ${tokenBalance.tokens_remaining} tokens remaining. You need ${shortfall} more token${shortfall === 1 ? '' : 's'}. Please upgrade your plan or wait for your token balance to reset.`,
        });
        // Auto-dismiss after 10 seconds
        setTimeout(() => setNotification(null), 10000);
        return;
      }
    }
    
    setIsUploading(true);
    const isScheduling = !globalSettings.upload_immediately;
    setMessage(isScheduling ? '⏳ Scheduling videos...' : '⏳ Uploading...');
    
    // Only poll for progress if uploading immediately
    let pollInterval;
    if (!isScheduling) {
      pollInterval = setInterval(async () => {
        try {
          const res = await axios.get(`${API}/videos`);
          setVideos(res.data);
        } catch (err) {
          console.error('Error polling videos:', err);
        }
      }, 1000);
    }
    
    try {
      const res = await axios.post(`${API}/upload`);
      if (pollInterval) clearInterval(pollInterval);
      
      if (res.data.uploaded !== undefined) {
        setMessage(`✅ Uploaded ${res.data.uploaded} videos!`);
      } else if (res.data.scheduled !== undefined) {
        setMessage(`✅ ${res.data.scheduled} videos scheduled! ${res.data.message}`);
      } else {
        setMessage(`✅ ${res.data.message || 'Success'}`);
      }
      
      // Final refresh
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } catch (err) {
      if (pollInterval) clearInterval(pollInterval);
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Unknown error';
      console.error('Upload error:', err);
      
      // Check if error is token-related and show popup
      if (errorMsg.toLowerCase().includes('insufficient') || errorMsg.toLowerCase().includes('token')) {
        setNotification({
          type: 'error',
          title: 'Insufficient Tokens',
          message: errorMsg,
        });
        setTimeout(() => setNotification(null), 10000);
      } else {
        setMessage(`❌ Upload failed: ${errorMsg}`);
      }
      
      // Refresh to get real status
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="app">
      {/* Notification Popup */}
      {notification && (
        <div
          style={{
            position: 'fixed',
            top: '20px',
            right: '20px',
            zIndex: 10000,
            minWidth: '350px',
            maxWidth: '500px',
            padding: '1.25rem',
            background: notification.type === 'error' 
              ? 'linear-gradient(135deg, rgba(239, 68, 68, 0.95) 0%, rgba(220, 38, 38, 0.95) 100%)'
              : 'linear-gradient(135deg, rgba(34, 197, 94, 0.95) 0%, rgba(22, 163, 74, 0.95) 100%)',
            border: notification.type === 'error'
              ? '2px solid rgba(239, 68, 68, 1)'
              : '2px solid rgba(34, 197, 94, 1)',
            borderRadius: '12px',
            boxShadow: '0 10px 40px rgba(0, 0, 0, 0.3)',
            color: 'white',
            animation: 'slideInRight 0.3s ease-out',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
            <div style={{ display: 'flex', gap: '0.75rem', flex: 1 }}>
              <span style={{ fontSize: '1.5rem', flexShrink: 0 }}>
                {notification.type === 'error' ? '⚠️' : '✅'}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '1.1rem', fontWeight: '700', marginBottom: '0.5rem' }}>
                  {notification.title}
                </div>
                <div style={{ fontSize: '0.95rem', lineHeight: '1.5', opacity: 0.95 }}>
                  {notification.message}
                </div>
                {notification.videoFilename && (
                  <div style={{ fontSize: '0.85rem', marginTop: '0.5rem', opacity: 0.85, fontStyle: 'italic' }}>
                    Video: {notification.videoFilename}
                  </div>
                )}
              </div>
            </div>
            <button
              onClick={() => setNotification(null)}
              style={{
                background: 'rgba(255, 255, 255, 0.2)',
                border: '1px solid rgba(255, 255, 255, 0.3)',
                borderRadius: '6px',
                color: 'white',
                cursor: 'pointer',
                padding: '0.25rem 0.5rem',
                fontSize: '1.2rem',
                lineHeight: '1',
                transition: 'all 0.2s',
                flexShrink: 0
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(255, 255, 255, 0.3)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(255, 255, 255, 0.2)';
              }}
            >
              ×
            </button>
          </div>
          {notification.type === 'error' && notification.title === 'Insufficient Tokens' && (
            <button
              onClick={() => {
                setNotification(null);
                setShowAccountSettings(true);
              }}
              style={{
                marginTop: '0.5rem',
                padding: '0.75rem 1rem',
                background: 'rgba(255, 255, 255, 0.2)',
                border: '1px solid rgba(255, 255, 255, 0.4)',
                borderRadius: '8px',
                color: 'white',
                cursor: 'pointer',
                fontSize: '0.95rem',
                fontWeight: '600',
                transition: 'all 0.2s',
                width: '100%'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(255, 255, 255, 0.3)';
                e.target.style.borderColor = 'rgba(255, 255, 255, 0.6)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(255, 255, 255, 0.2)';
                e.target.style.borderColor = 'rgba(255, 255, 255, 0.4)';
              }}
            >
              🪙 View Subscription & Tokens
            </button>
          )}
        </div>
      )}

      {/* Confirmation Dialog */}
      {confirmDialog && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10001,
            animation: 'fadeIn 0.2s ease-out'
          }}
          onClick={(e) => {
            // Close dialog when clicking backdrop
            if (e.target === e.currentTarget) {
              confirmDialog.onCancel();
            }
          }}
        >
          <div
            style={{
              background: 'linear-gradient(135deg, rgba(30, 30, 30, 0.98) 0%, rgba(20, 20, 20, 0.98) 100%)',
              border: '2px solid rgba(239, 68, 68, 0.5)',
              borderRadius: '16px',
              padding: '2rem',
              minWidth: '400px',
              maxWidth: '500px',
              boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
              color: 'white',
              animation: 'scaleIn 0.2s ease-out',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.5rem'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1rem' }}>
              <span style={{ fontSize: '2rem', flexShrink: 0 }}>⚠️</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '1.3rem', fontWeight: '700', marginBottom: '0.75rem' }}>
                  {confirmDialog.title}
                </div>
                <div style={{ fontSize: '1rem', lineHeight: '1.6', opacity: 0.9 }}>
                  {confirmDialog.message}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button
                onClick={confirmDialog.onCancel}
                style={{
                  padding: '0.75rem 1.5rem',
                  background: 'rgba(156, 163, 175, 0.2)',
                  border: '1px solid rgba(156, 163, 175, 0.4)',
                  borderRadius: '8px',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '1rem',
                  fontWeight: '600',
                  transition: 'all 0.2s'
                }}
                onMouseEnter={(e) => {
                  e.target.style.background = 'rgba(156, 163, 175, 0.3)';
                  e.target.style.borderColor = 'rgba(156, 163, 175, 0.6)';
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = 'rgba(156, 163, 175, 0.2)';
                  e.target.style.borderColor = 'rgba(156, 163, 175, 0.4)';
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDialog.onConfirm}
                style={{
                  padding: '0.75rem 1.5rem',
                  background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.9) 0%, rgba(220, 38, 38, 0.9) 100%)',
                  border: '1px solid rgba(239, 68, 68, 1)',
                  borderRadius: '8px',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '1rem',
                  fontWeight: '600',
                  transition: 'all 0.2s',
                  boxShadow: '0 4px 12px rgba(239, 68, 68, 0.3)'
                }}
                onMouseEnter={(e) => {
                  e.target.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 1) 0%, rgba(220, 38, 38, 1) 100%)';
                  e.target.style.transform = 'translateY(-1px)';
                  e.target.style.boxShadow = '0 6px 16px rgba(239, 68, 68, 0.4)';
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 0.9) 0%, rgba(220, 38, 38, 0.9) 100%)';
                  e.target.style.transform = 'translateY(0)';
                  e.target.style.boxShadow = '0 4px 12px rgba(239, 68, 68, 0.3)';
                }}
              >
                Clear All
              </button>
            </div>
          </div>
        </div>
      )}
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1>{appTitle}</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Token Balance Indicator */}
          {tokenBalance && (
            <div 
              style={{
                padding: '0.5rem 1rem',
                background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%)',
                border: '1px solid rgba(99, 102, 241, 0.3)',
                borderRadius: '20px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
              onClick={() => setShowAccountSettings(true)}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'linear-gradient(135deg, rgba(99, 102, 241, 0.25) 0%, rgba(168, 85, 247, 0.25) 100%)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
              title="Click to manage subscription"
            >
              <span style={{ fontSize: '1rem' }}>🪙</span>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                <span style={{ 
                  fontSize: '0.7rem', 
                  color: '#999', 
                  lineHeight: '1',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px'
                }}>
                  Tokens
                </span>
                <span style={{ 
                  fontSize: '1.1rem', 
                  fontWeight: '700', 
                  color: '#818cf8',
                  lineHeight: '1.2'
                }}>
                  {tokenBalance.unlimited ? '∞' : tokenBalance.tokens_remaining}
                </span>
              </div>
            </div>
          )}
          
          <span style={{ color: '#999', fontSize: '0.9rem' }}>
            {user.email}
          </span>
          <button 
            onClick={() => setShowAccountSettings(true)}
            style={{
              padding: '0.5rem',
              background: 'transparent',
              border: '1px solid #ddd',
              borderRadius: '4px',
              color: '#666',
              cursor: 'pointer',
              fontSize: '1.1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => {
              e.target.style.background = '#f5f5f5';
              e.target.style.borderColor = '#0066cc';
              e.target.style.color = '#0066cc';
            }}
            onMouseLeave={(e) => {
              e.target.style.background = 'transparent';
              e.target.style.borderColor = '#ddd';
              e.target.style.color = '#666';
            }}
            title="Account Settings"
          >
            ⚙️
          </button>
        </div>
      </div>
      
      {/* Global Settings */}
      <div className="card">
        <div className="card-header" onClick={() => setShowGlobalSettings(!showGlobalSettings)}>
          <h2>⚙️ Global Settings</h2>
          <button className="settings-toggle">{showGlobalSettings ? '−' : '+'}</button>
        </div>
        {showGlobalSettings && (
          <div className="settings-panel">
            <div className="setting-group">
              <label>
                Video Title Template <span className="char-counter">{globalSettings.title_template.length}/100</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
                </span>
              </label>
              <input 
                type="text"
                value={globalSettings.title_template}
                onChange={(e) => setGlobalSettings({...globalSettings, title_template: e.target.value})}
                onBlur={(e) => updateGlobalSettings('title_template', e.target.value)}
                placeholder="{filename}"
                className="input-text"
                maxLength="100"
              />
            </div>

            <div className="setting-group">
              <label>
                Video Description Template
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
                </span>
              </label>
              <textarea 
                value={globalSettings.description_template}
                onChange={(e) => setGlobalSettings({...globalSettings, description_template: e.target.value})}
                onBlur={(e) => updateGlobalSettings('description_template', e.target.value)}
                placeholder="Uploaded via hopper"
                className="textarea-text"
                rows="3"
              />
            </div>

            <div className="setting-divider"></div>

            <div className="setting-group">
              <div className="wordbank-label">
                <div className="wordbank-title">
                  <span>
                    Random Wordbank ({globalSettings.wordbank.length} words)
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">Words to use with {'{random}'} placeholder. Enter comma-separated words to add multiple at once</span>
                    </span>
                  </span>
                  {globalSettings.wordbank.length > 0 && (
                    <span 
                      className={`wordbank-caret ${wordbankExpanded ? 'expanded' : ''}`}
                      onClick={() => setWordbankExpanded(!wordbankExpanded)}
                      title={wordbankExpanded ? 'Hide words' : 'Show words'}
                    >
                      ▼
                    </span>
                  )}
                </div>
                {globalSettings.wordbank.length > 0 && (
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      clearWordbank();
                    }}
                    className="btn-clear-wordbank"
                    title="Clear all words"
                  >
                    Clear All
                  </button>
                )}
              </div>
              <div className="wordbank-input">
                <input 
                  type="text"
                  value={newWord}
                  onChange={(e) => setNewWord(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && newWord.trim() && addWordToWordbank(newWord.trim())}
                  placeholder="Add word(s) - comma-separated for multiple"
                  className="input-text"
                />
                <button 
                  onClick={() => newWord.trim() && addWordToWordbank(newWord.trim())}
                  className="btn-add-word"
                  disabled={!newWord.trim()}
                >
                  Add
                </button>
              </div>
              
              {globalSettings.wordbank.length > 0 && wordbankExpanded && (
                <div className="wordbank-list">
                  {globalSettings.wordbank.map((word, idx) => (
                    <div key={idx} className="wordbank-item">
                      <span>{word}</span>
                      <button onClick={() => removeWordFromWordbank(word)} className="btn-remove-word">×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="setting-divider"></div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={globalSettings.upload_immediately}
                  onChange={(e) => updateGlobalSettings('upload_immediately', e.target.checked)}
                  className="checkbox"
                />
                <span>
                  Upload Immediately
                  <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">If disabled, videos will be scheduled</span>
                  </span>
                </span>
              </label>
            </div>

            {!globalSettings.upload_immediately && (
              <>
                <div className="setting-group">
                  <label>Schedule Mode</label>
                  <select 
                    value={globalSettings.schedule_mode}
                    onChange={(e) => updateGlobalSettings('schedule_mode', e.target.value)}
                    className="select"
                  >
                    <option value="spaced">Spaced Interval</option>
                    <option value="specific_time">Specific Time</option>
                  </select>
                </div>

                {globalSettings.schedule_mode === 'spaced' ? (
                  <div className="setting-group">
                    <label>
                      Upload Interval
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">Videos upload one at a time with this interval</span>
                      </span>
                    </label>
                    <div className="interval-input">
                      <input 
                        type="number"
                        min="1"
                        value={globalSettings.schedule_interval_value}
                        onChange={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          setGlobalSettings({...globalSettings, schedule_interval_value: val});
                        }}
                        onBlur={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          updateGlobalSettings('schedule_interval_value', val);
                        }}
                        className="input-number"
                      />
                      <select 
                        value={globalSettings.schedule_interval_unit}
                        onChange={(e) => updateGlobalSettings('schedule_interval_unit', e.target.value)}
                        className="select-unit"
                      >
                        <option value="minutes">Minutes</option>
                        <option value="hours">Hours</option>
                        <option value="days">Days</option>
                      </select>
                    </div>
                  </div>
                ) : (
                  <div className="setting-group">
                    <label>
                      Start Time
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">All videos will upload at this time</span>
                      </span>
                    </label>
                    <input 
                      type="datetime-local"
                      value={globalSettings.schedule_start_time}
                      onChange={(e) => updateGlobalSettings('schedule_start_time', e.target.value)}
                      className="input"
                    />
                  </div>
                )}

                {globalSettings.schedule_mode === 'spaced' && (
                  <div className="setting-group">
                    <label>
                      <input
                        type="checkbox"
                        checked={globalSettings.upload_first_immediately !== false}
                        onChange={(e) => updateGlobalSettings('upload_first_immediately', e.target.checked)}
                        style={{ marginRight: '8px' }}
                      />
                      Upload first video immediately
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">
                          When checked, the first video uploads immediately and subsequent videos are spaced by the interval.
                          When unchecked, all videos (including the first) are spaced evenly by the interval.
                        </span>
                      </span>
                    </label>
                  </div>
                )}
              </>
            )}

            <div className="setting-divider"></div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={globalSettings.allow_duplicates}
                  onChange={(e) => updateGlobalSettings('allow_duplicates', e.target.checked)}
                  className="checkbox"
                />
                <span>
                  Allow Duplicate Videos
                  <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Allow uploading videos with the same filename</span>
                  </span>
                </span>
              </label>
            </div>

          </div>
        )}
      </div>
      
      {/* Destinations */}
      <div className="card">
        <h2>Destinations</h2>
        <div className="destination">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill="#FF0000"/>
              </svg>
              YouTube
            </span>
            <div style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: youtube.connected 
                ? (youtube.token_expired ? '#ef4444' : (youtube.token_expires_soon ? '#f59e0b' : '#22c55e'))
                : '#ef4444',
              flexShrink: 0
            }}></div>
            {youtube.connected && (
              <span className="account-info" style={{ fontSize: '0.9em', color: '#999', marginLeft: '4px' }}>
                {youtube.account ? (
                  youtube.account.channel_name ? 
                    youtube.account.channel_name + (youtube.account.email ? ` (${youtube.account.email})` : '') : 
                    youtube.account.email || 'Unknown account'
                ) : (
                  'Loading account...'
                )}
              </span>
            )}
            {youtube.connected && youtube.token_expired && (
              <span style={{ fontSize: '0.85em', color: '#ef4444', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {youtube.connected && !youtube.token_expired && youtube.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: '#f59e0b', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expires soon
              </span>
            )}
          </div>
          {youtube.connected ? (
            <>
              <label className="toggle">
                <input 
                  type="checkbox" 
                  checked={youtube.enabled}
                  onChange={toggleYoutube}
                />
                <span className="slider"></span>
              </label>
              <button onClick={() => setShowSettings(!showSettings)} className="btn-settings">
                ⚙️
              </button>
            </>
          ) : (
            <button onClick={connectYoutube}>Connect</button>
          )}
        </div>

        {/* YouTube Settings */}
        {showSettings && youtube.connected && (
          <div className="settings-panel">
            <h3>YouTube Settings</h3>
            
            <div className="setting-group">
              <label>Default Visibility</label>
              <select 
                value={youtubeSettings.visibility}
                onChange={(e) => updateYoutubeSettings('visibility', e.target.value)}
                className="select"
              >
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={youtubeSettings.made_for_kids}
                  onChange={(e) => updateYoutubeSettings('made_for_kids', e.target.checked)}
                  className="checkbox"
                />
                <span>Made for Kids</span>
              </label>
            </div>

            <div className="setting-group">
              <label>
                YouTube Title Template (Override) <span className="char-counter">{youtubeSettings.title_template?.length || 0}/100</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global title template for YouTube only. Leave empty to use global</span>
                </span>
              </label>
              <input 
                type="text"
                value={youtubeSettings.title_template || ''}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, title_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('title_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="input-text"
                maxLength="100"
              />
            </div>

            <div className="setting-group">
              <label>
                YouTube Description Template (Override)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global description template for YouTube only. Leave empty to use global</span>
                </span>
              </label>
              <textarea 
                value={youtubeSettings.description_template || ''}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, description_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('description_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="textarea-text"
                rows="3"
              />
            </div>

            <div className="setting-group">
              <label>
                Video Tags Template
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Comma-separated tags. Use {'{filename}'} or {'{random}'}</span>
                </span>
              </label>
              <input 
                type="text"
                value={youtubeSettings.tags_template}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, tags_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('tags_template', e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="input-text"
              />
            </div>

            <div className="setting-divider"></div>
            
            <div className="setting-group">
              <button onClick={disconnectYoutube} className="btn-logout" style={{
                width: '100%',
                padding: '0.75rem',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                color: '#ef4444',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
              }}>
                Log Out
              </button>
            </div>
          </div>
        )}

        {/* TikTok Destination */}
        <div className="destination">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" fill="#FFFFFF"/>
              </svg>
              TikTok
            </span>
            <div style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: tiktok.connected 
                ? (tiktok.token_expired ? '#ef4444' : (tiktok.token_expires_soon ? '#f59e0b' : '#22c55e'))
                : '#ef4444',
              flexShrink: 0
            }}></div>
            {tiktok.connected && (
              <span className="account-info" style={{ fontSize: '0.9em', color: '#999', marginLeft: '4px' }}>
                {tiktok.account ? (
                  tiktok.account.display_name ? 
                    tiktok.account.display_name + (tiktok.account.username ? ` (@${tiktok.account.username})` : '') : 
                    tiktok.account.username ? `@${tiktok.account.username}` : 'Unknown account'
                ) : (
                  'Loading account...'
                )}
              </span>
            )}
            {tiktok.connected && tiktok.token_expired && (
              <span style={{ fontSize: '0.85em', color: '#ef4444', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {tiktok.connected && !tiktok.token_expired && tiktok.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: '#f59e0b', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expires soon
              </span>
            )}
          </div>
          {tiktok.connected ? (
            <>
              <label className="toggle">
                <input 
                  type="checkbox" 
                  checked={tiktok.enabled}
                  onChange={toggleTiktok}
                />
                <span className="slider"></span>
              </label>
              <button onClick={() => setShowTiktokSettings(!showTiktokSettings)} className="btn-settings">
                ⚙️
              </button>
            </>
          ) : (
            <button onClick={connectTiktok}>Connect</button>
          )}
        </div>

        {/* TikTok Settings */}
        {showTiktokSettings && tiktok.connected && (
          <div className="settings-panel">
            <h3>TikTok Settings</h3>
            
            <div className="setting-group">
              <label>Privacy Level</label>
              <select 
                value={tiktokSettings.privacy_level}
                onChange={(e) => updateTiktokSettings('privacy_level', e.target.value)}
                className="select"
              >
                <option value="private">Private</option>
                <option value="friends">Friends</option>
                <option value="public">Public</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_comments}
                  onChange={(e) => updateTiktokSettings('allow_comments', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Comments</span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_duet}
                  onChange={(e) => updateTiktokSettings('allow_duet', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Duet</span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_stitch}
                  onChange={(e) => updateTiktokSettings('allow_stitch', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Stitch</span>
              </label>
            </div>

            <div className="setting-group">
              <label>
                TikTok Title Template (Caption) (Override) <span className="char-counter">{tiktokSettings.title_template?.length || 0}/2200</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global title template for TikTok only. This is the video caption (max 2200 characters). Leave empty to use global</span>
                </span>
              </label>
              <input 
                type="text"
                value={tiktokSettings.title_template || ''}
                onChange={(e) => setTiktokSettings({...tiktokSettings, title_template: e.target.value})}
                onBlur={(e) => updateTiktokSettings('title_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="input-text"
                maxLength="2200"
              />
            </div>

            <div className="setting-group">
              <label>
                TikTok Description Template (Override)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">TikTok only uses the caption (title) field. Description is not supported by TikTok API.</span>
                </span>
              </label>
              <textarea 
                value={tiktokSettings.description_template || ''}
                onChange={(e) => setTiktokSettings({...tiktokSettings, description_template: e.target.value})}
                onBlur={(e) => updateTiktokSettings('description_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="textarea-text"
                rows="3"
                disabled
              />
            </div>
            
            <div className="setting-divider"></div>
            
            <div className="setting-group">
              <button onClick={disconnectTiktok} className="btn-logout" style={{
                width: '100%',
                padding: '0.75rem',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                color: '#ef4444',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
              }}>
                Log Out
              </button>
            </div>
          </div>
        )}

        {/* Instagram Destination */}
        <div className="destination">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" fill="#E4405F"/>
              </svg>
              Instagram
            </span>
            <div style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: instagram.connected 
                ? (instagram.token_expired ? '#ef4444' : (instagram.token_expires_soon ? '#f59e0b' : '#22c55e'))
                : '#ef4444',
              flexShrink: 0
            }}></div>
            {instagram.connected && (
              <span className="account-info" style={{ fontSize: '0.9em', color: '#999', marginLeft: '4px' }}>
                {instagram.account ? (
                  instagram.account.username ? 
                    `@${instagram.account.username}` : 
                    instagram.account.user_id ? 
                      `Account (${instagram.account.user_id})` : 'Unknown account'
                ) : (
                  'Loading account...'
                )}
              </span>
            )}
            {instagram.connected && instagram.token_expired && (
              <span style={{ fontSize: '0.85em', color: '#ef4444', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {instagram.connected && !instagram.token_expired && instagram.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: '#f59e0b', marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expires soon
              </span>
            )}
          </div>
          {instagram.connected ? (
            <>
              <label className="toggle">
                <input 
                  type="checkbox" 
                  checked={instagram.enabled}
                  onChange={toggleInstagram}
                />
                <span className="slider"></span>
              </label>
              <button onClick={() => setShowInstagramSettings(!showInstagramSettings)} className="btn-settings">
                ⚙️
              </button>
            </>
          ) : (
            <button onClick={connectInstagram}>Connect</button>
          )}
        </div>

        {/* Instagram Settings */}
        {showInstagramSettings && instagram.connected && (
          <div className="settings-panel">
            <h3>Instagram Settings</h3>
            
            <div className="setting-group">
              <label>
                Caption Template (Override) <span className="char-counter">{instagramSettings.caption_template?.length || 0}/2200</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global title template for Instagram only. This is the video caption (max 2200 characters). Leave empty to use global</span>
                </span>
              </label>
              <input 
                type="text"
                value={instagramSettings.caption_template || ''}
                onChange={(e) => setInstagramSettings({...instagramSettings, caption_template: e.target.value})}
                onBlur={(e) => updateInstagramSettings('caption_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="input-text"
                maxLength="2200"
              />
            </div>

            <div className="setting-group">
              <label>
                Location ID
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Optional Instagram location ID for geotagging</span>
                </span>
              </label>
              <input 
                type="text"
                value={instagramSettings.location_id || ''}
                onChange={(e) => setInstagramSettings({...instagramSettings, location_id: e.target.value})}
                onBlur={(e) => updateInstagramSettings('location_id', e.target.value)}
                placeholder="Location ID (optional)"
                className="input-text"
              />
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={instagramSettings.disable_comments}
                  onChange={(e) => updateInstagramSettings('disable_comments', e.target.checked)}
                  className="checkbox"
                />
                <span>Disable Comments</span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={instagramSettings.disable_likes}
                  onChange={(e) => updateInstagramSettings('disable_likes', e.target.checked)}
                  className="checkbox"
                />
                <span>Disable Likes</span>
              </label>
            </div>
            
            <div className="setting-divider"></div>
            
            <div className="setting-group">
              <button onClick={disconnectInstagram} className="btn-logout" style={{
                width: '100%',
                padding: '0.75rem',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                color: '#ef4444',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
              }}>
                Log Out
              </button>
            </div>
          </div>
        )}
      </div>
      
      {/* Upload Button */}
      {videos.length > 0 && (youtube.enabled || tiktok.enabled || instagram.enabled) && (
        <>
          <button className="upload-btn" onClick={upload} disabled={isUploading}>
            {isUploading ? 'Uploading...' : 
             globalSettings.upload_immediately ? 'Upload' : 'Schedule Videos'}
          </button>
          
          {/* Cancel Scheduled Button */}
          {videos.some(v => v.status === 'scheduled') && (
            <button className="cancel-scheduled-btn" onClick={cancelScheduled}>
              Cancel Scheduled ({videos.filter(v => v.status === 'scheduled').length})
            </button>
          )}
        </>
      )}
      
      {/* Drop Zone */}
      <div 
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleFileDrop}
        onClick={() => document.getElementById('file').click()}
      >
        <p>Drop videos here</p>
        {maxFileSize && (
          <p style={{ fontSize: '0.85rem', color: '#999', marginTop: '0.5rem' }}>
            Maximum file size: {maxFileSize.max_file_size_display}
          </p>
        )}
        <input 
          id="file"
          type="file"
          multiple
          accept="video/*"
          onChange={(e) => Array.from(e.target.files).forEach(addVideo)}
          style={{display: 'none'}}
        />
      </div>
      
      {/* Queue */}
      {message && <div className="message">{message}</div>}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h2 style={{ margin: 0 }}>Queue ({videos.length})</h2>
          {videos.length > 0 && videos.some(v => v.status !== 'uploading') && (
            <button
              onClick={clearAllVideos}
              style={{
                padding: '0.5rem 1rem',
                background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.9) 0%, rgba(220, 38, 38, 0.9) 100%)',
                border: '1px solid rgba(239, 68, 68, 1)',
                borderRadius: '8px',
                color: 'white',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '600',
                transition: 'all 0.2s',
                boxShadow: '0 2px 8px rgba(239, 68, 68, 0.3)'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 1) 0%, rgba(220, 38, 38, 1) 100%)';
                e.target.style.transform = 'translateY(-1px)';
                e.target.style.boxShadow = '0 4px 12px rgba(239, 68, 68, 0.4)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 0.9) 0%, rgba(220, 38, 38, 0.9) 100%)';
                e.target.style.transform = 'translateY(0)';
                e.target.style.boxShadow = '0 2px 8px rgba(239, 68, 68, 0.3)';
              }}
            >
              Clear All
            </button>
          )}
        </div>
        {videos.length === 0 ? (
          <p className="empty">No videos</p>
        ) : (
          videos.map(v => {
            const isExpanded = expandedVideos.has(v.id);
            const uploadProps = v.upload_properties || {};
            const youtubeProps = uploadProps.youtube || {};
            
            return (
              <div 
                key={v.id} 
                className={`video ${draggedVideo?.id === v.id ? 'dragging' : ''}`}
                draggable={v.status !== 'uploading'}
                onDragStart={(e) => handleDragStart(e, v)}
                onDragEnd={handleDragEnd}
                onDragOver={handleDragOver}
                onDrop={(e) => handleDrop(e, v)}
              >
                <div className="drag-handle" title="Drag to reorder">⋮⋮</div>
                <div className="video-info-container" style={{ flex: 1 }}>
                  <div className="video-titles">
                    <div className="youtube-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8 5v14l11-7z" fill="currentColor"/>
                      </svg>
                      {v.youtube_title || v.filename}
                      {v.title_too_long && (
                        <span className="title-warning" title={`Title truncated from ${v.title_original_length} to 100 characters`}>
                          ⚠️ {v.title_original_length}
                        </span>
                      )}
                      {v.file_size_bytes && (
                        <>
                          <span 
                            style={{ 
                              marginLeft: '8px',
                              padding: '2px 8px',
                              background: 'rgba(156, 163, 175, 0.15)',
                              border: '1px solid rgba(156, 163, 175, 0.3)',
                              borderRadius: '12px',
                              fontSize: '0.75rem',
                              fontWeight: '500',
                              color: '#9ca3af',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px'
                            }}
                            title={`File size: ${formatFileSize(v.file_size_bytes)}`}
                          >
                            <span>📦</span>
                            <span>{formatFileSize(v.file_size_bytes)}</span>
                          </span>
                          <span 
                            style={{ 
                              marginLeft: '8px',
                              padding: '2px 8px',
                              background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%)',
                              border: '1px solid rgba(99, 102, 241, 0.3)',
                              borderRadius: '12px',
                              fontSize: '0.75rem',
                              fontWeight: '600',
                              color: '#818cf8',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px'
                            }}
                            title={`Tokens: ${v.tokens_consumed || calculateTokens(v.file_size_bytes)}`}
                          >
                            <span>🪙</span>
                            <span>{v.tokens_consumed || calculateTokens(v.file_size_bytes)}</span>
                          </span>
                        </>
                      )}
                    </div>
                    <div className="filename">File: {v.filename}</div>
                  </div>
                  <div className="status">
                    {v.status === 'uploading' ? (
                      v.upload_progress !== undefined ? (
                        <span>Uploading {v.upload_progress}%</span>
                      ) : v.progress !== undefined && v.progress < 100 ? (
                        <span>Uploading to server {v.progress}%</span>
                      ) : (
                        <span>Processing...</span>
                      )
                    ) : v.status === 'scheduled' && v.scheduled_time ? (
                      <span>Scheduled for {new Date(v.scheduled_time).toLocaleString(undefined, {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                      })}</span>
                    ) : (
                      <span>{v.status}</span>
                    )}
                  </div>
                  {v.status === 'uploading' && (
                    <div className="progress-bar">
                      <div 
                        className="progress-fill" 
                        style={{ 
                          width: `${v.upload_progress !== undefined ? v.upload_progress : (v.progress || 0)}%` 
                        }}
                      ></div>
                    </div>
                  )}
                  {isExpanded && (
                    <div style={{ 
                      marginTop: '1rem', 
                      padding: '1rem', 
                      background: 'rgba(0, 0, 0, 0.2)', 
                      borderRadius: '8px',
                      fontSize: '0.9rem'
                    }}>
                      <div style={{ fontWeight: 'bold', marginBottom: '0.5rem' }}>Upload Properties:</div>
                      {youtubeProps.title && (
                        <div style={{ marginBottom: '0.5rem' }}>
                          <strong>YouTube:</strong>
                          <div style={{ marginLeft: '1rem', marginTop: '0.25rem' }}>
                            <div>Title: {youtubeProps.title}</div>
                            <div>Visibility: {youtubeProps.visibility}</div>
                            <div>Made for Kids: {youtubeProps.made_for_kids ? 'Yes' : 'No'}</div>
                            {youtubeProps.description && <div>Description: {youtubeProps.description.substring(0, 100)}{youtubeProps.description.length > 100 ? '...' : ''}</div>}
                            {youtubeProps.tags && <div>Tags: {youtubeProps.tags}</div>}
                          </div>
                        </div>
                      )}
                      {uploadProps.tiktok && (
                        <div style={{ marginBottom: '0.5rem' }}>
                          <strong>TikTok:</strong>
                          <div style={{ marginLeft: '1rem', marginTop: '0.25rem' }}>
                            <div>Title: {uploadProps.tiktok.title}</div>
                            <div>Privacy: {uploadProps.tiktok.privacy_level}</div>
                            <div>Allow Comments: {uploadProps.tiktok.allow_comments ? 'Yes' : 'No'}</div>
                            <div>Allow Duet: {uploadProps.tiktok.allow_duet ? 'Yes' : 'No'}</div>
                            <div>Allow Stitch: {uploadProps.tiktok.allow_stitch ? 'Yes' : 'No'}</div>
                          </div>
                        </div>
                      )}
                      {uploadProps.instagram && (
                        <div style={{ marginBottom: '0.5rem' }}>
                          <strong>Instagram:</strong>
                          <div style={{ marginLeft: '1rem', marginTop: '0.25rem' }}>
                            <div>Caption: {uploadProps.instagram.caption}</div>
                            {uploadProps.instagram.location_id && <div>Location ID: {uploadProps.instagram.location_id}</div>}
                            <div>Disable Comments: {uploadProps.instagram.disable_comments ? 'Yes' : 'No'}</div>
                            <div>Disable Likes: {uploadProps.instagram.disable_likes ? 'Yes' : 'No'}</div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div className="video-actions">
                  {v.status !== 'uploading' && v.status !== 'uploaded' && (
                    <>
                      <button 
                        onClick={() => {
                          const newExpanded = new Set(expandedVideos);
                          if (isExpanded) {
                            newExpanded.delete(v.id);
                          } else {
                            newExpanded.add(v.id);
                          }
                          setExpandedVideos(newExpanded);
                        }}
                        className="btn-edit" 
                        title={isExpanded ? "Collapse properties" : "Expand properties"}
                        style={{ 
                          marginRight: '4px', 
                          fontSize: '1rem',
                          width: '24px',
                          height: '24px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: 0,
                          lineHeight: '1'
                        }}
                      >
                        <span style={{ display: 'inline-block', width: '12px', textAlign: 'center' }}>
                          {isExpanded ? '▼' : '▾'}
                        </span>
                      </button>
                      <button onClick={() => {
                        setEditingVideo(v);
                        setEditTitleLength((v.custom_settings?.title || v.youtube_title || '').length);
                      }} className="btn-edit" title="Edit video settings">
                        ✏️
                      </button>
                    </>
                  )}
                  <button onClick={() => removeVideo(v.id)} disabled={v.status === 'uploading'}>×</button>
                </div>
              </div>
            );
          })
        )}
      </div>
      
      {/* Edit Video Modal */}
      {editingVideo && (
        <div className="modal-overlay" onClick={closeEditModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit Video Settings</h2>
              <button onClick={closeEditModal} className="btn-close">×</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <label>
                    Video Title <span className="char-counter">{editTitleLength}/100</span>
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">Leave empty to use template. Click "Recompute" to regenerate from current template.</span>
                    </span>
                  </label>
                  <button 
                    type="button"
                    onClick={() => recomputeVideoTitle(editingVideo.id)}
                    className="btn-recompute-title"
                    style={{
                      padding: '0.4rem 0.8rem',
                      fontSize: '0.85rem',
                      background: 'rgba(139, 92, 246, 0.2)',
                      border: '1px solid rgba(139, 92, 246, 0.4)',
                      borderRadius: '4px',
                      color: '#8b5cf6',
                      cursor: 'pointer',
                      fontWeight: '500'
                    }}
                    title="Recompute title from current template"
                  >
                    🔄 Recompute
                  </button>
                </div>
                <input 
                  type="text"
                  defaultValue={editingVideo.custom_settings?.title || editingVideo.youtube_title}
                  id="edit-title"
                  className="input-text"
                  placeholder="Video title"
                  maxLength="100"
                  onInput={(e) => setEditTitleLength(e.target.value.length)}
                />
              </div>
              
              <div className="form-group">
                <label>
                  Description
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Leave empty to use global template</span>
                  </span>
                </label>
                <textarea 
                  defaultValue={editingVideo.custom_settings?.description || ''}
                  id="edit-description"
                  className="textarea-text"
                  rows="4"
                  placeholder="Video description"
                />
              </div>
              
              <div className="form-group">
                <label>
                  Tags
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Comma-separated tags. Leave empty to use global template</span>
                  </span>
                </label>
                <input 
                  type="text"
                  defaultValue={editingVideo.custom_settings?.tags || ''}
                  id="edit-tags"
                  className="input-text"
                  placeholder="tag1, tag2, tag3"
                />
              </div>
              
              <div className="form-group">
                <label>Visibility</label>
                <select 
                  defaultValue={editingVideo.custom_settings?.visibility || youtubeSettings.visibility}
                  id="edit-visibility"
                  className="select"
                >
                  <option value="private">Private</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
              </div>
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    defaultChecked={editingVideo.custom_settings?.made_for_kids ?? youtubeSettings.made_for_kids}
                    id="edit-made-for-kids"
                    className="checkbox"
                  />
                  <span>Made for Kids</span>
                </label>
              </div>

              <div className="form-group">
                <label>
                  Scheduled Time
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Leave empty for immediate upload (if enabled) or use global schedule</span>
                  </span>
                </label>
                <input 
                  type="datetime-local"
                  defaultValue={editingVideo.scheduled_time ? (() => {
                    const date = new Date(editingVideo.scheduled_time);
                    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
                    return localDate.toISOString().slice(0, 16);
                  })() : ''}
                  id="edit-scheduled-time"
                  className="input-text"
                />
              </div>
            </div>
            <div className="modal-footer">
              <button onClick={closeEditModal} className="btn-cancel">
                Cancel
              </button>
              <button 
                onClick={() => {
                  const title = document.getElementById('edit-title').value;
                  const description = document.getElementById('edit-description').value;
                  const tags = document.getElementById('edit-tags').value;
                  const visibility = document.getElementById('edit-visibility').value;
                  const madeForKids = document.getElementById('edit-made-for-kids').checked;
                  const scheduledTime = document.getElementById('edit-scheduled-time').value;
                  
                  updateVideoSettings(editingVideo.id, {
                    title: title || null,
                    description: description || null,
                    tags: tags || null,
                    visibility,
                    made_for_kids: madeForKids,
                    scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : ''
                  });
                }}
                className="btn-save"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Account Settings Modal */}
      {showAccountSettings && (
        <div className="modal-overlay" onClick={() => setShowAccountSettings(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <div className="modal-header">
              <h2>⚙️ Account Settings</h2>
              <button onClick={() => setShowAccountSettings(false)} className="btn-close">×</button>
            </div>
            
            <div className="modal-body">
              {/* Account Info */}
              <div className="form-group" style={{ 
                padding: '1rem', 
                background: 'rgba(255, 255, 255, 0.05)', 
                borderRadius: '8px',
                border: '1px solid rgba(255, 255, 255, 0.1)'
              }}>
                <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.25rem' }}>Logged in as</div>
                <div style={{ fontSize: '1rem', fontWeight: '500', color: 'white', marginBottom: '1rem' }}>{user.email}</div>
                <button 
                  onClick={handleLogout}
                  style={{
                    width: '100%',
                    padding: '0.75rem',
                    background: 'transparent',
                    border: '1px solid #666',
                    borderRadius: '6px',
                    color: '#999',
                    cursor: 'pointer',
                    fontSize: '1rem',
                    fontWeight: '500',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = 'rgba(255, 255, 255, 0.05)';
                    e.target.style.borderColor = '#999';
                    e.target.style.color = 'white';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = 'transparent';
                    e.target.style.borderColor = '#666';
                    e.target.style.color = '#999';
                  }}
                >
                  🚪 Logout
                </button>
              </div>

              {/* Subscription & Token Balance */}
              <div className="form-group" style={{ 
                padding: '1.5rem', 
                background: 'rgba(99, 102, 241, 0.1)', 
                borderRadius: '8px',
                border: '1px solid rgba(99, 102, 241, 0.3)'
              }}>
                <h3 style={{ color: '#818cf8', marginBottom: '1rem', fontSize: '1.1rem', marginTop: 0 }}>
                  💳 Subscription & Tokens
                </h3>
                
                {subscription && tokenBalance ? (
                  <>
                    {/* Current Plan */}
                    <div style={{ marginBottom: '1rem' }}>
                      <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.25rem' }}>Current Plan</div>
                      <div style={{ fontSize: '1.1rem', fontWeight: '600', color: 'white', textTransform: 'capitalize' }}>
                        {subscription.plan_type}
                        {subscription.status !== 'active' && (
                          <span style={{ 
                            fontSize: '0.75rem', 
                            marginLeft: '0.5rem', 
                            padding: '0.25rem 0.5rem',
                            background: 'rgba(239, 68, 68, 0.2)',
                            color: '#ef4444',
                            borderRadius: '4px',
                            textTransform: 'uppercase'
                          }}>
                            {subscription.status}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Token Balance */}
                    <div style={{ 
                      padding: '1rem', 
                      background: 'rgba(0, 0, 0, 0.2)', 
                      borderRadius: '6px',
                      marginBottom: '1rem'
                    }}>
                      <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.5rem' }}>Available Tokens</div>
                      <div style={{ fontSize: '2rem', fontWeight: '700', color: '#818cf8', marginBottom: '0.25rem' }}>
                        {tokenBalance.unlimited ? '∞' : tokenBalance.tokens_remaining}
                      </div>
                      {!tokenBalance.unlimited && (
                        <>
                          <div style={{ fontSize: '0.75rem', color: '#666' }}>
                            Used {tokenBalance.tokens_used_this_period} this period
                          </div>
                          {tokenBalance.period_end && (
                            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.25rem' }}>
                              Resets: {new Date(tokenBalance.period_end).toLocaleDateString()}
                            </div>
                          )}
                        </>
                      )}
                    </div>

                    {/* Available Plans */}
                    {availablePlans.length > 0 && (
                      <div style={{ marginBottom: '1rem' }}>
                        <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.75rem' }}>
                          Available Plans
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                          {availablePlans.map(plan => {
                            const isCurrent = subscription.plan_type === plan.key;
                            return (
                              <div 
                                key={plan.key}
                                style={{
                                  padding: '0.75rem',
                                  background: isCurrent ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                                  border: isCurrent ? '1px solid rgba(99, 102, 241, 0.5)' : '1px solid rgba(255, 255, 255, 0.1)',
                                  borderRadius: '6px',
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center'
                                }}
                              >
                                <div>
                                  <div style={{ 
                                    fontSize: '0.95rem', 
                                    fontWeight: '600', 
                                    color: 'white',
                                    textTransform: 'capitalize'
                                  }}>
                                    {plan.key}
                                  </div>
                                  <div style={{ fontSize: '0.75rem', color: '#999' }}>
                                    {plan.monthly_tokens} tokens/month
                                  </div>
                                </div>
                                {isCurrent && (
                                  <span style={{ 
                                    fontSize: '0.75rem', 
                                    padding: '0.25rem 0.5rem',
                                    background: 'rgba(34, 197, 94, 0.2)',
                                    color: '#22c55e',
                                    borderRadius: '4px',
                                    fontWeight: '600'
                                  }}>
                                    CURRENT
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Manage Subscription Button */}
                    <button 
                      onClick={handleManageSubscription}
                      disabled={loadingSubscription}
                      style={{
                        width: '100%',
                        padding: '0.75rem',
                        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: loadingSubscription ? 'not-allowed' : 'pointer',
                        fontSize: '0.95rem',
                        fontWeight: '600',
                        transition: 'all 0.2s',
                        opacity: loadingSubscription ? 0.6 : 1
                      }}
                      onMouseEnter={(e) => {
                        if (!loadingSubscription) {
                          e.target.style.transform = 'translateY(-2px)';
                          e.target.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.4)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        e.target.style.transform = 'translateY(0)';
                        e.target.style.boxShadow = 'none';
                      }}
                    >
                      {loadingSubscription ? '⏳ Loading...' : '⚙️ Manage Subscription'}
                    </button>
                  </>
                ) : (
                  <div style={{ textAlign: 'center', padding: '1rem', color: '#999' }}>
                    Loading subscription info...
                  </div>
                )}
              </div>

              {/* Danger Zone */}
              <div style={{ 
                marginTop: '1rem', 
                padding: '1.5rem', 
                background: 'rgba(239, 68, 68, 0.1)', 
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '8px' 
              }}>
                <h3 style={{ color: '#ef4444', marginBottom: '0.75rem', fontSize: '1.1rem', marginTop: 0 }}>
                  ⚠️ Danger Zone
                </h3>
                <p style={{ color: '#999', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: '1.5' }}>
                  Once you delete your account, there is no going back. This will permanently delete:
                </p>
                <ul style={{ color: '#999', marginBottom: '1rem', fontSize: '0.85rem', paddingLeft: '1.25rem', lineHeight: '1.6' }}>
                  <li>Your account and login credentials</li>
                  <li>All uploaded videos and files</li>
                  <li>All settings and preferences</li>
                  <li>All connected accounts (YouTube, TikTok, Instagram)</li>
                </ul>
                <button 
                  onClick={() => setShowDeleteConfirm(true)}
                  style={{
                    width: '100%',
                    padding: '0.75rem',
                    background: '#ef4444',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.95rem',
                    fontWeight: '600',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = '#dc2626';
                    e.target.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = '#ef4444';
                    e.target.style.transform = 'translateY(0)';
                  }}
                >
                  Delete My Account
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {showDeleteConfirm && (
        <div className="modal-overlay" onClick={() => setShowDeleteConfirm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '450px' }}>
            <div className="modal-header">
              <h2 style={{ color: '#ef4444' }}>⚠️ Delete Account</h2>
              <button onClick={() => setShowDeleteConfirm(false)} className="btn-close">×</button>
            </div>
            
            <div className="modal-body">
              <p style={{ marginBottom: '1rem', fontSize: '1rem', lineHeight: '1.6', color: 'white' }}>
                Are you absolutely sure you want to delete your account?
              </p>
              <p style={{ marginBottom: '1.5rem', fontSize: '0.9rem', color: '#999', lineHeight: '1.6' }}>
                This action <strong style={{ color: '#ef4444' }}>cannot be undone</strong>. All your data will be permanently deleted.
              </p>
              
              <div style={{ display: 'flex', gap: '0.75rem' }}>
                <button 
                  onClick={() => setShowDeleteConfirm(false)}
                  className="btn-cancel"
                  style={{ flex: 1 }}
                >
                  Cancel
                </button>
                <button 
                  onClick={handleDeleteAccount}
                  style={{
                    flex: 1,
                    padding: '0.75rem',
                    background: '#ef4444',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '1rem',
                    fontWeight: '600',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = '#dc2626';
                    e.target.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = '#ef4444';
                    e.target.style.transform = 'translateY(0)';
                  }}
                >
                  Yes, Delete Everything
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer style={{
        marginTop: '3rem',
        padding: '1.5rem',
        textAlign: 'center',
        borderTop: '1px solid #eee',
        color: '#666',
        fontSize: '0.9rem'
      }}>
        <Link 
          to="/terms" 
          style={{ 
            color: '#666', 
            textDecoration: 'none', 
            marginRight: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Terms of Service
        </Link>
        <span style={{ color: '#ccc' }}>|</span>
        <Link 
          to="/privacy" 
          style={{ 
            color: '#666', 
            textDecoration: 'none', 
            margin: '0 1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Privacy Policy
        </Link>
        <span style={{ color: '#ccc' }}>|</span>
        <Link 
          to="/delete-your-data"
          style={{ 
            color: '#666', 
            textDecoration: 'none', 
            marginLeft: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Delete Your Data
        </Link>
        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#999' }}>
          <a 
            href="https://github.com/the3venthoriz0n/hopper" 
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: '#999', 
              textDecoration: 'none',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = '#0066cc'}
            onMouseLeave={(e) => e.target.style.color = '#999'}
          >
            {process.env.REACT_APP_VERSION || 'dev'}
          </a>
        </div>
      </footer>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/admin" element={<AdminDashboard />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/delete-your-data" element={<DeleteYourData />} />
    </Routes>
  );
}

export default App;

