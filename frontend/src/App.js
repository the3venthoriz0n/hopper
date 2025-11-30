import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import './App.css';
import Terms from './Terms';
import Privacy from './Privacy';
import Login from './Login';

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
  const [authLoading, setAuthLoading] = useState(true);
  
  // Check if user is authenticated
  useEffect(() => {
    checkAuth();
  }, []);
  
  const checkAuth = async () => {
    try {
      const res = await axios.get(`${API}/auth/me`);
      if (res.data.user) {
        setUser(res.data.user);
      } else {
        setUser(null);
      }
    } catch (err) {
      console.error('Auth check failed:', err);
      setUser(null);
    } finally {
      setAuthLoading(false);
    }
  };
  
  const handleLogout = async () => {
    try {
      await axios.post(`${API}/auth/logout`);
      setUser(null);
      setMessage('✅ Logged out successfully');
    } catch (err) {
      console.error('Logout failed:', err);
      setMessage('❌ Logout failed');
    }
  };
  
  // Set document title based on environment
  useEffect(() => {
    document.title = isProduction ? 'hopper' : 'DEV HOPPER';
  }, [isProduction]);
  
  // Show login page if not authenticated
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
  
  const [youtube, setYoutube] = useState({ connected: false, enabled: false, account: null });
  const [tiktok, setTiktok] = useState({ connected: false, enabled: false, account: null });
  const [instagram, setInstagram] = useState({ connected: false, enabled: false, account: null });
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
  const [isUploading, setIsUploading] = useState(false);
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [newWord, setNewWord] = useState('');
  const [wordbankExpanded, setWordbankExpanded] = useState(false);

  // Tooltip positioning handler to keep tooltips on screen
  useEffect(() => {
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
  }, [videos, editingVideo, showSettings, showTiktokSettings, showGlobalSettings]);

  useEffect(() => {
    loadDestinations();
    loadGlobalSettings();
    loadYoutubeSettings();
    loadTiktokSettings();
    loadInstagramSettings();
    loadVideos();
    
    // Check OAuth callback
    if (window.location.search.includes('connected=youtube')) {
      setMessage('✅ YouTube connected!');
      loadDestinations();
      // Small delay to ensure account info is available
      setTimeout(() => {
        loadYoutubeAccount();
      }, 1000);
      window.history.replaceState({}, '', '/');
    } else if (window.location.search.includes('connected=tiktok')) {
      setMessage('✅ TikTok connected!');
      loadDestinations();
      // Small delay to ensure account info is available
      setTimeout(() => {
        loadTiktokAccount();
      }, 1000);
      window.history.replaceState({}, '', '/');
    } else if (window.location.search.includes('connected=instagram')) {
      setMessage('✅ Instagram connected!');
      loadDestinations();
      // Small delay to ensure account info is available
      setTimeout(() => {
        loadInstagramAccount();
      }, 1000);
      window.history.replaceState({}, '', '/');
    }
    
    // Poll for video updates every 5 seconds to catch scheduled uploads
    const pollInterval = setInterval(() => {
      loadVideos();
    }, 5000);
    
    return () => clearInterval(pollInterval);
  }, []);
  
  const loadVideos = async () => {
    try {
      const res = await axios.get(`${API}/videos`);
      // Only update if the data has actually changed to avoid unnecessary re-renders
      setVideos(prevVideos => {
        const newData = res.data;
        // Check if the data is different
        if (JSON.stringify(prevVideos) === JSON.stringify(newData)) {
          return prevVideos;
        }
        return newData;
      });
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  };

  const loadYoutubeAccount = async () => {
    try {
      const res = await axios.get(`${API}/auth/youtube/account`);
      if (res.data.error) {
        console.error('Error loading YouTube account:', res.data.error);
        setYoutube(prev => ({ ...prev, account: null }));
      } else {
        setYoutube(prev => ({ ...prev, account: res.data.account || null }));
      }
    } catch (error) {
      console.error('Error loading YouTube account:', error.response?.data || error.message);
      setYoutube(prev => ({ ...prev, account: null }));
    }
  };

  const loadTiktokAccount = async () => {
    try {
      const res = await axios.get(`${API}/auth/tiktok/account`);
      if (res.data.error) {
        console.error('Error loading TikTok account:', res.data.error);
        setTiktok(prev => ({ ...prev, account: null }));
      } else {
        setTiktok(prev => ({ ...prev, account: res.data.account || null }));
      }
    } catch (error) {
      console.error('Error loading TikTok account:', error.response?.data || error.message);
      setTiktok(prev => ({ ...prev, account: null }));
    }
  };

  const loadInstagramAccount = async () => {
    try {
      const res = await axios.get(`${API}/auth/instagram/account`);
      if (res.data.error) {
        console.error('Error loading Instagram account:', res.data.error);
        setInstagram(prev => ({ ...prev, account: null }));
      } else {
        setInstagram(prev => ({ ...prev, account: res.data.account || null }));
      }
    } catch (error) {
      console.error('Error loading Instagram account:', error.response?.data || error.message);
      setInstagram(prev => ({ ...prev, account: null }));
    }
  };

  const loadDestinations = async () => {
    try {
      const res = await axios.get(`${API}/destinations`);
      setYoutube({ 
        connected: res.data.youtube.connected, 
        enabled: res.data.youtube.enabled,
        account: null  // Will be loaded separately
      });
      setTiktok({ 
        connected: res.data.tiktok.connected, 
        enabled: res.data.tiktok.enabled,
        account: null  // Will be loaded separately
      });
      setInstagram({ 
        connected: res.data.instagram.connected, 
        enabled: res.data.instagram.enabled,
        account: null  // Will be loaded separately
      });
      
      // Load account info if connected
      if (res.data.youtube.connected) {
        loadYoutubeAccount();
      }
      if (res.data.tiktok.connected) {
        loadTiktokAccount();
      }
      if (res.data.instagram.connected) {
        loadInstagramAccount();
      }
    } catch (error) {
      console.error('Error loading destinations:', error);
    }
  };

  const loadGlobalSettings = async () => {
    try {
      const res = await axios.get(`${API}/global/settings`);
      setGlobalSettings(res.data);
    } catch (err) {
      console.error('Error loading global settings:', err);
    }
  };

  const updateGlobalSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/global/settings?${params.toString()}`);
      setGlobalSettings(res.data);
      setMessage(`✅ Settings updated`);
    } catch (err) {
      setMessage('❌ Error updating settings');
      console.error('Error updating settings:', err);
    }
  };

  const loadYoutubeSettings = async () => {
    try {
      const res = await axios.get(`${API}/youtube/settings`);
      setYoutubeSettings(res.data);
    } catch (err) {
      console.error('Error loading settings:', err);
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

  const loadTiktokSettings = async () => {
    try {
      const res = await axios.get(`${API}/tiktok/settings`);
      setTiktokSettings(res.data);
    } catch (err) {
      console.error('Error loading TikTok settings:', err);
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

  const loadInstagramSettings = async () => {
    try {
      const res = await axios.get(`${API}/instagram/settings`);
      setInstagramSettings(res.data);
    } catch (err) {
      console.error('Error loading Instagram settings:', err);
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

  const connectYoutube = async () => {
    const res = await axios.get(`${API}/auth/youtube`);
    window.location.href = res.data.url;
  };

  const disconnectYoutube = async () => {
    try {
      await axios.post(`${API}/auth/youtube/disconnect`);
      setYoutube({ connected: false, enabled: false, account: null });
      setMessage('✅ Disconnected from YouTube');
    } catch (err) {
      setMessage('❌ Error disconnecting');
      console.error('Error disconnecting:', err);
    }
  };

  const connectTiktok = async () => {
    try {
      const res = await axios.get(`${API}/auth/tiktok`);
      window.location.href = res.data.url;
    } catch (err) {
      setMessage(`❌ Error connecting to TikTok: ${err.response?.data?.detail || err.message}`);
      console.error('Error connecting TikTok:', err);
    }
  };

  const disconnectTiktok = async () => {
    try {
      await axios.post(`${API}/auth/tiktok/disconnect`);
      setTiktok({ connected: false, enabled: false, account: null });
      setMessage('✅ Disconnected from TikTok');
    } catch (err) {
      setMessage('❌ Error disconnecting from TikTok');
      console.error('Error disconnecting TikTok:', err);
    }
  };

  const connectInstagram = async () => {
    try {
      const res = await axios.get(`${API}/auth/instagram`);
      window.location.href = res.data.url;
    } catch (err) {
      setMessage(`❌ Error connecting to Instagram: ${err.response?.data?.detail || err.message}`);
      console.error('Error connecting Instagram:', err);
    }
  };

  const disconnectInstagram = async () => {
    try {
      await axios.post(`${API}/auth/instagram/disconnect`);
      setInstagram({ connected: false, enabled: false, account: null });
      setMessage('✅ Disconnected from Instagram');
    } catch (err) {
      setMessage('❌ Error disconnecting from Instagram');
      console.error('Error disconnecting Instagram:', err);
    }
  };

  const toggleInstagram = async () => {
    const newEnabled = !instagram.enabled;
    setInstagram({ ...instagram, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/instagram/toggle?${params.toString()}`);
    } catch (err) {
      console.error('Error toggling Instagram:', err);
      // Revert on error
      setInstagram({ ...instagram, enabled: !newEnabled });
    }
  };

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
    const form = new FormData();
    form.append('file', file);
    
    // Add CSRF token to form data as fallback (backend checks both header and form data)
    if (csrfToken) {
      form.append('csrf_token', csrfToken);
    }
    
    // Add temp entry with uploading status
    const tempId = Date.now();
    const tempVideo = {
      id: tempId,
      filename: file.name,
      status: 'uploading',
      progress: 0
    };
    setVideos(prev => [...prev, tempVideo]);
    
      try {
        const res = await axios.post(`${API}/videos`, form, {
          onUploadProgress: (progressEvent) => {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setVideos(prev => prev.map(v =>
              v.id === tempId ? { ...v, progress: percent } : v
            ));
          }
        });
        
        // Replace temp with real video data
        setVideos(prev => prev.map(v => 
          v.id === tempId ? { ...res.data, progress: 100 } : v
        ));
        setMessage(`✅ Added ${file.name}`);
      } catch (err) {
        setVideos(prev => prev.filter(v => v.id !== tempId));
        let errorMsg = err.response?.data?.detail || err.message || 'Error adding video';
        
        // Provide more helpful error messages
        if (err.response?.status === 403 && errorMsg.includes('CSRF')) {
          errorMsg = 'CSRF token error. Please refresh the page and try again.';
        } else if (err.response?.status === 401) {
          errorMsg = 'Session expired. Please refresh the page.';
        } else if (!err.response) {
          errorMsg = 'Network error. Please check your connection.';
        }
        
        setMessage(`❌ ${errorMsg}`);
        console.error('Error adding video:', err);
      }
  };

  const removeVideo = async (id) => {
    await axios.delete(`${API}/videos/${id}`);
    setVideos(videos.filter(v => v.id !== id));
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

  const toggleYoutube = async () => {
    const newEnabled = !youtube.enabled;
    setYoutube({ ...youtube, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/youtube/toggle?${params.toString()}`);
    } catch (err) {
      console.error('Error toggling YouTube:', err);
      // Revert on error
      setYoutube({ ...youtube, enabled: !newEnabled });
    }
  };

  const toggleTiktok = async () => {
    const newEnabled = !tiktok.enabled;
    setTiktok({ ...tiktok, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/tiktok/toggle?${params.toString()}`);
    } catch (err) {
      console.error('Error toggling TikTok:', err);
      // Revert on error
      setTiktok({ ...tiktok, enabled: !newEnabled });
    }
  };

  const upload = async () => {
    if (!youtube.enabled && !tiktok.enabled && !instagram.enabled) {
      setMessage('❌ Enable at least one destination first');
      return;
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
      setMessage(`❌ Upload failed: ${errorMsg}`);
      
      // Refresh to get real status
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="app">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1>{appTitle}</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span style={{ color: '#999', fontSize: '0.9rem' }}>
            {user.email}
          </span>
          <button 
            onClick={handleLogout}
            style={{
              padding: '0.5rem 1rem',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '4px',
              color: '#ef4444',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: '500'
            }}
          >
            Logout
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
                      className="input-text"
                    />
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
              backgroundColor: youtube.connected ? '#22c55e' : '#ef4444',
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
              backgroundColor: tiktok.connected ? '#22c55e' : '#ef4444',
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
              backgroundColor: instagram.connected ? '#22c55e' : '#ef4444',
              flexShrink: 0
            }}></div>
            {instagram.connected && (
              <span className="account-info" style={{ fontSize: '0.9em', color: '#999', marginLeft: '4px' }}>
                {instagram.account ? (
                  instagram.account.username ? 
                    `@${instagram.account.username}` : 'Unknown account'
                ) : (
                  'Loading account...'
                )}
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
        <h2>Queue ({videos.length})</h2>
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
            marginLeft: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Privacy Policy
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
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
    </Routes>
  );
}

export default App;

