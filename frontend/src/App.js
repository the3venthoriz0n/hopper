import React, { useState, useEffect, useCallback } from 'react';
import { Routes, Route, Link, useNavigate, useLocation, Navigate } from 'react-router-dom';
import Cookies from 'js-cookie';
import axios from 'axios';
import './App.css';
import Terms from './Terms';
import Privacy from './Privacy';
import DeleteYourData from './DeleteYourData';
import Help from './Help';
import Login from './Login';
import AdminDashboard from './AdminDashboard';
import Pricing from './Pricing';
import { useWebSocket } from './hooks/useWebSocket';


// SYSTEM DESIGN: RGB values stored separately for opacity support
// Use rgba() helper function for colors with opacity
export const HOPPER_COLORS = {
  // Primary Palette - Deep, Slate-based tones
  base: '#0F1115',      // Slightly deeper for better depth
  secondary: '#1A1D23', // Clearer separation from base
  accent: '#969D9E',    // Balanced Sage/Teal (Better contrast than #696F70)
  light: '#E2E1D5',     // Brightened slightly for readability
  white: '#FFFFFF',
  black: '#0F1115', 

  // Semantic colors - Refined to match the muted palette
  success: '#43A047',   // Slightly more organic green
  error: '#E53935',     // Vibrant but deep red
  warning: '#FFB300',   // Amber warning
  info: '#1E88E5',      // Clearer blue
  link: '#0066cc',      // Link color (blue)
  linkHover: '#0052a3', // Link hover color (darker blue)
  grey: '#666666',      // Grey text color
  greyLight: '#CCCCCC', // Light grey for separators
  greyBorder: '#EEEEEE', // Very light grey for borders
  
  // RGB values 
  rgb: {
    base: '15, 17, 21',
    secondary: '26, 29, 35',
    accent: '120, 149, 150',
    light: '226, 225, 213',
    white: '255, 255, 255',
    success: '67, 160, 71',
    error: '229, 57, 53',
    warning: '255, 179, 0',
    info: '30, 136, 229',
    link: '0, 102, 204',
    linkHover: '0, 82, 163',
    grey: '102, 102, 102',
    greyLight: '204, 204, 204',
    greyBorder: '238, 238, 238'
  }
};

// Helper function for rgba colors with opacity
// Usage: rgba(HOPPER_COLORS.rgb.blue, 0.5) => 'rgba(66, 133, 244, 0.5)'
const rgba = (rgb, opacity) => `rgba(${rgb}, ${opacity})`;

// Circular Progress Component for Token Usage
// monthlyTokens tracks starting balance (plan allocation + granted tokens)
const CircularTokenProgress = ({ tokensRemaining, tokensUsed, monthlyTokens, overageTokens, unlimited, isLoading }) => {
  if (unlimited) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          background: `conic-gradient(from 0deg, ${HOPPER_COLORS.success} 0deg 360deg)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative'
        }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: HOPPER_COLORS.base,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1rem',
            fontWeight: '700',
            color: HOPPER_COLORS.success
          }}>
            ∞
          </div>
        </div>
        <div style={{ fontSize: '0.6rem', color: HOPPER_COLORS.grey, textAlign: 'center' }}>Unlimited</div>
      </div>
    );
  }

  // monthlyTokens = starting balance for period (plan + granted tokens)
  // This resets at billing and increases when tokens are granted
  const effectiveMonthlyTokens = monthlyTokens || 0;
  
  // Calculate percentage: tokensUsed / monthlyTokens
  // This shows usage percentage of starting balance
  const percentage = effectiveMonthlyTokens > 0 ? (tokensUsed / effectiveMonthlyTokens) * 100 : 0;
  const hasOverage = overageTokens > 0;
  
  // Color based on usage - red when in overage, amber when high usage, green otherwise
  let progressColor = HOPPER_COLORS.success;
  if (hasOverage) {
    progressColor = HOPPER_COLORS.error; // red when in overage
  } else if (percentage >= 90) {
    progressColor = HOPPER_COLORS.warning; // amber when 90% or more used
  }
  
  // Calculate stroke-dasharray for the circle
  const radius = 21;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
      <div style={{ position: 'relative', width: '48px', height: '48px' }}>
        <svg width="48" height="48" style={{ transform: 'rotate(-90deg)' }}>
          {/* Background circle */}
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke={rgba(HOPPER_COLORS.rgb.white, 0.1)}
            strokeWidth="3"
          />
          {/* Progress circle */}
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke={progressColor}
            strokeWidth="3"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.5s ease', opacity: isLoading ? 0.5 : 1 }}
          />
        </svg>
        {/* Dark background circle */}
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          background: HOPPER_COLORS.base,
          zIndex: 1
        }} />
        {/* Center text - show usage / monthlyTokens (starting balance) */}
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.05rem',
          zIndex: 2
        }}>
          <div style={{ fontSize: '0.65rem', fontWeight: '700', color: isLoading ? HOPPER_COLORS.grey : HOPPER_COLORS.light, lineHeight: '1' }}>
            {tokensUsed}
          </div>
          <div style={{ fontSize: '0.5rem', color: isLoading ? HOPPER_COLORS.grey : HOPPER_COLORS.grey, lineHeight: '1' }}>
            / {effectiveMonthlyTokens}
          </div>
        </div>
      </div>
    </div>
  );
};


// Axios will now automatically read the 'csrf_token_client' cookie 
// and put it into the 'X-CSRF-Token' header for every request.
axios.defaults.withCredentials = true;
axios.defaults.xsrfCookieName = 'csrf_token_client';
axios.defaults.xsrfHeaderName = 'X-CSRF-Token';

// CSRF Token Management
let csrfToken = null;

// Build API URL helper function
const getApiUrl = () => {
  const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
  return `${backendUrl}/api`;
};

// Custom hook for authentication state management
function useAuth() {
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

axios.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);

axios.interceptors.request.use(
  (config) => {
    // Read the non-HttpOnly cookie we set in the backend
    const token = Cookies.get('csrf_token_client');
    
    if (token) {
      config.headers['X-CSRF-Token'] = token;
      // Optional: console.log("CSRF Token injected:", token);
    }
    
    return config;
  },
  (error) => Promise.reject(error)
);

// Loading Screen Component
function LoadingScreen() {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: HOPPER_COLORS.white,
      color: HOPPER_COLORS.black
    }}>
      <div>Loading...</div>
    </div>
  );
}

// Protected Route Component - handles authentication checks
function ProtectedRoute({ children, requireAdmin = false }) {
  const location = useLocation();
  const { user, isAdmin, setUser, authLoading } = useAuth();

  if (authLoading) {
    return <LoadingScreen />;
  }

  if (!user) {
    // Save the attempted location for redirect after login
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/app" replace />;
  }

  // Pass auth context via props
  return React.cloneElement(children, { user, isAdmin, setUser, authLoading });
}

// Simple public landing page for unauthenticated visitors
function PublicLanding() {
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';

  return (
    <div className="landing-container">
      <header className="landing-header">
        <div className="landing-logo">
          <span className="landing-logo-icon">🐸</span>
          <span>{appTitle.replace('🐸 ', '')}</span>
        </div>
        <nav className="landing-nav">
          <Link to="/pricing" className="landing-nav-link">
            Pricing
          </Link>
          <Link to="/help" className="landing-nav-link">
            Help
          </Link>
          <Link to="/login" className="landing-nav-button">
            Login
          </Link>
        </nav>
      </header>

      <main className="landing-main">
        <div className="landing-content">
          <p className="landing-tagline">
            Creator upload automation
          </p>
          <h1 className="landing-title">
            Upload once.<br />Hopper handles YouTube, TikTok, and Instagram for you.
          </h1>
          <p className="landing-description">
            Hopper is a creator tool that automates multi-platform uploads and scheduling.
            Connect your accounts, drag in videos, and let hopper handle the rest.
          </p>
          <div className="landing-cta">
            <Link to="/login" className="landing-cta-button">
              Log in
            </Link>
          </div>
        </div>
      </main>

      <footer style={{
        marginTop: '3rem',
        padding: '1.5rem',
        textAlign: 'center',
        borderTop: `1px solid ${HOPPER_COLORS.greyBorder}`,
        color: HOPPER_COLORS.grey,
        fontSize: '0.9rem'
      }}>
        <Link 
          to="/terms" 
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            marginRight: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Terms of Service
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/privacy" 
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            margin: '0 1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Privacy Policy
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/help"
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            margin: '0 1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Help
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/delete-your-data"
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            marginLeft: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Delete Your Data
        </Link>
        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
          © {new Date().getFullYear()} hopper
        </div>
        <div style={{ marginTop: '0.25rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
          <a 
            href={process.env.REACT_APP_VERSION && process.env.REACT_APP_VERSION !== 'dev' 
              ? `https://github.com/the3venthoriz0n/hopper/releases/tag/${process.env.REACT_APP_VERSION}`
              : 'https://github.com/the3venthoriz0n/hopper/releases'}
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            {process.env.REACT_APP_VERSION || 'dev'}
          </a>
        </div>
      </footer>
    </div>
  );
}

// Landing or App - smart redirect based on auth state
function LandingOrApp() {
  const { user, authLoading } = useAuth();
  
  if (authLoading) {
    return <LoadingScreen />;
  }
  
  return user ? <Navigate to="/app" replace /> : <PublicLanding />;
}

// App Routes - nested routes for app section
function AppRoutes({ user, isAdmin, setUser, authLoading }) {
  return (
    <Routes>
      <Route index element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
      <Route path="subscription" element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
      <Route path="subscription/success" element={<Home user={user} isAdmin={isAdmin} setUser={setUser} authLoading={authLoading} />} />
    </Routes>
  );
}

// 404 Not Found Component
function NotFound() {
  return (
    <div style={{ 
      textAlign: 'center', 
      padding: '2rem',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      background: HOPPER_COLORS.white,
      color: HOPPER_COLORS.black
    }}>
      <h1 style={{ fontSize: '3rem', marginBottom: '1rem' }}>404</h1>
      <p style={{ fontSize: '1.2rem', marginBottom: '2rem' }}>Page Not Found</p>
      <Link 
        to="/" 
        style={{ 
          color: HOPPER_COLORS.grey, 
          textDecoration: 'none',
          fontSize: '1.1rem'
        }}
      >
        Go Home
      </Link>
    </div>
  );
}

// Platform configuration - DRY, extensible (matches backend config.py)
const PLATFORM_CONFIG = {
  youtube: {
    enabledKey: 'youtube_enabled',
    titleField: 'youtube_title',
    icon: 'youtube',
    color: '#FF0000',
  },
  tiktok: {
    enabledKey: 'tiktok_enabled',
    titleField: 'tiktok_title',
    icon: 'tiktok',
    color: '#000000',
  },
  instagram: {
    enabledKey: 'instagram_enabled',
    titleField: 'instagram_caption',
    icon: 'instagram',
    color: '#E4405F',
  },
};

function Home({ user, isAdmin, setUser, authLoading }) {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Build API URL at runtime - always use HTTPS
  const API = getApiUrl();
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';
  
  // Determine if we're on the subscription view
  const isSubscriptionView = location.pathname.startsWith('/app/subscription');
  
  // All state hooks must be declared before any conditional returns (Rules of Hooks)
  const [youtube, setYoutube] = useState({ connected: false, enabled: false, account: null, token_status: 'valid' });
  const [tiktok, setTiktok] = useState({ connected: false, enabled: false, account: null, token_status: 'valid' });
  const [tiktokCreatorInfo, setTiktokCreatorInfo] = useState(null);
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
    privacy_level: '',
    allow_comments: false,
    allow_duet: false,
    allow_stitch: false,
    title_template: '',
    description_template: '',
    commercial_content_disclosure: false,
    commercial_content_your_brand: false,
    commercial_content_branded: false
  });
  const [instagramSettings, setInstagramSettings] = useState({
    caption_template: '',
    disable_comments: false,
    disable_likes: false,
    media_type: 'REELS',
    share_to_feed: true,
    cover_url: ''
    // audio_name: '' // Commented out - removed Audio Name feature
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showTiktokSettings, setShowTiktokSettings] = useState(false);
  const [showInstagramSettings, setShowInstagramSettings] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [editCommercialContentDisclosure, setEditCommercialContentDisclosure] = useState(false);
  const [editCommercialContentYourBrand, setEditCommercialContentYourBrand] = useState(false);
  const [editCommercialContentBranded, setEditCommercialContentBranded] = useState(false);
  const [editTiktokPrivacy, setEditTiktokPrivacy] = useState('');
  const [newWord, setNewWord] = useState('');
  const [wordbankExpanded, setWordbankExpanded] = useState(false);
  const [showGlobalSettings, setShowGlobalSettings] = useState(false);
  const [maxFileSize, setMaxFileSize] = useState(null);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [sendingResetEmail, setSendingResetEmail] = useState(false);
  const [resetEmailSent, setResetEmailSent] = useState(false);
  const [showDangerZone, setShowDangerZone] = useState(false);
  
  // Subscription & token state
  const [subscription, setSubscription] = useState(null);
  const [tokenBalance, setTokenBalance] = useState(null);
  const [availablePlans, setAvailablePlans] = useState([]);
  const [loadingSubscription, setLoadingSubscription] = useState(false);
  const [loadingPlanKey, setLoadingPlanKey] = useState(null); // Track which specific plan is loading
  const [notification, setNotification] = useState(null); // For popup notifications
  const [confirmDialog, setConfirmDialog] = useState(null); // For confirmation dialogs
  const [destinationModal, setDestinationModal] = useState(null);
  const [overrideInputValues, setOverrideInputValues] = useState({}); // { videoId, platform, video }
  const [expandedDestinationErrors, setExpandedDestinationErrors] = useState(new Set()); // Track which destination errors are expanded

  // Check for Google login callback
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const googleLogin = urlParams.get('google_login');
    
    if (googleLogin === 'success') {
      setMessage('✅ Successfully logged in with Google!');
      window.history.replaceState({}, '', '/app');
      // Close popup if this is a popup window
      if (window.opener) {
        window.close();
      }
    } else if (googleLogin === 'error') {
      setMessage('❌ Google login failed. Please try again.');
      window.history.replaceState({}, '', '/app');
      // Close popup if this is a popup window
      if (window.opener) {
        window.close();
      }
    }
  }, []);
  
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
  }, [videos, editingVideo, showSettings, showTiktokSettings, showAccountSettings, showDeleteConfirm, user]);

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

  const loadSubscription = useCallback(async () => {
    if (!user) return;
    
    try {
      const [subscriptionRes, plansRes] = await Promise.all([
        axios.get(`${API}/subscription/current`),
        axios.get(`${API}/subscription/plans`)
      ]);
      
      setSubscription(subscriptionRes.data.subscription);
      // Always set token balance - default to 0 if missing
      if (subscriptionRes.data.token_balance) {
        setTokenBalance(subscriptionRes.data.token_balance);
      } else {
        // Default token balance when no subscription exists
        setTokenBalance({
          tokens_remaining: 0,
          tokens_used_this_period: 0,
          monthly_tokens: 0,
          overage_tokens: 0,
          unlimited: false,
          period_start: null,
          period_end: null
        });
      }
      setAvailablePlans(plansRes.data.plans || []);
    } catch (err) {
      console.error('Error loading subscription:', err);
      // On error, set safe defaults
      setSubscription(null);
      setTokenBalance({
        tokens_remaining: 0,
        tokens_used_this_period: 0,
        monthly_tokens: 0,
        overage_tokens: 0,
        unlimited: false,
        period_start: null,
        period_end: null
      });
      // Still try to load plans even on error
      try {
        const plansRes = await axios.get(`${API}/subscription/plans`);
        setAvailablePlans(plansRes.data.plans || []);
      } catch (plansErr) {
        console.error('Error loading plans:', plansErr);
        setAvailablePlans([]);
      }
    }
  }, [API, user]);

  // Load subscription when user changes
  useEffect(() => {
    if (user) {
      loadSubscription();
    }
  }, [user, loadSubscription]);

  // Check for subscription upgrade success message (from query param after redirect)
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('upgraded') === 'success' && location.pathname === '/app/subscription') {
      // Wait for subscription and token balance to be loaded before showing success message
      // This ensures tokens are updated before showing the popup
      const showSuccessMessage = async () => {
        if (!user) return;
        
        // Get initial token balance for comparison
        const initialTokenBalance = tokenBalance;
        
        // Reload subscription and token balance multiple times to ensure we have latest data
        // This accounts for webhook processing delays
        let attempts = 0;
        const maxAttempts = 5;
        
        while (attempts < maxAttempts) {
          await loadSubscription();
          
          // Wait for token balance to update (webhooks may take a moment)
          await new Promise(resolve => setTimeout(resolve, 800));
          
          // Check if token balance has been updated (new subscription should have different tokens)
          // If tokenBalance is still null or hasn't changed after multiple attempts, continue anyway
          if (tokenBalance && tokenBalance.monthly_tokens) {
            // Token balance has been loaded, we can proceed
            break;
          }
          
          attempts++;
          
          // If we've tried multiple times, proceed anyway (tokens may still be syncing)
          if (attempts >= maxAttempts) {
            // One final reload and wait
            await loadSubscription();
            await new Promise(resolve => setTimeout(resolve, 1000));
            break;
          }
        }
        
        // Additional wait to ensure UI has fully updated with new token balance
        await new Promise(resolve => setTimeout(resolve, 500));
        
        // Now show success message after everything is updated
        setMessage('✅ Subscription upgraded successfully! Your new plan is now active.');
        
        // Clean up the query parameter after a brief delay to ensure message is shown
        setTimeout(() => {
          urlParams.delete('upgraded');
          const newUrl = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
          window.history.replaceState({}, '', newUrl);
        }, 100);
      };
      
      showSuccessMessage();
    }
  }, [location.pathname, location.search, user, loadSubscription, tokenBalance]);

  // Check for checkout success (from /app/subscription/success route or query param)
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id');
    const isSuccessPage = location.pathname === '/app/subscription/success' || urlParams.get('checkout') === 'success';
    
    if (isSuccessPage && user && sessionId) {
      setMessage('✅ Payment successful! Processing your subscription update...');
      
      let attempts = 0;
      const maxAttempts = 10; // Max polling attempts
      let pollTimeout = null;
      let isCleanedUp = false;
      
      // Exponential backoff: start at 500ms, double each time, max 5s
      const getPollDelay = (attempt) => Math.min(500 * Math.pow(2, attempt), 5000);
      
      const checkCheckoutStatus = async () => {
        if (isCleanedUp) return;
        
        attempts++;
        try {
          // Check checkout session status (more reliable than polling subscription)
          const statusRes = await axios.get(`${API}/subscription/checkout-status`, {
            params: { session_id: sessionId }
          });
          
          const { status, payment_status, subscription_created } = statusRes.data;
          
          if (status === 'completed' && payment_status === 'paid') {
            // Payment confirmed, now check if subscription was created
            if (subscription_created) {
              // Subscription is ready, reload subscription data and token balance multiple times
              // This ensures tokens are fully synced before showing success message
              
              // First reload
              await loadSubscription();
              await new Promise(resolve => setTimeout(resolve, 1000));
              
              // Second reload to catch any webhook updates
              await loadSubscription();
              await new Promise(resolve => setTimeout(resolve, 1000));
              
              // Third reload to ensure tokens are definitely updated
              await loadSubscription();
              await new Promise(resolve => setTimeout(resolve, 500));
              
              // Check if there's a canceled subscription notification to show
              const canceledSubInfo = sessionStorage.getItem('upgrade_canceled_subscription');
              if (canceledSubInfo) {
                try {
                  const info = JSON.parse(canceledSubInfo);
                  const planName = availablePlans.find(p => p.key === info.new_plan_key)?.name || info.new_plan_key;
                  setNotification({
                    type: 'info',
                    title: 'Subscription Upgraded',
                    message: `Your ${info.canceled_plan_type} subscription has been canceled and replaced with ${planName}. Your new plan is now active.`
                  });
                  setTimeout(() => setNotification(null), 8000);
                  sessionStorage.removeItem('upgrade_canceled_subscription');
                } catch (e) {
                  console.error('Error parsing canceled subscription info:', e);
                  sessionStorage.removeItem('upgrade_canceled_subscription');
                }
              }
              
              // Navigate to subscription page with success flag - message will be shown by the other useEffect
              // The upgrade success handler will verify tokens are updated before showing the message
              if (location.pathname === '/app/subscription/success') {
                navigate('/app/subscription?upgraded=success', { replace: true });
              } else {
                // If already on subscription page, navigate to trigger the useEffect
                navigate('/app/subscription?upgraded=success', { replace: true });
              }
              return; // Stop polling
            } else if (attempts < maxAttempts) {
              // Payment confirmed but subscription not created yet (webhook processing)
              // Continue polling with exponential backoff
              const delay = getPollDelay(attempts);
              pollTimeout = setTimeout(checkCheckoutStatus, delay);
              return;
            }
          }
          
          // If we've exhausted attempts, show message and redirect
          if (attempts >= maxAttempts) {
            if (payment_status === 'paid') {
              setMessage('✅ Payment successful! Your subscription should be active shortly. If you don\'t see the update, please refresh the page.');
            } else {
              setMessage('✅ Payment processing. Your subscription will be active shortly.');
            }
            if (location.pathname === '/app/subscription/success') {
              navigate('/app/subscription', { replace: true });
            }
            return;
          }
          
          // Continue polling with exponential backoff
          const delay = getPollDelay(attempts);
          pollTimeout = setTimeout(checkCheckoutStatus, delay);
          
        } catch (err) {
          console.error('Error checking checkout status:', err);
          
          // If it's a 403 or 404, the session might be invalid - stop polling
          if (err.response?.status === 403 || err.response?.status === 404) {
            setMessage('⚠️ Could not verify checkout session. Please check your subscription status.');
            if (location.pathname === '/app/subscription/success') {
              navigate('/app/subscription', { replace: true });
            }
            return;
          }
          
          // For other errors, retry with exponential backoff
          if (attempts < maxAttempts) {
            const delay = getPollDelay(attempts);
            pollTimeout = setTimeout(checkCheckoutStatus, delay);
          } else {
            setMessage('✅ Payment successful! Your subscription should be active shortly.');
            if (location.pathname === '/app/subscription/success') {
              navigate('/app/subscription', { replace: true });
            }
          }
        }
      };
      
      // Start polling with initial delay
      pollTimeout = setTimeout(checkCheckoutStatus, getPollDelay(0));
      
      // Cleanup on unmount
      return () => {
        isCleanedUp = true;
        if (pollTimeout) {
          clearTimeout(pollTimeout);
        }
      };
    } else if (isSuccessPage && user && !sessionId) {
      // No session_id, just reload subscription and show message
      loadSubscription();
      setMessage('✅ Payment successful! Your subscription should be active shortly.');
      if (location.pathname === '/app/subscription/success') {
        navigate('/app/subscription', { replace: true });
      }
    }
  }, [user, API, location.pathname, navigate, loadSubscription]);

  // Token balance updates are handled via WebSocket events - no polling needed

  // Handle subscription upgrade
  const handleUpgrade = async (planKey) => {
    // Check if user has an active subscription that will be canceled
    if (subscription && subscription.status === 'active' && subscription.plan_type && subscription.plan_type !== 'free' && subscription.plan_type !== 'unlimited') {
      // Show confirmation dialog
      const planName = availablePlans.find(p => p.key === planKey)?.name || planKey;
      const currentPlanName = availablePlans.find(p => p.key === subscription.plan_type)?.name || subscription.plan_type;
      
      const newPlan = availablePlans.find(p => p.key === planKey);
      const currentPlan = availablePlans.find(p => p.key === subscription.plan_type);
      
      // Format prices for display (new pricing: flat monthly fee + overage)
      const formatPlanPrice = (plan) => {
        if (!plan?.price) return null;
        if (plan.key === 'free') return 'Free';
        if (plan.tokens === -1) return plan.price.formatted;
        
        // New pricing: amount_dollars is the flat monthly fee
        const monthlyFee = plan.price.amount_dollars || 0;
        const overagePrice = plan.overage_price?.amount_dollars;
        
        if (overagePrice !== undefined && overagePrice !== null) {
          // Display as: "$3.00/Month (1.5c / token)"
          const overageCents = (overagePrice * 100).toFixed(1);
          return `$${monthlyFee.toFixed(2)}/Month (${overageCents}c / token)`;
        } else {
          // Fallback if overage price not available
          return `$${monthlyFee.toFixed(2)}/Month`;
        }
      };
      
      const newPlanPrice = formatPlanPrice(newPlan);
      const currentPlanPrice = formatPlanPrice(currentPlan);
      
      setConfirmDialog({
        title: 'Upgrade Subscription?',
        message: `You currently have an active ${currentPlanName} subscription${currentPlanPrice ? ` (${currentPlanPrice})` : ''}. Upgrading to ${planName}${newPlanPrice ? ` (${newPlanPrice})` : ''} will cancel your current subscription and replace it with the new plan. Your current token balance will be preserved.`,
        onConfirm: async () => {
          setConfirmDialog(null);
          await proceedWithUpgrade(planKey);
        },
        onCancel: () => {
          setConfirmDialog(null);
        }
      });
    } else {
      // No active subscription, proceed directly
      await proceedWithUpgrade(planKey);
    }
  };

  const proceedWithUpgrade = async (planKey) => {
    setLoadingPlanKey(planKey); // Set which specific plan is loading
    setLoadingSubscription(true);
    // Clear any previous canceled subscription info (in case user is starting a new checkout)
    sessionStorage.removeItem('upgrade_canceled_subscription');
    try {
      const res = await axios.post(`${API}/subscription/create-checkout`, { plan_key: planKey });
      if (res.data.url) {
        // If a subscription was canceled, store info to show after successful checkout
        if (res.data.canceled_subscription) {
          sessionStorage.setItem('upgrade_canceled_subscription', JSON.stringify({
            canceled_plan_type: res.data.canceled_subscription.plan_type,
            new_plan_key: planKey
          }));
        }
        window.location.href = res.data.url;
      }
    } catch (err) {
      // Clear stored info on error since checkout didn't start
      sessionStorage.removeItem('upgrade_canceled_subscription');
      console.error('Error creating checkout session:', err);
      
      // Check if user already has an active subscription (shouldn't happen with our new logic, but handle it)
      if (err.response?.status === 400 && err.response?.data?.portal_url) {
        // User already has subscription - show popup and redirect to customer portal
        setNotification({
          type: 'error',
          title: 'Active Subscription Found',
          message: 'You already have an active subscription. Opening subscription management...'
        });
        setTimeout(() => {
          setNotification(null);
          window.location.href = err.response.data.portal_url;
        }, 2000);
      } else if (err.response?.status === 400 && err.response?.data?.message) {
        // Show the error message from backend as popup
        setNotification({
          type: 'error',
          title: 'Checkout Error',
          message: err.response.data.message || 'Failed to start checkout. Please try again.'
        });
        setTimeout(() => setNotification(null), 8000);
      } else {
        // Generic error popup
        setNotification({
          type: 'error',
          title: 'Checkout Failed',
          message: err.response?.data?.detail || err.response?.data?.message || 'Failed to start checkout. Please try again.'
        });
        setTimeout(() => setNotification(null), 8000);
      }
    } finally {
      setLoadingPlanKey(null); // Clear loading state
      setLoadingSubscription(false);
    }
  };

  // Handle manage subscription (Stripe customer portal or purchase page)
  const handleManageSubscription = async () => {
    setLoadingSubscription(true);
    try {
      const res = await axios.get(`${API}/subscription/portal`);
      if (res.data.url) {
        if (res.data.action === 'purchase') {
          // User is on free plan - scroll to plans section or show purchase options
          // The URL points back to the subscription page, so we just scroll to plans
          const plansSection = document.getElementById('subscription-plans');
          if (plansSection) {
            plansSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } else {
            // If plans section doesn't exist, just navigate to the page
            window.location.href = res.data.url;
          }
        } else {
          // User has paid subscription - open Stripe customer portal
          window.location.href = res.data.url;
        }
      }
    } catch (err) {
      console.error('Error opening subscription portal:', err);
      setMessage('❌ Failed to open subscription management. Please try again.');
    } finally {
      setLoadingSubscription(false);
    }
  };

  // Handle cancel subscription
  const handleOpenStripePortal = async () => {
    setLoadingSubscription(true);
    try {
      const res = await axios.get(`${API}/subscription/portal`);
      if (res.data.url) {
        window.location.href = res.data.url;
      }
    } catch (err) {
      console.error('Error opening Stripe portal:', err);
      setMessage('❌ Failed to open subscription management. Please try again.');
      setLoadingSubscription(false);
    }
  };

  const handleCancelSubscription = async () => {
    setLoadingSubscription(true);
    try {
      const res = await axios.post(`${API}/subscription/cancel`);
      if (res.data.status === 'success') {
        setMessage(`✅ ${res.data.message || 'Subscription canceled successfully'}`);
        // Reload subscription data to reflect the change
        await loadSubscription();
        setNotification({
          type: 'success',
          title: 'Subscription Canceled',
          message: `Your subscription has been canceled and you've been switched to the free plan. Your ${res.data.tokens_preserved || 0} tokens have been preserved.`
        });
        setTimeout(() => setNotification(null), 5000);
      } else if (res.data.status === 'error') {
        // Handle error response (e.g., trying to cancel free plan)
        setMessage(`❌ ${res.data.message || 'Failed to cancel subscription'}`);
        setNotification({
          type: 'error',
          title: 'Cancel Failed',
          message: res.data.message || 'Cannot cancel this subscription.'
        });
        setTimeout(() => setNotification(null), 5000);
      }
    } catch (err) {
      console.error('Error canceling subscription:', err);
      setMessage('❌ Failed to cancel subscription. Please try again.');
      setNotification({
        type: 'error',
        title: 'Cancel Failed',
        message: err.response?.data?.detail || err.response?.data?.message || 'Failed to cancel subscription. Please try again.'
      });
      setTimeout(() => setNotification(null), 5000);
    } finally {
      setLoadingSubscription(false);
    }
  };

  const loadVideos = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/videos`);
      const newData = res.data;
      
      // Deduplicate in case backend ever returns duplicates
      const seenIds = new Set();
      const uniqueData = newData.filter(video => {
        if (seenIds.has(video.id)) {
          console.warn(`⚠️ Duplicate video ID from API: ${video.id}, skipping`);
          return false;
        }
        seenIds.add(video.id);
        return true;
      });
      
      setVideos(prevVideos => {
        // Preserve temp videos during reload
        const tempVideos = prevVideos.filter(v => typeof v.id === 'string' && v.id.startsWith('temp-'));
        const tempVideoIds = new Set(tempVideos.map(v => v.id));
        
        // Check for new token-related failures
        if (prevVideos && prevVideos.length > 0) {
          uniqueData.forEach(newVideo => {
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
        
        // Compare only real videos (excluding temp videos) to determine if state changed
        const prevRealVideos = prevVideos.filter(v => !tempVideoIds.has(v.id));
        if (JSON.stringify(prevRealVideos) === JSON.stringify(uniqueData)) {
          return prevVideos; // No changes to real videos, keep temp videos
        }
        
        // Merge: backend videos + temp videos
        return [...uniqueData, ...tempVideos];
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
  // Calculate total token cost for all queued videos (uses backend-calculated tokens_required)
  const calculateQueueTokenCost = () => {
    return videos
      .filter(v => (v.status === 'pending' || v.status === 'scheduled') && v.tokens_consumed === 0)
      .reduce((total, video) => {
        return total + (video.tokens_required || 0);
      }, 0);
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

  const loadTiktokAccount = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/tiktok/account`);
      if (res.data.account) {
        setTiktok(prev => ({
          ...prev,
          // Don't update connected status - it comes from loadDestinations
          account: res.data.account,
          token_status: res.data.token_status || 'valid',
          token_expired: res.data.token_expired || false,
          token_expires_soon: res.data.token_expires_soon || false
        }));
        // Store creator_info for privacy options and interaction settings
        if (res.data.creator_info) {
          console.log('TikTok creator_info received:', res.data.creator_info);
          console.log('privacy_level_options:', res.data.creator_info.privacy_level_options);
          setTiktokCreatorInfo(res.data.creator_info);
        } else {
          console.warn('No creator_info in TikTok account response');
          setTiktokCreatorInfo(null);
        }
      } else {
        // Only update account info and token status, don't change connection status
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
      // Keep existing account info and connection status on error - don't disconnect
      // Only update token status if available in error response
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
      
      // Unified pattern for all platforms: Update connection/enabled status, preserve account info
      // Only clear account if explicitly disconnected
      const updatePlatformState = (setState, platformData) => {
      setState(prev => {
        const tokenExpired = platformData.token_expired || false;
        // Auto-disable destinations with expired tokens so we never upload there
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
      // Merge with default state to ensure all fields are defined
      setGlobalSettings({
        title_template: '{filename}',
        description_template: 'Uploaded via Hopper',
        wordbank: [],
        upload_immediately: true,
        schedule_mode: 'spaced',
        schedule_interval_value: 1,
        schedule_interval_unit: 'hours',
        schedule_start_time: '',
        upload_first_immediately: true,
        allow_duplicates: false,
        ...res.data
      });
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

  // WebSocket connection for real-time updates
  const handleWebSocketMessage = useCallback((message) => {
    const { event, payload } = message;
    
    switch (event) {
      case 'connected':
        console.log('✅ WebSocket connected, user_id:', payload.user_id);
        break;
        
      case 'video_added':
        // ROOT CAUSE FIX: Check if video already exists to prevent duplicates from race condition
        // Video might already be in state from HTTP response when file upload completes
        if (payload.video) {
          setVideos(prev => {
            // Check if video already exists (from HTTP response or previous WebSocket event)
            const existingIndex = prev.findIndex(v => v.id === payload.video.id);
            if (existingIndex !== -1) {
              // Update existing video
              const updated = [...prev];
              updated[existingIndex] = payload.video;
              return updated;
            }
            // Video doesn't exist, add it
            return [payload.video, ...prev];
          });
        }
        break;
        
      case 'video_status_changed':
        // Update video status in state
        setVideos(prev => prev.map(v => 
          v.id === payload.video_id 
            ? { ...v, status: payload.new_status }
            : v
        ));
        break;
        
      case 'video_updated':
        // Reload videos to get updated computed titles and settings
        loadVideos();
        break;
        
      case 'video_deleted':
        // Remove video from state
        setVideos(prev => prev.filter(v => v.id !== payload.video_id));
        break;
        
      case 'video_title_recomputed':
        // Update video title in state
        setVideos(prev => prev.map(v => 
          v.id === payload.video_id 
            ? { ...v, youtube_title: payload.new_title, tiktok_title: payload.new_title, instagram_title: payload.new_title }
            : v
        ));
        break;
        
      case 'videos_bulk_recomputed':
        // Reload all videos to get updated titles
        loadVideos();
        break;
        
      case 'destination_toggled':
        // ROOT CAUSE FIX: Backend now sends updated videos with correct upload_properties and platform_statuses
        // This eliminates race conditions and ensures UI immediately reflects the toggled state
        console.log('🔔 Received destination_toggled event:', payload);
        console.log('  Platform:', payload.platform);
        console.log('  Enabled:', payload.enabled);
        console.log('  Videos count:', payload.videos ? payload.videos.length : 0);
        
        const platform = payload.platform;
        const enabled = payload.enabled;
        const connected = payload.connected !== undefined ? payload.connected : true;
        
        // Update platform enabled/connected state for UI toggles
        if (platform === 'youtube') {
          setYoutube(prev => ({ ...prev, enabled, connected }));
        } else if (platform === 'tiktok') {
          setTiktok(prev => ({ ...prev, enabled, connected }));
        } else if (platform === 'instagram') {
          setInstagram(prev => ({ ...prev, enabled, connected }));
        }
        
        // Update videos with fresh data from backend (includes recomputed upload_properties and platform_statuses)
        if (payload.videos && Array.isArray(payload.videos)) {
          console.log('  Updating videos with', payload.videos.length, 'items');
          
          // Deduplicate backend videos
          const seenIds = new Set();
          const uniqueBackendVideos = payload.videos.filter(video => {
            if (seenIds.has(video.id)) {
              console.warn(`⚠️ Duplicate video ID detected: ${video.id}, skipping`);
              return false;
            }
            seenIds.add(video.id);
            return true;
          });
          
          // Merge with current state: update existing videos, preserve temp videos, add new ones
          setVideos(prev => {
            // Start with backend videos (source of truth for real videos)
            // Preserve temp videos (videos with IDs starting with "temp-")
            const backendVideoIds = new Set(uniqueBackendVideos.map(v => v.id));
            const tempVideos = prev.filter(v => typeof v.id === 'string' && v.id.startsWith('temp-') && !backendVideoIds.has(v.id));
            
            // Combine: backend videos first, then temp videos
            return [...uniqueBackendVideos, ...tempVideos];
          });
        } else {
          console.warn('  No videos in payload or not an array, falling back to HTTP reload');
          // Fallback: reload videos via HTTP if WebSocket data missing
          loadVideos();
        }
        break;
        
      case 'upload_progress':
        // Update upload progress (if we track it in state)
        // For now, just reload videos to get updated status
        loadVideos();
        break;
        
      case 'settings_changed':
        // Reload settings and videos (settings affect computed titles)
        loadGlobalSettings();
        if (payload.category === 'youtube') {
          loadYoutubeSettings();
        } else if (payload.category === 'tiktok') {
          loadTiktokSettings();
        } else if (payload.category === 'instagram') {
          loadInstagramSettings();
        }
        // Reload videos to get updated computed titles
        loadVideos();
        break;
        
      case 'token_balance_changed':
        // Update token balance immediately from WebSocket event
        if (payload.new_balance !== undefined) {
          setTokenBalance(prev => {
            const newBalance = {
              ...prev,
              tokens_remaining: payload.new_balance
            };
            // Update tokens_used_this_period if we can calculate it
            if (prev && payload.change_amount) {
              // If tokens were deducted (negative change), increase used count
              if (payload.change_amount < 0) {
                newBalance.tokens_used_this_period = (prev.tokens_used_this_period || 0) + Math.abs(payload.change_amount);
              }
            }
            return newBalance;
          });
        }
        // No need to reload full subscription - token balance is updated above
        break;
        
      default:
        // Unknown event, ignore
        break;
    }
  }, [loadVideos, loadGlobalSettings, loadYoutubeSettings, loadTiktokSettings, loadInstagramSettings, loadSubscription]);
  
  // Connect WebSocket when user is authenticated
  const wsUrl = user ? '/ws' : null;
  useWebSocket(wsUrl, handleWebSocketMessage, {
    reconnect: true,
    reconnectInterval: 3000,
    maxReconnectAttempts: 10,
    onError: (error) => {
      console.error('WebSocket error:', error);
    }
  });

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
    
    // WebSocket handles all real-time updates - no polling needed
  }, [user, loadDestinations, loadGlobalSettings, loadYoutubeSettings, loadTiktokSettings, loadInstagramSettings, loadVideos, loadYoutubeAccount, loadTiktokAccount, loadInstagramAccount, applyOAuthStatus, loadUploadLimits]);

  // Reusable style for flex text containers that extend to the right
  const flexTextStyle = { 
    flex: 1, 
    minWidth: 0, 
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    display: 'block',
    width: '100%'
  };
  
  // Show loading state while checking auth
  if (authLoading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: HOPPER_COLORS.white,
        color: HOPPER_COLORS.black
      }}>
        <div>Loading...</div>
      </div>
    );
  }
  

  const updateGlobalSettings = async (key, value) => {
    try {
      // Send as JSON body (backend now uses Pydantic schemas)
      const res = await axios.post(`${API}/global/settings`, { [key]: value });
      // Merge with current state to ensure all fields are defined
      setGlobalSettings(prev => ({
        ...prev,
        ...res.data
      }));
      setMessage(`✅ Settings updated`);
    } catch (err) {
      setMessage('❌ Error updating settings');
      console.error('Error updating settings:', err);
    }
  };

  const updateYoutubeSettings = async (key, value) => {
    try {
      // Send as JSON body (backend now uses Pydantic schemas)
      const res = await axios.post(`${API}/youtube/settings`, { [key]: value });
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
      // Don't send null or empty string for privacy_level - skip the request entirely
      if (key === 'privacy_level' && (!value || value === 'null' || value === '')) {
        // Skip sending empty/null privacy_level to avoid backend validation errors
        return;
      }
      // Send as JSON body (backend now uses Pydantic schemas)
      const res = await axios.post(`${API}/tiktok/settings`, { [key]: value });
      setTiktokSettings(res.data);
      
      if (key === 'privacy_level') {
        setMessage(`✅ Privacy level set to ${value}`);
      } else if (key.startsWith('commercial_content')) {
        setMessage(`✅ Commercial content settings updated`);
      } else {
        setMessage(`✅ TikTok settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating TikTok settings');
    }
  };

  const updateInstagramSettings = async (key, value) => {
    try {
      // Send as JSON body (backend now uses Pydantic schemas)
      const res = await axios.post(`${API}/instagram/settings`, { [key]: value });
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
    // Prevent enabling a destination if its OAuth token is expired
    if (currentState.token_expired) {
      setMessage(`⚠️ Token expired - reconnect your ${platform.charAt(0).toUpperCase() + platform.slice(1)} account before enabling uploads`);
      return;
    }

    const newEnabled = !currentState.enabled;
    // Use functional form to avoid stale closures
    setState(prev => ({ ...prev, enabled: newEnabled }));
    
    try {
      await axios.post(`${API}/destinations/${platform}/toggle`, {
        enabled: newEnabled
      });
    } catch (err) {
      console.error(`Error toggling ${platform}:`, err);
      // Revert on error using functional form
      setState(prev => ({ ...prev, enabled: !newEnabled }));
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
          const res = await axios.post(`${API}/global/wordbank`, {
            word: word
          });
          setGlobalSettings(prev => ({...prev, wordbank: res.data.wordbank}));
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
      setGlobalSettings(prev => ({
        ...prev,
        wordbank: prev.wordbank.filter(w => w !== word)
      }));
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
      setGlobalSettings(prev => ({...prev, wordbank: []}));
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
    
    // Tokens will be calculated by backend and returned in response
    
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
    
    // Calculate timeout based on file size (allow 1 minute per 100MB, minimum 5 minutes, maximum 2 hours)
    // Declare outside try-catch so it's accessible in error handling
    const timeoutMs = Math.max(5 * 60 * 1000, Math.min(2 * 60 * 60 * 1000, (file.size / (100 * 1024 * 1024)) * 60 * 1000));
    
    try {
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
          // Remove temp entry
          const withoutTemp = prev.filter(v => v.id !== tempId);
          
          // Check if video already exists (from WebSocket event)
          const exists = withoutTemp.some(v => v.id === res.data.id);
          if (exists) {
            // Update existing video instead of adding duplicate
            return withoutTemp.map(v => v.id === res.data.id ? res.data : v);
          }
          
          // Add new video
          return [...withoutTemp, res.data];
        });
        
        // Get tokens_required from backend response
        const tokensRequired = res.data.tokens_required || 0;
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
        } else if (err.response?.status === 400 && (errorMsg.includes('Insufficient tokens') || errorMsg.includes('Insufficient'))) {
          // Token limit error - show popup notification
          setNotification({
            type: 'error',
            title: 'Insufficient Tokens',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 15000);
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

  const clearUploadedVideos = async () => {
    // Filter only uploaded/completed videos
    const uploadedVideos = videos.filter(v => v.status === 'uploaded' || v.status === 'completed');
    
    if (uploadedVideos.length === 0) {
      setMessage('No uploaded videos to clear');
      return;
    }
    
    // Show confirmation dialog
    setConfirmDialog({
      title: 'Clear Uploaded Videos',
      message: `Are you sure you want to clear ${uploadedVideos.length} uploaded video(s) from the queue? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          const res = await axios.delete(`${API}/videos/uploaded`);
          setVideos(videos.filter(v => v.status !== 'uploaded' && v.status !== 'completed'));
          setMessage(`✅ Cleared ${res.data.deleted} uploaded video(s) from queue`);
        } catch (err) {
          const errorMsg = err.response?.data?.detail || err.message || 'Error clearing uploaded videos';
          setMessage(`❌ ${errorMsg}`);
          console.error('Error clearing uploaded videos:', err);
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
    setEditCommercialContentDisclosure(false);
    setEditCommercialContentYourBrand(false);
    setEditCommercialContentBranded(false);
    setEditTiktokPrivacy('');
  };

  const updateVideoSettings = async (videoId, settings) => {
    try {
      // Filter out null/undefined values but keep empty strings (for clearing values like scheduled_time)
      const filteredSettings = {};
      Object.entries(settings).forEach(([key, value]) => {
        if (value !== null && value !== undefined) {
          filteredSettings[key] = value;
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}`, filteredSettings);
      
      // Reload videos to get updated computed titles
      await loadVideos();
      
      setMessage('✅ Video settings updated');
      closeEditModal();
    } catch (err) {
      setMessage('❌ Error updating video');
      console.error('Error updating video:', err);
    }
  };

  // Reusable function for saving destination-specific overrides (DRY)
  const saveDestinationOverrides = async (videoId, platform, overrides) => {
    try {
      // Filter out null/undefined values
      const filteredOverrides = {};
      Object.entries(overrides).forEach(([key, value]) => {
        if (value !== null && value !== undefined) {
          filteredOverrides[key] = value;
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}`, filteredOverrides);
      
      // Reload videos to get updated data
      await loadVideos();
      
      setMessage(`✅ ${platform === 'youtube' ? 'YouTube' : platform === 'tiktok' ? 'TikTok' : 'Instagram'} overrides saved`);
      return true;
    } catch (err) {
      setMessage(`❌ Failed to save overrides: ${err.response?.data?.detail || err.message}`);
      console.error('Error saving destination overrides:', err);
      return false;
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

  const recomputeAllVideos = async (platform) => {
    try {
      const res = await axios.post(`${API}/videos/recompute-all/${platform}`);
      await loadVideos();
      const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);
      setMessage(`✅ Recomputed ${res.data.updated_count} ${platformName} video${res.data.updated_count !== 1 ? 's' : ''}`);
    } catch (err) {
      console.error(`Error recomputing ${platform} videos:`, err);
      const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);
      setMessage(`❌ Error recomputing ${platformName} videos`);
    }
  };

  const recomputeAllYouTube = () => recomputeAllVideos('youtube');
  const recomputeAllTiktok = () => recomputeAllVideos('tiktok');
  const recomputeAllInstagram = () => recomputeAllVideos('instagram');

  const recomputeVideoField = async (videoId, platform, field) => {
    try {
      // Recompute the specific field for this video
      // For now, we'll use the single video recompute endpoint
      // and then update the specific field in the override modal
      await axios.post(`${API}/videos/${videoId}/recompute-title?platform=${platform}`);
      
      // Reload videos to get updated values
      await loadVideos();
      
      // Update the override input value if modal is open
      const modalKey = `${videoId}-${platform}`;
      const videosRes = await axios.get(`${API}/videos`);
      const updatedVideo = videosRes.data.find(v => v.id === videoId);
      
      if (updatedVideo) {
        const newValue = field === 'title' 
          ? (platform === 'youtube' ? updatedVideo.youtube_title : updatedVideo.tiktok_title)
          : field === 'description'
          ? updatedVideo.youtube_description
          : field === 'tags'
          ? updatedVideo.youtube_tags
          : field === 'caption'
          ? updatedVideo.instagram_caption
          : null;
        
        if (newValue !== null) {
          setOverrideInputValues(prev => ({
            ...prev,
            [modalKey]: {
              ...(prev[modalKey] || {}),
            [platform === 'youtube' && field === 'title' ? 'youtube_title' : 
             field === 'title' || field === 'caption' ? 'title' : 
             field]: newValue
            }
          }));
        }
      }
      
      setMessage(`✅ ${field === 'title' ? 'Title' : field === 'description' ? 'Description' : field === 'tags' ? 'Tags' : 'Caption'} recomputed from template`);
    } catch (err) {
      console.error(`Error recomputing ${field}:`, err);
      setMessage(`❌ Error recomputing ${field}`);
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
    
    // Check commercial content disclosure validation
    if (tiktok.enabled && tiktokSettings.commercial_content_disclosure) {
      const hasYourBrand = tiktokSettings.commercial_content_your_brand ?? false;
      const hasBranded = tiktokSettings.commercial_content_branded ?? false;
      
      if (!hasYourBrand && !hasBranded) {
        setMessage('❌ You need to indicate if your content promotes yourself, a third party, or both.');
        return;
      }
    }
    
    if (!youtube.enabled && !tiktok.enabled && !instagram.enabled) {
      setMessage('❌ Enable at least one destination first');
      return;
    }
    
    // Check token balance before uploading
    // Only block free plan users - paid plans (starter/creator) allow overage
    if (tokenBalance && !tokenBalance.unlimited && subscription && subscription.plan_type && subscription.plan_type === 'free') {
      // Get pending videos (pending, failed, or uploading status)
      const pendingVideos = videos.filter(v => 
        v.status === 'pending' || v.status === 'failed' || v.status === 'uploading'
      );
      
      // Calculate total tokens required for all pending videos
      // Only count videos that haven't consumed tokens yet (tokens_consumed === 0)
      const totalTokensRequired = pendingVideos
        .filter(v => v.tokens_consumed === 0)
        .reduce((sum, video) => {
          return sum + (video.tokens_required || 0);
        }, 0);
      
      // Free plan has hard limit - block if not enough tokens
      // Paid plans (starter/creator) allow overage, so we don't block them here
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
    
    // WebSocket handles all upload status updates in real-time - no polling needed
    try {
      const res = await axios.post(`${API}/upload`);
      
      // Final refresh to get latest video statuses
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
      
      // Check if any videos were successfully uploaded to TikTok
      // TikTok upload is successful if video has tiktok_publish_id or tiktok_id in custom_settings
      // and the video status is 'uploaded' or TikTok platform status is 'uploaded'
      const hasSuccessfulTiktokUploads = videosRes.data.some(video => {
        const tiktokId = video.custom_settings?.tiktok_id;
        const tiktokPublishId = video.custom_settings?.tiktok_publish_id;
        const hasTiktokUpload = tiktokId || tiktokPublishId;
        const isUploaded = video.status === 'uploaded' || video.platform_statuses?.tiktok === 'uploaded';
        return hasTiktokUpload && isUploaded;
      });
      
      if (res.data.videos_uploaded !== undefined && res.data.videos_uploaded > 0) {
        if (res.data.videos_failed > 0) {
          setMessage(`⚠️ ${res.data.message || `Uploaded ${res.data.videos_uploaded} video(s), ${res.data.videos_failed} failed`}`);
        } else {
          setMessage(`✅ ${res.data.message || `Uploaded ${res.data.videos_uploaded} videos!`}`);
        }
        // Show notification for TikTok only if TikTok uploads actually succeeded
        if (tiktok.enabled && hasSuccessfulTiktokUploads) {
          setNotification({
            type: 'info',
            title: 'Content Processing',
            message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
          });
          setTimeout(() => setNotification(null), 15000);
        }
      } else if (res.data.videos_failed > 0) {
        setMessage(`❌ ${res.data.message || `Upload failed for ${res.data.videos_failed} video(s)`}`);
      } else if (res.data.scheduled !== undefined) {
        setMessage(`✅ ${res.data.scheduled} videos scheduled! ${res.data.message}`);
        // Don't show processing notification for scheduled uploads - they haven't been published yet
      } else {
        setMessage(`✅ ${res.data.message || 'Success'}`);
        // Only show notification if TikTok uploads actually succeeded
        if (tiktok.enabled && hasSuccessfulTiktokUploads) {
          setNotification({
            type: 'info',
            title: 'Content Processing',
            message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
          });
          setTimeout(() => setNotification(null), 15000);
        }
      }
    } catch (err) {
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
          className="notification-popup"
          style={{
            position: 'fixed',
            top: '20px',
            right: '20px',
            zIndex: 10000,
            minWidth: '350px',
            maxWidth: '500px',
            padding: '1.25rem',
            background: notification.type === 'error' 
              ? `linear-gradient(135deg, ${rgba(HOPPER_COLORS.rgb.error, 1.0)} 0%, ${rgba(HOPPER_COLORS.rgb.error, 0.9)} 100%)`
              : notification.type === 'info'
              ? `linear-gradient(135deg, ${rgba(HOPPER_COLORS.rgb.info, 1.0)} 0%, ${rgba(HOPPER_COLORS.rgb.info, 0.9)} 100%)`
              : `linear-gradient(135deg, ${rgba(HOPPER_COLORS.rgb.success, 1.0)} 0%, ${rgba(HOPPER_COLORS.rgb.success, 0.9)} 100%)`,
            border: notification.type === 'error'
              ? `2px solid ${HOPPER_COLORS.error}`
              : notification.type === 'info'
              ? `2px solid ${HOPPER_COLORS.info}`
              : `2px solid ${HOPPER_COLORS.success}`,
            borderRadius: '12px',
            boxShadow: `0 10px 40px ${rgba(HOPPER_COLORS.rgb.black, 0.3)}`,
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
                {notification.type === 'error' ? '⚠️' : notification.type === 'info' ? 'ℹ️' : '✅'}
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
                background: rgba(HOPPER_COLORS.rgb.white, 0.2),
                border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.3)}`,
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
                e.target.style.background = rgba(HOPPER_COLORS.rgb.white, 0.3);
              }}
              onMouseLeave={(e) => {
                e.target.style.background = rgba(HOPPER_COLORS.rgb.white, 0.2);
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
                background: rgba(HOPPER_COLORS.rgb.white, 0.2),
                border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.4)}`,
                borderRadius: '8px',
                color: 'white',
                cursor: 'pointer',
                fontSize: '0.95rem',
                fontWeight: '600',
                transition: 'all 0.2s',
                width: '100%'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = rgba(HOPPER_COLORS.rgb.white, 0.3);
                e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.white, 0.6);
              }}
              onMouseLeave={(e) => {
                e.target.style.background = rgba(HOPPER_COLORS.rgb.white, 0.2);
                e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.white, 0.4);
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
            backgroundColor: 'var(--bg-overlay)',
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
            className="confirm-dialog"
            style={{
              background: `linear-gradient(135deg, rgba(${HOPPER_COLORS.rgb.black}, 0.98) 0%, rgba(${HOPPER_COLORS.rgb.black}, 0.98) 100%)`,
              border: `2px solid ${rgba(HOPPER_COLORS.rgb.error, 0.5)}`,
              borderRadius: '16px',
              padding: '2rem',
              minWidth: '400px',
              maxWidth: '500px',
              boxShadow: `0 20px 60px ${rgba(HOPPER_COLORS.rgb.black, 0.5)}`,
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
                  background: rgba(HOPPER_COLORS.rgb.grey, 0.2),
                  border: `1px solid ${rgba(HOPPER_COLORS.rgb.grey, 0.4)}`,
                  borderRadius: '8px',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '1rem',
                  fontWeight: '600',
                  transition: 'all 0.2s'
                }}
                onMouseEnter={(e) => {
                  e.target.style.background = rgba(HOPPER_COLORS.rgb.grey, 0.3);
                  e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.grey, 0.6);
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = rgba(HOPPER_COLORS.rgb.grey, 0.2);
                  e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.grey, 0.4);
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDialog.onConfirm}
                style={{
                  padding: '0.75rem 1.5rem',
                  background: `linear-gradient(135deg, ${rgba(HOPPER_COLORS.rgb.error, 1.0)} 0%, ${rgba(HOPPER_COLORS.rgb.error, 0.9)} 100%)`,
                  border: `1px solid ${HOPPER_COLORS.error}`,
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
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      
      <div className="app-header">
        <h1 className="app-title">{appTitle}</h1>
        <div className="app-header-right">
          {/* Admin Dashboard Link */}
          {isAdmin && (
            <Link
              to="/admin"
              className="admin-button-link"
              style={{
                padding: '0.5rem 1rem',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '20px',
                color: '#ef4444',
                textDecoration: 'none',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.25)';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <span>🔐</span>
              <span>Admin</span>
            </Link>
          )}
          {/* Token Balance Indicator - always rendered, shows loading state if not yet loaded */}
          <div 
              className="token-balance-indicator"
              style={{
                padding: '0.4rem 0.8rem',
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
              <CircularTokenProgress
                tokensRemaining={tokenBalance?.tokens_remaining}
                tokensUsed={tokenBalance?.tokens_used_this_period || 0}
                monthlyTokens={tokenBalance?.monthly_tokens || 0}
                overageTokens={tokenBalance?.overage_tokens || 0}
                unlimited={tokenBalance?.unlimited || false}
                isLoading={!tokenBalance}
              />
          </div>
          
          <span className="user-email" style={{ color: HOPPER_COLORS.grey, fontSize: '0.9rem' }}>
            {user.email}
          </span>
          <button 
            className="settings-button"
            onClick={() => setShowAccountSettings(true)}
            style={{
              padding: '0.5rem',
              background: 'transparent',
              border: '1px solid #ddd',
              borderRadius: '4px',
              color: HOPPER_COLORS.grey,
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
      
      {/* Global Settings - Collapsible, no + button */}
      <div className="card">
        <button 
          className="global-settings-button"
          onClick={() => setShowGlobalSettings(!showGlobalSettings)}
          type="button"
        >
          ⚙️ Global Settings {showGlobalSettings ? '▼' : '▶'}
        </button>
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
                  <label className="checkbox-label">
                    <input 
                      type="checkbox"
                      checked={globalSettings.upload_first_immediately !== false}
                      onChange={(e) => updateGlobalSettings('upload_first_immediately', e.target.checked)}
                      className="checkbox"
                    />
                    <span>
                      Upload first video immediately
                      <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">
                          When checked, the first video uploads immediately and subsequent videos are spaced by the interval.
                          When unchecked, all videos (including the first) are spaced evenly by the interval.
                        </span>
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
              <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
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
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {youtube.connected && !youtube.token_expired && youtube.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
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
                  disabled={youtube.token_expired}
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
              <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
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
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {tiktok.connected && !tiktok.token_expired && tiktok.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
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
                  disabled={tiktok.token_expired}
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
                value={tiktokSettings.privacy_level || ''}
                onChange={(e) => updateTiktokSettings('privacy_level', e.target.value || null)}
                className="select"
                required
                title={
                  tiktokSettings.commercial_content_disclosure && 
                  tiktokSettings.commercial_content_branded && 
                  tiktokSettings.privacy_level === 'SELF_ONLY'
                    ? "Branded content visibility cannot be set to private."
                    : undefined
                }
              >
                <option value="">-- Select Privacy Level --</option>
                {Array.isArray(tiktokCreatorInfo?.privacy_level_options) ? tiktokCreatorInfo.privacy_level_options.map(option => {
                  const labelMap = {
                    'PUBLIC_TO_EVERYONE': 'Everyone',
                    'MUTUAL_FOLLOW_FRIENDS': 'Friends',
                    'FOLLOWER_OF_CREATOR': 'Followers',
                    'SELF_ONLY': 'Only you'
                  };
                  const isPrivate = option === 'SELF_ONLY';
                  const brandedContentSelected = tiktokSettings.commercial_content_disclosure && tiktokSettings.commercial_content_branded;
                  const isDisabled = isPrivate && brandedContentSelected;
                  
                  return (
                    <option 
                      key={option} 
                      value={option}
                      disabled={isDisabled}
                      title={isDisabled ? "Branded content visibility cannot be set to private." : undefined}
                    >
                      {labelMap[option] || option}
                    </option>
                  );
                }) : null}
              </select>
              {tiktokSettings.commercial_content_disclosure && tiktokSettings.commercial_content_branded && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#f59e0b' }}>
                  ⚠️ Branded content requires public or friends visibility
                </div>
              )}
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_comments ?? false}
                  onChange={(e) => updateTiktokSettings('allow_comments', e.target.checked)}
                  className="checkbox"
                  disabled={tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled}
                />
                <span style={{ 
                  opacity: (tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled) ? 0.5 : 1 
                }}>
                  Allow Comments
                </span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_duet ?? false}
                  onChange={(e) => updateTiktokSettings('allow_duet', e.target.checked)}
                  className="checkbox"
                  disabled={tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled}
                />
                <span style={{ 
                  opacity: (tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled) ? 0.5 : 1 
                }}>
                  Allow Duet
                </span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_stitch ?? false}
                  onChange={(e) => updateTiktokSettings('allow_stitch', e.target.checked)}
                  className="checkbox"
                  disabled={tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled}
                />
                <span style={{ 
                  opacity: (tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled) ? 0.5 : 1 
                }}>
                  Allow Stitch
                </span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.commercial_content_disclosure ?? false}
                  onChange={(e) => {
                    const newValue = e.target.checked;
                    setTiktokSettings({...tiktokSettings, commercial_content_disclosure: newValue});
                    updateTiktokSettings('commercial_content_disclosure', newValue);
                    // Reset checkboxes when toggle is turned off
                    if (!newValue) {
                      setTiktokSettings(prev => ({...prev, commercial_content_your_brand: false, commercial_content_branded: false}));
                      updateTiktokSettings('commercial_content_your_brand', false);
                      updateTiktokSettings('commercial_content_branded', false);
                    }
                  }}
                  className="checkbox"
                />
                <span>Content Disclosure</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Indicate whether this content promotes yourself, a brand, product or service</span>
                </span>
              </label>
            </div>

            {tiktokSettings.commercial_content_disclosure && (
              <>
                <div className="setting-group" style={{ marginLeft: '1.5rem' }}>
                  <label className="checkbox-label">
                    <input 
                      type="checkbox"
                      checked={tiktokSettings.commercial_content_your_brand ?? false}
                      onChange={(e) => {
                        const newValue = e.target.checked;
                        setTiktokSettings({...tiktokSettings, commercial_content_your_brand: newValue});
                        updateTiktokSettings('commercial_content_your_brand', newValue);
                      }}
                      className="checkbox"
                    />
                    <span>Your Brand</span>
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">You are promoting yourself or your own business. This content will be classified as Brand Organic.</span>
                    </span>
                  </label>
                </div>

                <div className="setting-group" style={{ marginLeft: '1.5rem' }}>
                  <label className="checkbox-label">
                    <input 
                      type="checkbox"
                      checked={tiktokSettings.commercial_content_branded ?? false}
                      onChange={(e) => {
                        const newValue = e.target.checked;
                        setTiktokSettings({...tiktokSettings, commercial_content_branded: newValue});
                        updateTiktokSettings('commercial_content_branded', newValue);
                      }}
                      className="checkbox"
                      disabled={tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded}
                    />
                    <span style={{
                      opacity: (tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded) ? 0.5 : 1
                    }}>
                      Branded Content
                    </span>
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">
                        {tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded
                          ? "Branded content visibility cannot be set to private. Please change privacy level to public or friends first."
                          : "You are promoting another brand or a third party. This content will be classified as Branded Content."}
                      </span>
                    </span>
                  </label>
                </div>

                {/* Show appropriate prompt based on selection */}
                {tiktokSettings.commercial_content_your_brand || tiktokSettings.commercial_content_branded ? (
                  <div className="setting-group" style={{ marginLeft: '1.5rem', marginTop: '0.5rem' }}>
                    <div style={{
                      padding: '0.75rem',
                      background: 'rgba(59, 130, 246, 0.1)',
                      border: '1px solid rgba(59, 130, 246, 0.3)',
                      borderRadius: '6px',
                      fontSize: '0.85rem',
                      color: '#3b82f6'
                    }}>
                      {tiktokSettings.commercial_content_your_brand && tiktokSettings.commercial_content_branded
                        ? "Your photo/video will be labeled as 'Paid partnership'"
                        : tiktokSettings.commercial_content_branded
                        ? "Your photo/video will be labeled as 'Paid partnership'"
                        : "Your photo/video will be labeled as 'Promotional content'"
                      }
                    </div>
                  </div>
                ) : null}
              </>
            )}

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
              <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
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
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
                ⚠️ Token expired - reconnect required
              </span>
            )}
            {instagram.connected && !instagram.token_expired && instagram.token_expires_soon && (
              <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
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
                  disabled={instagram.token_expired}
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
                Media Type
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Choose whether to post as a Reel or regular Video feed post</span>
                </span>
              </label>
              <select
                value={instagramSettings.media_type || 'REELS'}
                onChange={(e) => updateInstagramSettings('media_type', e.target.value)}
                className="select"
              >
                <option value="REELS">Reels</option>
                <option value="VIDEO">Video (Feed Post)</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={instagramSettings.share_to_feed ?? true}
                  onChange={(e) => updateInstagramSettings('share_to_feed', e.target.checked)}
                  className="checkbox"
                  disabled={instagramSettings.media_type !== 'REELS'}
                />
                <span>Share Reel to Feed</span>
                <span className="tooltip-wrapper" style={{ marginLeft: '8px' }}>
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">When enabled, your Reel will also appear in your feed (only applies to Reels)</span>
                </span>
              </label>
            </div>

            <div className="setting-group">
              <label>
                Cover Image URL (Optional)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">URL to a custom thumbnail image for your video</span>
                </span>
              </label>
              <input 
                type="text"
                value={instagramSettings.cover_url || ''}
                onChange={(e) => setInstagramSettings({...instagramSettings, cover_url: e.target.value})}
                onBlur={(e) => updateInstagramSettings('cover_url', e.target.value)}
                placeholder="https://example.com/image.jpg (optional)"
                className="input-text"
              />
            </div>

            {/* Commented out - removed Audio Name feature
            <div className="setting-group">
              <label>
                Audio Name (Optional, Reels only)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Name of the audio track for your Reel</span>
                </span>
              </label>
              <input 
                type="text"
                value={instagramSettings.audio_name || ''}
                onChange={(e) => setInstagramSettings({...instagramSettings, audio_name: e.target.value})}
                onBlur={(e) => updateInstagramSettings('audio_name', e.target.value)}
                placeholder="Audio track name (optional)"
                className="input-text"
                disabled={instagramSettings.media_type !== 'REELS'}
              />
            </div>
            */}

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
          {/* TikTok Compliance Declaration */}
          {tiktok.enabled && (() => {
            // Determine the declaration message based on commercial content selection
            const commercialContentOn = tiktokSettings.commercial_content_disclosure ?? false;
            const hasYourBrand = commercialContentOn && (tiktokSettings.commercial_content_your_brand ?? false);
            const hasBrandedContent = commercialContentOn && (tiktokSettings.commercial_content_branded ?? false);
            
            const musicUsageUrl = 'https://www.tiktok.com/legal/page/global/music-usage-confirmation/en';
            const brandedContentUrl = 'https://www.tiktok.com/legal/page/global/bc-policy/en';
            
            let declarationContent = (
              <>
                By posting, you agree to TikTok's{' '}
                <a 
                  href={musicUsageUrl} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  style={{ 
                    color: '#3b82f6', 
                    textDecoration: 'underline',
                    fontWeight: '500'
                  }}
                >
                  Music Usage Confirmation
                </a>
              </>
            );
            
            if (commercialContentOn) {
              if (hasBrandedContent) {
                // Branded Content is checked (alone or with Your Brand) - include Branded Content Policy
                declarationContent = (
                  <>
                    By posting, you agree to TikTok's{' '}
                    <a 
                      href={brandedContentUrl} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      style={{ 
                        color: '#3b82f6', 
                        textDecoration: 'underline',
                        fontWeight: '500'
                      }}
                    >
                      Branded Content Policy
                    </a>
                    {' '}and{' '}
                    <a 
                      href={musicUsageUrl} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      style={{ 
                        color: '#3b82f6', 
                        textDecoration: 'underline',
                        fontWeight: '500'
                      }}
                    >
                      Music Usage Confirmation
                    </a>
                  </>
                );
              } else if (hasYourBrand) {
                // Only "Your Brand" is checked - just Music Usage Confirmation
                declarationContent = (
                  <>
                    By posting, you agree to TikTok's{' '}
                    <a 
                      href={musicUsageUrl} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      style={{ 
                        color: '#3b82f6', 
                        textDecoration: 'underline',
                        fontWeight: '500'
                      }}
                    >
                      Music Usage Confirmation
                    </a>
                  </>
                );
              }
            }
            
            return (
              <div style={{
                padding: '0.75rem 1rem',
                background: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                borderRadius: '6px',
                marginBottom: '1rem',
                fontSize: '0.9rem',
                color: '#3b82f6',
                textAlign: 'center'
              }}>
                {declarationContent}
              </div>
            );
          })()}
          
          <button 
            className="upload-btn" 
            onClick={upload} 
            disabled={
              isUploading || 
              (tiktok.enabled && 
               tiktokSettings.commercial_content_disclosure && 
               !(tiktokSettings.commercial_content_your_brand || tiktokSettings.commercial_content_branded))
            }
            title={
              tiktok.enabled && 
              tiktokSettings.commercial_content_disclosure && 
              !(tiktokSettings.commercial_content_your_brand || tiktokSettings.commercial_content_branded)
                ? "You need to indicate if your content promotes yourself, a third party, or both."
                : undefined
            }
            style={{
              cursor: (
                tiktok.enabled && 
                tiktokSettings.commercial_content_disclosure && 
                !(tiktokSettings.commercial_content_your_brand || tiktokSettings.commercial_content_branded)
              ) ? 'not-allowed' : undefined
            }}
          >
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
          <p style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginTop: '0.5rem' }}>
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
        <div className="queue-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            Queue ({videos.length})
            <span style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              padding: '0.5rem 0.75rem',
              background: 'rgba(99, 102, 241, 0.15)',
              border: '1px solid rgba(99, 102, 241, 0.3)',
              borderRadius: '6px',
              fontSize: '0.75rem',
              color: HOPPER_COLORS.grey,
              fontWeight: '500',
              height: '32px',
              minWidth: '32px',
              boxSizing: 'border-box'
            }}>
              🪙 {calculateQueueTokenCost()}
            </span>
          </h2>
          <div className="queue-buttons" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {videos.length > 0 && videos.some(v => v.status === 'uploaded' || v.status === 'completed') && (
              <button
                onClick={clearUploadedVideos}
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
                Clear Uploaded
              </button>
            )}
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
                onDragOver={handleDragOver}
                onDrop={(e) => handleDrop(e, v)}
              >
                <div 
                  className="drag-handle" 
                  title="Drag to reorder"
                  draggable={v.status !== 'uploading'}
                  onDragStart={(e) => handleDragStart(e, v)}
                  onDragEnd={handleDragEnd}
                >⋮⋮</div>
                <div className="video-info-container">
                  <div className="video-titles">
                    <div className="youtube-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }}>
                        <path d="M8 5v14l11-7z" fill="currentColor"/>
                      </svg>
                      <span style={flexTextStyle}>
                        {(() => {
                          // Configuration-driven title display (DRY, extensible)
                          const platforms = [
                            { name: 'youtube', state: youtube },
                            { name: 'tiktok', state: tiktok },
                            { name: 'instagram', state: instagram },
                          ];
                          
                          // Find first enabled platform with a title
                          for (const { name, state } of platforms) {
                            if (state.enabled) {
                              const titleField = PLATFORM_CONFIG[name].titleField;
                              const title = v[titleField];
                              if (title) {
                                return title;
                              }
                            }
                          }
                          
                          // Fallback to filename
                          return v.filename;
                        })()}
                        {v.title_too_long && (
                          <span className="title-warning" title={`Title truncated from ${v.title_original_length} to 100 characters`}>
                            ⚠️ {v.title_original_length}
                          </span>
                        )}
                      </span>
                    </div>
                    {/* Platform Status Indicators - Clickable Buttons */}
                    {v.platform_statuses && (
                      <div className="platform-status-buttons" style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: '6px', 
                        marginTop: '4px',
                        flexWrap: 'wrap'
                      }}>
                        {Object.entries(v.platform_statuses).map(([platform, statusData]) => {
                          // Handle new format: statusData is now {status: "...", error: "..."}
                          const status = typeof statusData === 'object' ? statusData.status : statusData;
                          
                          // ROOT CAUSE FIX: Backend is source of truth - only check platform_statuses
                          // Don't check separate youtube/tiktok/instagram state to avoid race conditions
                          // The video's platform_statuses already contains the correct enabled/disabled state
                          if (status === 'not_enabled') return null;
                          
                          const platformNames = {
                            youtube: 'YouTube',
                            tiktok: 'TikTok',
                            instagram: 'Instagram'
                          };
                          
                          // Get SVG icon for platform
                          let platformIcon;
                          if (platform === 'youtube') {
                            platformIcon = (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill="#FF0000"/>
                              </svg>
                            );
                          } else if (platform === 'tiktok') {
                            platformIcon = (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" fill="#FFFFFF"/>
                              </svg>
                            );
                          } else if (platform === 'instagram') {
                            platformIcon = (
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" fill="#E4405F"/>
                              </svg>
                            );
                          }
                          
                          // Determine border color based on status using design system colors
                          let borderColor, backgroundColor, boxShadow, title;
                          if (status === 'success') {
                            borderColor = HOPPER_COLORS.success;
                            backgroundColor = rgba(HOPPER_COLORS.rgb.success, 0.1);
                            boxShadow = `0 0 8px ${rgba(HOPPER_COLORS.rgb.success, 0.4)}`;
                            title = `${platformNames[platform]}: Upload successful - Click to view/edit`;
                          } else if (status === 'failed') {
                            borderColor = HOPPER_COLORS.error;
                            backgroundColor = rgba(HOPPER_COLORS.rgb.error, 0.1);
                            boxShadow = `0 0 8px ${rgba(HOPPER_COLORS.rgb.error, 0.4)}`;
                            title = `${platformNames[platform]}: Upload failed - Click to view errors/edit`;
                          } else {
                            // Pending
                            borderColor = rgba(HOPPER_COLORS.rgb.white, 0.2);
                            backgroundColor = rgba(HOPPER_COLORS.rgb.white, 0.05);
                            boxShadow = 'none';
                            title = `${platformNames[platform]}: Will upload to this platform - Click to configure`;
                          }
                          
                          return (
                            <button
                              key={platform}
                              className="destination-status-button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDestinationModal({ videoId: v.id, platform, video: v });
                              }}
                              title={title}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                padding: '4px 6px',
                                border: `2px solid ${borderColor}`,
                                borderRadius: '6px',
                                background: backgroundColor,
                                cursor: 'pointer',
                                transition: 'all 0.2s ease',
                                opacity: status === 'pending' ? 0.7 : 1,
                                minWidth: '32px',
                                height: '28px',
                                boxShadow: boxShadow
                              }}
                              onMouseEnter={(e) => {
                                if (status === 'pending') {
                                  e.currentTarget.style.opacity = '1';
                                  e.currentTarget.style.borderColor = rgba(HOPPER_COLORS.rgb.info, 0.5);
                                } else {
                                  e.currentTarget.style.transform = 'scale(1.05)';
                                }
                              }}
                              onMouseLeave={(e) => {
                                if (status === 'pending') {
                                  e.currentTarget.style.opacity = '0.7';
                                  e.currentTarget.style.borderColor = rgba(HOPPER_COLORS.rgb.white, 0.2);
                                } else {
                                  e.currentTarget.style.transform = 'scale(1)';
                                }
                              }}
                            >
                              {platformIcon}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  {/* TikTok Publish Status */}
                  {v.tiktok_publish_status && (
                    <div style={{
                      marginTop: '6px',
                      fontSize: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      <span style={{ color: HOPPER_COLORS.grey, flexShrink: 0 }}>TikTok:</span>
                      <span style={flexTextStyle}>
                        {v.tiktok_publish_status === 'PUBLISHED' && (
                          <span style={{ 
                            color: '#22c55e',
                            fontWeight: '500'
                          }}>Published</span>
                        )}
                        {v.tiktok_publish_status === 'PROCESSING' && (
                          <span style={{ 
                            color: HOPPER_COLORS.warning,
                            fontWeight: '500'
                          }}>Processing...</span>
                        )}
                        {v.tiktok_publish_status === 'FAILED' && (
                          <span style={{ 
                            color: HOPPER_COLORS.error,
                            fontWeight: '500'
                          }}>Failed</span>
                        )}
                        {!['PUBLISHED', 'PROCESSING', 'FAILED'].includes(v.tiktok_publish_status) && (
                          <span style={{ 
                            color: HOPPER_COLORS.grey,
                            fontWeight: '500'
                          }}>{v.tiktok_publish_status}</span>
                        )}
                        {v.tiktok_publish_error && (
                          <span style={{ 
                            color: HOPPER_COLORS.error,
                            fontSize: '0.7rem',
                            marginLeft: '4px'
                          }} title={v.tiktok_publish_error}>({v.tiktok_publish_error})</span>
                        )}
                      </span>
                    </div>
                  )}
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
                  {/* Status at bottom left */}
                  <div className="status">
                    <span style={flexTextStyle}>
                      {v.status === 'uploading' ? (
                        v.upload_progress !== undefined ? (
                          <span>Uploading {v.upload_progress}%</span>
                        ) : v.progress !== undefined && v.progress < 100 ? (
                          <span>Uploading to server {v.progress}%</span>
                        ) : (
                          <span>Processing...</span>
                        )
                      ) : v.status === 'failed' ? (
                        <span style={{ color: HOPPER_COLORS.error }}>Upload Failed</span>
                      ) : v.scheduled_time ? (
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
                    </span>
                  </div>
                  {isExpanded && (
                    <div className="video-expanded-details">
                      {/* File Info Section */}
                      <div className="video-detail-section">
                        <div className="video-detail-label">File Information</div>
                        <div className="video-detail-content">
                          <div className="video-detail-row">
                            <span className="video-detail-key">Filename:</span>
                            <span className="video-detail-value">{v.filename}</span>
                          </div>
                          {v.file_size_bytes && (
                            <>
                              <div className="video-detail-row">
                                <span className="video-detail-key">File Size:</span>
                                <span className="video-detail-value">{formatFileSize(v.file_size_bytes)}</span>
                              </div>
                              <div className="video-detail-row">
                                <span className="video-detail-key">Tokens:</span>
                                <span className="video-detail-value video-detail-tokens">{v.tokens_consumed || v.tokens_required || 0}</span>
                              </div>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Upload Properties Section */}
                      {(youtubeProps.title || uploadProps.tiktok || uploadProps.instagram) && (
                        <div className="video-detail-section">
                          <div className="video-detail-label">Upload Properties</div>
                          <div className="video-detail-content">
                            {youtubeProps.title && (
                              <div className="video-detail-platform">
                                <div className="video-detail-platform-name">YouTube</div>
                                <div className="video-detail-platform-props">
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Title:</span>
                                    <span className="video-detail-value">{youtubeProps.title}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Visibility:</span>
                                    <span className="video-detail-value">{youtubeProps.visibility}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Made for Kids:</span>
                                    <span className="video-detail-value">{youtubeProps.made_for_kids ? 'Yes' : 'No'}</span>
                                  </div>
                                  {youtubeProps.description && (
                                    <div className="video-detail-row">
                                      <span className="video-detail-key">Description:</span>
                                      <span className="video-detail-value">{youtubeProps.description.substring(0, 100)}{youtubeProps.description.length > 100 ? '...' : ''}</span>
                                    </div>
                                  )}
                                  {youtubeProps.tags && (
                                    <div className="video-detail-row">
                                      <span className="video-detail-key">Tags:</span>
                                      <span className="video-detail-value">{youtubeProps.tags}</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                            {uploadProps.tiktok && (
                              <div className="video-detail-platform">
                                <div className="video-detail-platform-name">TikTok</div>
                                <div className="video-detail-platform-props">
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Title:</span>
                                    <span className="video-detail-value">{uploadProps.tiktok.title}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Privacy:</span>
                                    <span className="video-detail-value">
                                      {uploadProps.tiktok.privacy_level === 'private' ? 'Only Me' :
                                       uploadProps.tiktok.privacy_level === 'friends' ? 'Friends' :
                                       uploadProps.tiktok.privacy_level === 'public' ? 'Followers' :
                                       uploadProps.tiktok.privacy_level}
                                    </span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Allow Comments:</span>
                                    <span className="video-detail-value">{uploadProps.tiktok.allow_comments ? 'Yes' : 'No'}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Allow Duet:</span>
                                    <span className="video-detail-value">{uploadProps.tiktok.allow_duet ? 'Yes' : 'No'}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Allow Stitch:</span>
                                    <span className="video-detail-value">{uploadProps.tiktok.allow_stitch ? 'Yes' : 'No'}</span>
                                  </div>
                                </div>
                              </div>
                            )}
                            {uploadProps.instagram && (
                              <div className="video-detail-platform">
                                <div className="video-detail-platform-name">Instagram</div>
                                <div className="video-detail-platform-props">
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Caption:</span>
                                    <span className="video-detail-value">{uploadProps.instagram.caption}</span>
                                  </div>
                                  {uploadProps.instagram.location_id && (
                                    <div className="video-detail-row">
                                      <span className="video-detail-key">Location ID:</span>
                                      <span className="video-detail-value">{uploadProps.instagram.location_id}</span>
                                    </div>
                                  )}
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Disable Comments:</span>
                                    <span className="video-detail-value">{uploadProps.instagram.disable_comments ? 'Yes' : 'No'}</span>
                                  </div>
                                  <div className="video-detail-row">
                                    <span className="video-detail-key">Disable Likes:</span>
                                    <span className="video-detail-value">{uploadProps.instagram.disable_likes ? 'Yes' : 'No'}</span>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div className="video-actions">
                  {v.status === 'failed' && (
                    <button 
                      onClick={async () => {
                        try {
                          await axios.post(`${API}/videos/${v.id}/retry`);
                          setMessage('🔄 Retrying upload...');
                          // Refresh videos to show updated status
                          loadVideos();
                        } catch (err) {
                          setMessage(`❌ ${err.response?.data?.detail || err.message || 'Failed to retry upload'}`);
                        }
                      }}
                      className="retry-upload-btn"
                      title="Retry failed upload"
                      style={{
                        height: '32px',
                        minWidth: '32px',
                        padding: '0.5rem 0.75rem',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxSizing: 'border-box'
                      }}
                    >
                      🔄 Retry
                    </button>
                  )}
                  {/* Token amount */}
                  {v.file_size_bytes && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '4px',
                      padding: '0.5rem 0.75rem',
                      background: 'rgba(99, 102, 241, 0.15)',
                      border: '1px solid rgba(99, 102, 241, 0.3)',
                      borderRadius: '6px',
                      fontSize: '0.75rem',
                      color: HOPPER_COLORS.grey,
                      fontWeight: '500',
                      height: '32px',
                      minWidth: '32px',
                      boxSizing: 'border-box'
                    }}>
                      🪙 {v.tokens_consumed || v.tokens_required || 0}
                    </div>
                  )}
                  <button 
                    onClick={() => removeVideo(v.id)} 
                    disabled={v.status === 'uploading'}
                    style={{
                      height: '32px',
                      minWidth: '32px',
                      width: '32px',
                      padding: '0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '1.25rem',
                      lineHeight: '1',
                      background: 'rgba(239, 68, 68, 0.1)',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      borderRadius: '6px',
                      color: '#ef4444',
                      cursor: v.status === 'uploading' ? 'not-allowed' : 'pointer',
                      transition: 'all 0.2s',
                      boxSizing: 'border-box'
                    }}
                    onMouseEnter={(e) => {
                      if (v.status !== 'uploading') {
                        e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                        e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (v.status !== 'uploading') {
                        e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                        e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
                      }
                    }}
                    title="Delete video"
                  >
                    ×
                  </button>
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
              
              {/* TikTok Settings */}
              {tiktok.enabled && tiktok.connected && (
                <>
                  <div className="form-group">
                    <label>TikTok Privacy Level</label>
                    <select 
                      value={editTiktokPrivacy}
                      id="edit-tiktok-privacy"
                      className="select"
                      required
                      onChange={(e) => setEditTiktokPrivacy(e.target.value)}
                      title={
                        editCommercialContentDisclosure && 
                        editCommercialContentBranded && 
                        editTiktokPrivacy === 'SELF_ONLY'
                          ? "Branded content visibility cannot be set to private."
                          : undefined
                      }
                    >
                      <option value="">-- Select Privacy Level --</option>
                      {Array.isArray(tiktokCreatorInfo?.privacy_level_options) ? tiktokCreatorInfo.privacy_level_options.map(option => {
                        const labelMap = {
                          'PUBLIC_TO_EVERYONE': 'Everyone',
                          'MUTUAL_FOLLOW_FRIENDS': 'Friends',
                          'FOLLOWER_OF_CREATOR': 'Followers',
                          'SELF_ONLY': 'Only you'
                        };
                        const isPrivate = option === 'SELF_ONLY';
                        const brandedContentSelected = editCommercialContentDisclosure && editCommercialContentBranded;
                        const isDisabled = isPrivate && brandedContentSelected;
                        
                        return (
                          <option 
                            key={option} 
                            value={option}
                            disabled={isDisabled}
                            title={isDisabled ? "Branded content visibility cannot be set to private." : undefined}
                          >
                            {labelMap[option] || option}
                          </option>
                        );
                      }) : null}
                    </select>
                    {editCommercialContentDisclosure && editCommercialContentBranded && (
                      <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#f59e0b' }}>
                        ⚠️ Branded content requires public or friends visibility
                      </div>
                    )}
                  </div>
                  
                  <div className="form-group">
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        defaultChecked={editingVideo.custom_settings?.allow_comments ?? false}
                        id="edit-tiktok-allow-comments"
                        className="checkbox"
                        disabled={tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled}
                      />
                      <span style={{ 
                        opacity: (tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled) ? 0.5 : 1 
                      }}>
                        Allow Comments
                      </span>
                    </label>
                  </div>
                  
                  <div className="form-group">
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        defaultChecked={editingVideo.custom_settings?.allow_duet ?? false}
                        id="edit-tiktok-allow-duet"
                        className="checkbox"
                        disabled={tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled}
                      />
                      <span style={{ 
                        opacity: (tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled) ? 0.5 : 1 
                      }}>
                        Allow Duet
                      </span>
                    </label>
                  </div>
                  
                  <div className="form-group">
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        defaultChecked={editingVideo.custom_settings?.allow_stitch ?? false}
                        id="edit-tiktok-allow-stitch"
                        className="checkbox"
                        disabled={tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled}
                      />
                      <span style={{ 
                        opacity: (tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled) ? 0.5 : 1 
                      }}>
                        Allow Stitch
                      </span>
                    </label>
                  </div>
                  
                  <div className="form-group">
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        checked={editCommercialContentDisclosure}
                        id="edit-tiktok-commercial-content-disclosure"
                        className="checkbox"
                        onChange={(e) => {
                          const newValue = e.target.checked;
                          setEditCommercialContentDisclosure(newValue);
                          if (!newValue) {
                            // Reset checkboxes when toggle is turned off
                            setEditCommercialContentYourBrand(false);
                            setEditCommercialContentBranded(false);
                          }
                        }}
                      />
                      <span>Content Disclosure</span>
                    </label>
                  </div>
                  
                  {editCommercialContentDisclosure && (
                    <>
                      <div className="form-group" style={{ marginLeft: '1.5rem' }}>
                        <label className="checkbox-label">
                          <input 
                            type="checkbox"
                            checked={editCommercialContentYourBrand}
                            id="edit-tiktok-commercial-content-your-brand"
                            className="checkbox"
                            onChange={(e) => setEditCommercialContentYourBrand(e.target.checked)}
                          />
                          <span>Your Brand</span>
                        </label>
                      </div>
                      
                      <div className="form-group" style={{ marginLeft: '1.5rem' }}>
                        <label className="checkbox-label">
                          <input 
                            type="checkbox"
                            checked={editCommercialContentBranded}
                            id="edit-tiktok-commercial-content-branded"
                            className="checkbox"
                            onChange={(e) => setEditCommercialContentBranded(e.target.checked)}
                            disabled={editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded}
                          />
                          <span style={{
                            opacity: (editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded) ? 0.5 : 1
                          }}>
                            Branded Content
                          </span>
                          <span className="tooltip-wrapper">
                            <span className="tooltip-icon">i</span>
                            <span className="tooltip-text">
                              {editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded
                                ? "Branded content visibility cannot be set to private. Please change privacy level to public or friends first."
                                : "You are promoting another brand or a third party. This content will be classified as Branded Content."}
                            </span>
                          </span>
                        </label>
                      </div>
                      
                      {(editCommercialContentYourBrand || editCommercialContentBranded) && (
                        <div className="form-group" style={{ marginLeft: '1.5rem', marginTop: '0.5rem' }}>
                          <div style={{
                            padding: '0.75rem',
                            background: 'rgba(59, 130, 246, 0.1)',
                            border: '1px solid rgba(59, 130, 246, 0.3)',
                            borderRadius: '6px',
                            fontSize: '0.85rem',
                            color: '#3b82f6'
                          }}>
                            {editCommercialContentYourBrand && editCommercialContentBranded
                              ? "Your photo/video will be labeled as 'Paid partnership'"
                              : editCommercialContentBranded
                              ? "Your photo/video will be labeled as 'Paid partnership'"
                              : "Your photo/video will be labeled as 'Promotional content'"
                            }
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
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
                  
                  const settings = {
                    title: title || null,
                    description: description || null,
                    tags: tags || null,
                    visibility,
                    made_for_kids: madeForKids,
                    scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : ''
                  };
                  
                  // Add TikTok settings if TikTok is enabled and connected
                  if (tiktok.enabled && tiktok.connected) {
                    const tiktokPrivacy = editTiktokPrivacy || document.getElementById('edit-tiktok-privacy')?.value;
                    const tiktokAllowComments = document.getElementById('edit-tiktok-allow-comments').checked;
                    const tiktokAllowDuet = document.getElementById('edit-tiktok-allow-duet').checked;
                    const tiktokAllowStitch = document.getElementById('edit-tiktok-allow-stitch').checked;
                    const tiktokCommercialContentDisclosure = editCommercialContentDisclosure;
                    const tiktokCommercialContentYourBrand = editCommercialContentYourBrand;
                    const tiktokCommercialContentBranded = editCommercialContentBranded;
                    
                    if (tiktokPrivacy) {
                      settings.privacy_level = tiktokPrivacy;
                    }
                    settings.allow_comments = tiktokAllowComments;
                    settings.allow_duet = tiktokAllowDuet;
                    settings.allow_stitch = tiktokAllowStitch;
                    settings.commercial_content_disclosure = tiktokCommercialContentDisclosure;
                    settings.commercial_content_your_brand = tiktokCommercialContentYourBrand;
                    settings.commercial_content_branded = tiktokCommercialContentBranded;
                  }
                  
                  updateVideoSettings(editingVideo.id, settings);
                }}
                className="btn-save"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Destination Details Modal */}
      {destinationModal && (() => {
        const video = videos.find(v => v.id === destinationModal.videoId);
        if (!video) return null;
        
        const platform = destinationModal.platform;
        const platformNames = {
          youtube: 'YouTube',
          tiktok: 'TikTok',
          instagram: 'Instagram'
        };
        
        const platformData = video.upload_properties?.[platform] || {};
        const platformStatusData = video.platform_statuses?.[platform] || {status: 'pending', error: null};
        // Handle both old format (string) and new format (object)
        const platformStatus = typeof platformStatusData === 'object' ? platformStatusData.status : platformStatusData;
        const platformErrorFromStatus = typeof platformStatusData === 'object' ? platformStatusData.error : null;
        
        // Get error from multiple possible sources
        let platformError = platformData.error || platformErrorFromStatus || null;
        if (!platformError && platform === 'tiktok') {
          platformError = video.tiktok_publish_error || null;
        }
        // If no platform-specific error but video failed, try to extract platform-specific error from general error
        if (!platformError && platformStatus === 'failed' && video.error) {
          // Check if the general error message mentions this platform
          const platformKeywords = {
            youtube: ['youtube', 'google'],
            tiktok: ['tiktok'],
            instagram: ['instagram', 'facebook']
          };
          const keywords = platformKeywords[platform] || [];
          const errorLower = video.error.toLowerCase();
          
          // If error mentions this platform, use it
          if (keywords.some(keyword => errorLower.includes(keyword))) {
            platformError = video.error;
          } else if (!video.error.includes('Upload failed for all destinations') && 
                     !video.error.includes('but failed for others')) {
            // If error doesn't mention platform but isn't generic, show it anyway
            platformError = video.error;
          }
        }
        const customSettings = video.custom_settings || {};
        
        // DRY: Helper function to format tags (must be defined before use)
        const formatTags = (tags) => {
          if (!tags) return '';
          if (Array.isArray(tags)) return tags.join(', ');
          if (typeof tags === 'string') return tags.split(',').map(t => t.trim()).join(', ');
          return String(tags);
        };
        
        // Get or initialize override input values for character counters
        const modalKey = `${video.id}-${platform}`;
        
        // Initialize values if not already set
        if (!overrideInputValues[modalKey]) {
          const initial = {};
          if (platform === 'youtube') {
            initial.youtube_title = customSettings.youtube_title || platformData.title || '';
            initial.description = customSettings.description || platformData.description || '';
            initial.tags = customSettings.tags || formatTags(platformData.tags) || '';
          } else if (platform === 'tiktok') {
            initial.title = customSettings.title || platformData.title || '';
          } else if (platform === 'instagram') {
            initial.title = customSettings.title || platformData.caption || '';
          }
          setOverrideInputValues(prev => ({ ...prev, [modalKey]: initial }));
        }
        
        const overrideValues = overrideInputValues[modalKey] || {};
        
        const updateOverrideValue = (key, value) => {
          setOverrideInputValues(prev => ({
            ...prev,
            [modalKey]: {
              ...(prev[modalKey] || {}),
              [key]: value
            }
          }));
        };
        
        // DRY: Reusable style objects for metadata display
        const metadataContainerStyle = {
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          padding: '0.75rem',
          background: rgba(HOPPER_COLORS.rgb.white, 0.03),
          border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.1)}`,
          borderRadius: '6px',
          fontSize: '0.9rem'
        };
        
        const metadataItemStyle = {
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem'
        };
        
        const metadataLabelStyle = {
          fontWeight: '600',
          color: HOPPER_COLORS.light
        };
        
        const metadataValueStyle = {
          color: HOPPER_COLORS.light
        };
        
        const metadataTextBlockStyle = {
          marginTop: '0.25rem',
          padding: '0.5rem',
          background: rgba(HOPPER_COLORS.rgb.base, 0.2),
          borderRadius: '4px',
          color: HOPPER_COLORS.light,
          maxHeight: '150px',
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word'
        };
        
        const metadataGridStyle = {
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '0.5rem',
          marginTop: '0.25rem'
        };
        
        const metadataStatusBadgeStyle = (status) => ({
          marginTop: '0.5rem',
          padding: '0.5rem',
          background: status === 'PUBLISHED' 
            ? rgba(HOPPER_COLORS.rgb.success, 0.1)
            : rgba(HOPPER_COLORS.rgb.info, 0.1),
          borderRadius: '4px',
          border: `1px solid ${
            status === 'PUBLISHED' 
              ? rgba(HOPPER_COLORS.rgb.success, 0.3)
              : rgba(HOPPER_COLORS.rgb.info, 0.3)
          }`
        });
        
        const metadataWarningBoxStyle = {
          marginTop: '0.25rem',
          padding: '0.5rem',
          background: rgba(HOPPER_COLORS.rgb.warning, 0.1),
          borderRadius: '4px',
          border: `1px solid ${rgba(HOPPER_COLORS.rgb.warning, 0.3)}`
        };
        
        // DRY: Helper function to format boolean values
        const formatBoolean = (value, undefinedText = 'Not set') => {
          if (value === undefined || value === null) return undefinedText;
          return value ? 'Yes' : 'No';
        };
        
        const handleSaveOverrides = async () => {
          try {
            const overrides = {};
            
            if (platform === 'youtube') {
              const descEl = document.getElementById(`dest-override-description-${video.id}-${platform}`);
              const tagsEl = document.getElementById(`dest-override-tags-${video.id}-${platform}`);
              const visibilityEl = document.getElementById(`dest-override-visibility-${video.id}-${platform}`);
              const madeForKidsEl = document.getElementById(`dest-override-made-for-kids-${video.id}-${platform}`);
              
              if (overrideValues.youtube_title) overrides.title = overrideValues.youtube_title;
              if (descEl?.value) overrides.description = descEl.value;
              if (tagsEl?.value) overrides.tags = tagsEl.value;
              if (visibilityEl?.value) overrides.visibility = visibilityEl.value;
              overrides.made_for_kids = madeForKidsEl?.checked ?? false;
            } else if (platform === 'tiktok') {
              const privacyEl = document.getElementById(`dest-override-privacy-${video.id}-${platform}`);
              
              if (overrideValues.title) overrides.title = overrideValues.title;
              if (privacyEl?.value) overrides.privacy_level = privacyEl.value;
            } else if (platform === 'instagram') {
              const mediaTypeEl = document.getElementById(`dest-override-media-type-${video.id}-${platform}`);
              const shareToFeedEl = document.getElementById(`dest-override-share-to-feed-${video.id}-${platform}`);
              const coverUrlEl = document.getElementById(`dest-override-cover-url-${video.id}-${platform}`);
              const disableCommentsEl = document.getElementById(`dest-override-disable-comments-${video.id}-${platform}`);
              const disableLikesEl = document.getElementById(`dest-override-disable-likes-${video.id}-${platform}`);
              
              if (overrideValues.title) overrides.title = overrideValues.title;
              if (mediaTypeEl?.value) overrides.media_type = mediaTypeEl.value;
              if (disableCommentsEl !== null) overrides.disable_comments = disableCommentsEl.checked;
              if (disableLikesEl !== null) overrides.disable_likes = disableLikesEl.checked;
              
              // Only include share_to_feed for REELS media type
              const mediaType = mediaTypeEl?.value || customSettings.media_type || platformData.media_type || 'REELS';
              if (mediaType === 'REELS' && shareToFeedEl !== null) {
                overrides.share_to_feed = shareToFeedEl.checked;
              }
              
              if (coverUrlEl?.value) overrides.cover_url = coverUrlEl.value;
            }
            
            const success = await saveDestinationOverrides(video.id, platform, overrides);
            if (success) {
              setDestinationModal(null);
            }
          } catch (err) {
            console.error('Error saving destination overrides:', err);
          }
        };
        
        // DRY: Reusable button styles
        const errorButtonBaseStyle = {
          padding: '0.375rem 0.75rem',
          background: rgba(HOPPER_COLORS.rgb.error, 0.1),
          border: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`,
          borderRadius: '6px',
          color: HOPPER_COLORS.error,
          cursor: 'pointer',
          fontSize: '0.85rem',
          fontWeight: '500',
          transition: 'all 0.2s',
          fontFamily: 'inherit'
        };
        
        const errorButtonHoverStyle = {
          background: rgba(HOPPER_COLORS.rgb.error, 0.2),
          borderColor: rgba(HOPPER_COLORS.rgb.error, 0.5)
        };
        
        return (
          <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'var(--bg-overlay)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10000,
              padding: '1rem'
            }}
            onClick={() => setDestinationModal(null)}
          >
            <div
              className="modal"
              onClick={(e) => e.stopPropagation()}
              style={{
                maxWidth: '700px',
                width: '100%',
                maxHeight: '90vh',
                overflowY: 'auto'
              }}
            >
              <div className="modal-header">
                <h2>
                  {platformNames[platform]} Upload Details
                  {platformStatus === 'success' && <span style={{ color: HOPPER_COLORS.success, marginLeft: '8px' }}>✓</span>}
                  {platformStatus === 'failed' && <span style={{ color: HOPPER_COLORS.error, marginLeft: '8px' }}>✕</span>}
                </h2>
                <button className="btn-close" onClick={() => setDestinationModal(null)}>×</button>
              </div>
              
              <div className="modal-body">
                {/* Upload Status */}
                <div className="setting-group">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label>Upload Status</label>
                    {platformStatus === 'failed' && (
                      <button
                        onClick={() => {
                          const errorKey = `${video.id}-${platform}`;
                          setExpandedDestinationErrors(prev => {
                            const newSet = new Set(prev);
                            if (newSet.has(errorKey)) {
                              newSet.delete(errorKey);
                            } else {
                              newSet.add(errorKey);
                            }
                            return newSet;
                          });
                        }}
                        style={errorButtonBaseStyle}
                        onMouseEnter={(e) => {
                          Object.assign(e.target.style, errorButtonHoverStyle);
                        }}
                        onMouseLeave={(e) => {
                          Object.assign(e.target.style, errorButtonBaseStyle);
                        }}
                      >
                        {expandedDestinationErrors.has(`${video.id}-${platform}`) ? 'Hide Error' : 'Show Error'}
                      </button>
                    )}
                  </div>
                  <div style={{
                    padding: '0.75rem',
                    background: platformStatus === 'success' 
                      ? rgba(HOPPER_COLORS.rgb.success, 0.1)
                      : platformStatus === 'failed'
                      ? rgba(HOPPER_COLORS.rgb.error, 0.1)
                      : rgba(HOPPER_COLORS.rgb.white, 0.05),
                    border: `1px solid ${
                      platformStatus === 'success'
                        ? HOPPER_COLORS.success
                        : platformStatus === 'failed'
                        ? HOPPER_COLORS.error
                        : rgba(HOPPER_COLORS.rgb.white, 0.2)
                    }`,
                    borderRadius: '6px',
                    color: platformStatus === 'success'
                      ? HOPPER_COLORS.success
                      : platformStatus === 'failed'
                      ? HOPPER_COLORS.error
                      : HOPPER_COLORS.grey,
                    fontWeight: '500'
                  }}>
                    {platformStatus === 'success' && '✓ Upload Successful'}
                    {platformStatus === 'failed' && '✕ Upload Failed'}
                    {platformStatus === 'pending' && '⏳ Pending Upload'}
                  </div>
                </div>
                
                {/* Destination-Specific Error Display */}
                {platformStatus === 'failed' && expandedDestinationErrors.has(`${video.id}-${platform}`) && (
                  <div className="setting-group">
                    <label>{platformNames[platform]} Upload Error</label>
                    <div style={{
                      padding: '0.75rem',
                      background: rgba(HOPPER_COLORS.rgb.error, 0.1),
                      border: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`,
                      borderRadius: '6px',
                      color: HOPPER_COLORS.error,
                      fontSize: '0.9rem',
                      wordBreak: 'break-word'
                    }}>
                      {platformError ? (
                        platformError
                      ) : (
                        <div style={{ fontStyle: 'italic', opacity: 0.8 }}>
                          No detailed error message available. The upload failed but no specific error was captured.
                          {video.error && (
                            <div style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.2)}` }}>
                              <strong>General error:</strong> {video.error}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                
                {/* Upload Metadata */}
                <div className="setting-group">
                  <label>Upload Metadata</label>
                  <div style={metadataContainerStyle}>
                    {platform === 'youtube' && (
                      <div style={metadataItemStyle}>
                        <div>
                          <span style={metadataLabelStyle}>Title:</span>
                          <div style={metadataTextBlockStyle}>
                            {platformData.title || video.youtube_title || video.filename}
                          </div>
                        </div>
                        {platformData.description && (
                          <div>
                            <span style={metadataLabelStyle}>Description:</span>
                            <div style={metadataTextBlockStyle}>
                              {platformData.description}
                            </div>
                          </div>
                        )}
                        {platformData.tags && (
                          <div>
                            <span style={metadataLabelStyle}>Tags:</span>{' '}
                            <span style={metadataValueStyle}>{formatTags(platformData.tags)}</span>
                          </div>
                        )}
                        {platformData.visibility && (
                          <div>
                            <span style={metadataLabelStyle}>Visibility:</span>{' '}
                            <span style={{...metadataValueStyle, textTransform: 'capitalize'}}>
                              {platformData.visibility}
                            </span>
                          </div>
                        )}
                        {platformData.made_for_kids !== undefined && (
                          <div>
                            <span style={metadataLabelStyle}>Made for Kids:</span>{' '}
                            <span style={metadataValueStyle}>{formatBoolean(platformData.made_for_kids)}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {platform === 'tiktok' && (
                      <div style={metadataItemStyle}>
                        {platformData.title && (
                          <div>
                            <span style={metadataLabelStyle}>Title:</span>
                            <div style={{...metadataTextBlockStyle, maxHeight: 'none'}}>
                              {platformData.title}
                            </div>
                          </div>
                        )}
                        {platformData.privacy_level && (
                          <div>
                            <span style={metadataLabelStyle}>Privacy Level:</span>{' '}
                            <span style={{...metadataValueStyle, textTransform: 'capitalize'}}>
                              {platformData.privacy_level}
                            </span>
                          </div>
                        )}
                        <div style={metadataGridStyle}>
                          <div>
                            <span style={metadataLabelStyle}>Allow Comments:</span>{' '}
                            <span style={metadataValueStyle}>{formatBoolean(platformData.allow_comments)}</span>
                          </div>
                          <div>
                            <span style={metadataLabelStyle}>Allow Duet:</span>{' '}
                            <span style={metadataValueStyle}>{formatBoolean(platformData.allow_duet)}</span>
                          </div>
                          <div>
                            <span style={metadataLabelStyle}>Allow Stitch:</span>{' '}
                            <span style={metadataValueStyle}>{formatBoolean(platformData.allow_stitch)}</span>
                          </div>
                          {platformData.commercial_content_disclosure !== undefined && (
                            <div>
                              <span style={metadataLabelStyle}>Commercial Disclosure:</span>{' '}
                              <span style={metadataValueStyle}>{formatBoolean(platformData.commercial_content_disclosure)}</span>
                            </div>
                          )}
                        </div>
                        {(platformData.commercial_content_your_brand || platformData.commercial_content_branded) && (
                          <div style={metadataWarningBoxStyle}>
                            <strong style={{ color: HOPPER_COLORS.warning }}>Commercial Content:</strong>
                            <div style={{ marginTop: '0.25rem', color: HOPPER_COLORS.light, fontSize: '0.85rem' }}>
                              {platformData.commercial_content_your_brand && <div>• Your Brand</div>}
                              {platformData.commercial_content_branded && <div>• Branded Content</div>}
                            </div>
                          </div>
                        )}
                        {video.tiktok_publish_status && (
                          <div style={metadataStatusBadgeStyle(video.tiktok_publish_status)}>
                            <strong>Publish Status:</strong>{' '}
                            <span style={{ 
                              color: video.tiktok_publish_status === 'PUBLISHED' 
                                ? HOPPER_COLORS.success
                                : HOPPER_COLORS.info,
                              textTransform: 'capitalize'
                            }}>{video.tiktok_publish_status}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {platform === 'instagram' && (
                      <div style={metadataItemStyle}>
                        {platformData.caption && (
                          <div>
                            <span style={metadataLabelStyle}>Caption:</span>
                            <div style={metadataTextBlockStyle}>
                              {platformData.caption}
                            </div>
                          </div>
                        )}
                        <div style={metadataGridStyle}>
                          <div>
                            <span style={metadataLabelStyle}>Media Type:</span>{' '}
                            <span style={metadataValueStyle}>
                              {platformData.media_type || 'REELS'}
                            </span>
                          </div>
                          {(platformData.media_type === 'REELS' || !platformData.media_type) && (
                            <div>
                              <span style={metadataLabelStyle}>Share to Feed:</span>{' '}
                              <span style={metadataValueStyle}>
                                {platformData.share_to_feed !== false ? 'Yes' : 'No'}
                              </span>
                            </div>
                          )}
                          <div>
                            <span style={metadataLabelStyle}>Comments:</span>{' '}
                            <span style={metadataValueStyle}>
                              {platformData.disable_comments ? 'Disabled' : 'Enabled'}
                            </span>
                          </div>
                          <div>
                            <span style={metadataLabelStyle}>Likes:</span>{' '}
                            <span style={metadataValueStyle}>
                              {platformData.disable_likes ? 'Disabled' : 'Enabled'}
                            </span>
                          </div>
                        </div>
                        {platformData.cover_url && (
                          <div>
                            <span style={metadataLabelStyle}>Cover Image:</span>{' '}
                            <span style={metadataValueStyle}>Custom thumbnail set</span>
                          </div>
                        )}
                        {/* Commented out - removed Audio Name feature
                        {platformData.audio_name && (
                          <div>
                            <span style={metadataLabelStyle}>Audio Name:</span>{' '}
                            <span style={metadataValueStyle}>{platformData.audio_name}</span>
                          </div>
                        )}
                        */}
                      </div>
                    )}
                    {(!platformData || Object.keys(platformData).length === 0) && (
                      <div style={{ 
                        color: HOPPER_COLORS.grey,
                        fontStyle: 'italic',
                        textAlign: 'center',
                        padding: '1rem'
                      }}>
                        No upload metadata available yet. Metadata will be computed when the upload is processed.
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Override Configuration */}
                <div className="setting-group">
                  <label>
                    Override Settings (Optional)
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">Override default settings for this video on {platformNames[platform]} only</span>
                    </span>
                  </label>
                  
                  {platform === 'youtube' && (
                    <>
                      <div className="setting-group">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <label htmlFor={`dest-override-title-${video.id}-${platform}`}>
                            Title <span className="char-counter">{(overrideValues.youtube_title || '').length}/100</span>
                          </label>
                          <button
                            type="button"
                            onClick={() => recomputeVideoField(video.id, platform, 'title')}
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
                          id={`dest-override-title-${video.id}-${platform}`}
                          value={overrideValues.youtube_title || ''}
                          onChange={(e) => updateOverrideValue('youtube_title', e.target.value)}
                          placeholder={platformData.title || video.filename}
                          maxLength={100}
                          className="input-text"
                        />
                      </div>
                      
                      <div className="setting-group">
                        <label htmlFor={`dest-override-description-${video.id}-${platform}`}>Description</label>
                        <textarea
                          id={`dest-override-description-${video.id}-${platform}`}
                          defaultValue={customSettings.description || platformData.description || ''}
                          placeholder={platformData.description || 'Enter description...'}
                          rows={4}
                          className="textarea-text"
                        />
                      </div>
                      
                      <div className="setting-group">
                        <label htmlFor={`dest-override-tags-${video.id}-${platform}`}>Tags (comma-separated)</label>
                        <input
                          type="text"
                          id={`dest-override-tags-${video.id}-${platform}`}
                          defaultValue={customSettings.tags || formatTags(platformData.tags) || ''}
                          placeholder={formatTags(platformData.tags) || 'Enter tags...'}
                          className="input-text"
                        />
                      </div>
                      
                      <div className="setting-group">
                        <label htmlFor={`dest-override-visibility-${video.id}-${platform}`}>Visibility</label>
                        <select
                          id={`dest-override-visibility-${video.id}-${platform}`}
                          defaultValue={customSettings.visibility || platformData.visibility || 'private'}
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
                            id={`dest-override-made-for-kids-${video.id}-${platform}`}
                            defaultChecked={customSettings.made_for_kids !== undefined ? customSettings.made_for_kids : platformData.made_for_kids || false}
                            className="checkbox"
                          />
                          <span>Made for Kids</span>
                        </label>
                      </div>
                    </>
                  )}
                  
                  {platform === 'tiktok' && (
                    <>
                      <div className="setting-group">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <label htmlFor={`dest-override-title-${video.id}-${platform}`}>
                            Title <span className="char-counter">{(overrideValues.title || '').length}/2200</span>
                          </label>
                          <button
                            type="button"
                            onClick={() => recomputeVideoField(video.id, platform, 'title')}
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
                          id={`dest-override-title-${video.id}-${platform}`}
                          value={overrideValues.title || ''}
                          onChange={(e) => updateOverrideValue('title', e.target.value)}
                          placeholder={platformData.title || 'Enter title...'}
                          maxLength={2200}
                          className="input-text"
                        />
                      </div>
                      
                      <div className="setting-group">
                        <label htmlFor={`dest-override-privacy-${video.id}-${platform}`}>Privacy Level</label>
                        <select
                          id={`dest-override-privacy-${video.id}-${platform}`}
                          defaultValue={customSettings.privacy_level || platformData.privacy_level || ''}
                          className="select"
                        >
                          <option value="">Use default</option>
                          <option value="PUBLIC_TO_EVERYONE">Public to Everyone</option>
                          <option value="MUTUAL_FOLLOW_FRIENDS">Friends</option>
                          <option value="FOLLOWER_OF_CREATOR">Followers</option>
                          <option value="SELF_ONLY">Only you</option>
                        </select>
                      </div>
                    </>
                  )}
                  
                  {platform === 'instagram' && (
                    <>
                      <div className="setting-group">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <label htmlFor={`dest-override-caption-${video.id}-${platform}`}>
                            Title/Caption <span className="char-counter">{(overrideValues.title || '').length}/2200</span>
                          </label>
                          <button
                            type="button"
                            onClick={() => recomputeVideoField(video.id, platform, 'caption')}
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
                            title="Recompute caption from current template"
                          >
                            🔄 Recompute
                          </button>
                        </div>
                        <textarea
                          id={`dest-override-caption-${video.id}-${platform}`}
                          value={overrideValues.title || ''}
                          onChange={(e) => updateOverrideValue('title', e.target.value)}
                          placeholder={platformData.caption || 'Enter title/caption...'}
                          rows={4}
                          maxLength={2200}
                          className="textarea-text"
                        />
                      </div>

                      <div className="setting-group">
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            id={`dest-override-disable-comments-${video.id}-${platform}`}
                            defaultChecked={customSettings.disable_comments !== undefined ? customSettings.disable_comments : (platformData.disable_comments ?? false)}
                            className="checkbox"
                          />
                          <span>Disable Comments</span>
                        </label>
                      </div>

                      <div className="setting-group">
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            id={`dest-override-disable-likes-${video.id}-${platform}`}
                            defaultChecked={customSettings.disable_likes !== undefined ? customSettings.disable_likes : (platformData.disable_likes ?? false)}
                            className="checkbox"
                          />
                          <span>Disable Likes</span>
                        </label>
                      </div>

                      <div className="setting-group">
                        <label htmlFor={`dest-override-media-type-${video.id}-${platform}`}>Media Type</label>
                        <select
                          id={`dest-override-media-type-${video.id}-${platform}`}
                          defaultValue={customSettings.media_type || platformData.media_type || 'REELS'}
                          className="select"
                        >
                          <option value="REELS">Reels</option>
                          <option value="VIDEO">Video (Feed Post)</option>
                        </select>
                      </div>

                      {(() => {
                        const currentMediaType = customSettings.media_type || platformData.media_type || 'REELS';
                        if (currentMediaType !== 'REELS') return null;
                        
                        return (
                          <div className="setting-group">
                            <label className="checkbox-label">
                              <input
                                type="checkbox"
                                id={`dest-override-share-to-feed-${video.id}-${platform}`}
                                defaultChecked={customSettings.share_to_feed !== undefined ? customSettings.share_to_feed : (platformData.share_to_feed ?? true)}
                                className="checkbox"
                              />
                              <span>Share Reel to Feed</span>
                            </label>
                          </div>
                        );
                      })()}

                      <div className="setting-group">
                        <label htmlFor={`dest-override-cover-url-${video.id}-${platform}`}>Cover Image URL (Optional)</label>
                        <input
                          type="text"
                          id={`dest-override-cover-url-${video.id}-${platform}`}
                          defaultValue={customSettings.cover_url || platformData.cover_url || ''}
                          placeholder="https://example.com/image.jpg"
                          className="input-text"
                        />
                      </div>

                      {/* Commented out - removed Audio Name feature
                      <div className="setting-group">
                        <label htmlFor={`dest-override-audio-name-${video.id}-${platform}`}>Audio Name (Optional, Reels only)</label>
                        <input
                          type="text"
                          id={`dest-override-audio-name-${video.id}-${platform}`}
                          defaultValue={customSettings.audio_name || platformData.audio_name || ''}
                          placeholder="Audio track name"
                          className="input-text"
                        />
                      </div>
                      */}
                    </>
                  )}
                </div>
              </div>
              
              <div className="modal-footer">
                <button
                  onClick={() => setDestinationModal(null)}
                  className="btn-cancel"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveOverrides}
                  className="btn-save"
                >
                  Save Overrides
                </button>
              </div>
            </div>
          </div>
        );
      })()}
      
      {/* Account Settings Modal */}
      {showAccountSettings && (
        <div className="modal-overlay" onClick={() => setShowAccountSettings(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <div className="modal-header">
              <h2>⚙️ Account Settings</h2>
              <button onClick={() => setShowAccountSettings(false)} className="btn-close">×</button>
            </div>
            
            <div className="modal-body">
              {/* Account Info + inline Change Password */}
              <div className="form-group" style={{ 
                padding: '1rem', 
                background: 'rgba(255, 255, 255, 0.05)', 
                borderRadius: '8px',
                border: '1px solid rgba(255, 255, 255, 0.1)'
              }}>
                <div style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginBottom: '0.25rem' }}>Logged in as</div>
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  marginBottom: '0.75rem'
                }}>
                  <div style={{ fontSize: '1rem', fontWeight: '500', color: 'white' }}>{user.email}</div>
                  <button
                    type="button"
                    onClick={() => setShowChangePassword(!showChangePassword)}
                    style={{
                      padding: '0.3rem 0.6rem',
                      background: 'transparent',
                      borderRadius: '999px',
                      border: '1px solid rgba(255,255,255,0.25)',
                      color: '#e5e7eb',
                      cursor: 'pointer',
                      fontSize: '0.8rem'
                    }}
                  >
                    {showChangePassword ? 'Hide' : 'Change password'}
                  </button>
                </div>
                {showChangePassword && (
                  <div style={{ marginBottom: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {resetEmailSent ? (
                      <>
                        <p style={{ color: '#22c55e', fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                          ✅ Password reset email sent to <strong>{user.email}</strong>
                        </p>
                        <p style={{ color: HOPPER_COLORS.grey, fontSize: '0.8rem', marginBottom: '0.25rem' }}>
                          Check your email and click the reset link to set a new password. The link will take you to the login screen.
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setShowChangePassword(false);
                            setResetEmailSent(false);
                          }}
                          style={{
                            padding: '0.6rem',
                            background: 'transparent',
                            borderRadius: '6px',
                            border: '1px solid rgba(255,255,255,0.25)',
                            color: HOPPER_COLORS.white,
                            cursor: 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          Close
                        </button>
                      </>
                    ) : (
                      <>
                        <p style={{ color: HOPPER_COLORS.grey, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                          We'll send a password reset link to <strong>{user.email}</strong>. Click the link in the email to set a new password.
                        </p>
                        <button
                          type="button"
                          onClick={async () => {
                            if (!user?.email) {
                              setMessage('❌ Email not available');
                              return;
                            }
                            setSendingResetEmail(true);
                            setMessage('');
                            try {
                              await axios.post(`${API}/auth/forgot-password`, { email: user.email });
                              setResetEmailSent(true);
                              setMessage('✅ Password reset email sent! Check your inbox.');
                            } catch (err) {
                              const errorMsg = err.response?.data?.detail || err.message || 'Failed to send reset email';
                              setMessage(`❌ ${errorMsg}`);
                            } finally {
                              setSendingResetEmail(false);
                            }
                          }}
                          disabled={sendingResetEmail}
                          style={{
                            padding: '0.6rem',
                            background: sendingResetEmail ? 'rgba(34, 197, 94, 0.3)' : 'rgba(34, 197, 94, 0.4)',
                            borderRadius: '6px',
                            border: '1px solid rgba(34,197,94,0.7)',
                            color: HOPPER_COLORS.white,
                            cursor: sendingResetEmail ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem',
                            fontWeight: 500,
                            opacity: sendingResetEmail ? 0.6 : 1
                          }}
                        >
                          {sendingResetEmail ? 'Sending...' : 'Send Password Reset Email'}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setShowChangePassword(false);
                            setResetEmailSent(false);
                          }}
                          style={{
                            padding: '0.6rem',
                            background: 'transparent',
                            borderRadius: '6px',
                            border: '1px solid rgba(255,255,255,0.25)',
                            color: HOPPER_COLORS.grey,
                            cursor: 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          Cancel
                        </button>
                      </>
                    )}
                  </div>
                )}
                <button 
                  onClick={handleLogout}
                  style={{
                    width: '100%',
                    padding: '0.75rem',
                    background: 'transparent',
                    border: `1px solid ${HOPPER_COLORS.grey}`,
                    borderRadius: '6px',
                    color: HOPPER_COLORS.grey,
                    cursor: 'pointer',
                    fontSize: '1rem',
                    fontWeight: '500',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = 'rgba(255, 255, 255, 0.05)';
                    e.target.style.borderColor = HOPPER_COLORS.grey;
                    e.target.style.color = 'white';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = 'transparent';
                    e.target.style.borderColor = HOPPER_COLORS.grey;
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
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h3 style={{ color: '#818cf8', fontSize: '1.1rem', marginTop: 0, marginBottom: 0 }}>
                    💳 Subscription & Tokens
                  </h3>
                  {subscription && subscription.plan_type !== 'free' && subscription.status === 'active' && (
                    <button
                      onClick={handleOpenStripePortal}
                      disabled={loadingSubscription}
                      style={{
                        padding: '0.5rem 0.75rem',
                        background: 'rgba(99, 102, 241, 0.2)',
                        border: '1px solid rgba(99, 102, 241, 0.5)',
                        borderRadius: '6px',
                        color: '#818cf8',
                        cursor: loadingSubscription ? 'not-allowed' : 'pointer',
                        fontSize: '0.85rem',
                        fontWeight: '600',
                        transition: 'all 0.2s ease',
                        opacity: loadingSubscription ? 0.6 : 1,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem'
                      }}
                      onMouseEnter={(e) => {
                        if (!loadingSubscription) {
                          e.currentTarget.style.background = 'rgba(99, 102, 241, 0.3)';
                          e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.7)';
                          e.currentTarget.style.transform = 'translateY(-1px)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!loadingSubscription) {
                          e.currentTarget.style.background = 'rgba(99, 102, 241, 0.2)';
                          e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.5)';
                          e.currentTarget.style.transform = 'translateY(0)';
                        }
                      }}
                      title="Manage subscription in Stripe"
                    >
                      ⚙️ Manage
                    </button>
                  )}
                </div>
                
                {/* Token Balance - Always visible */}
                <div style={{
                  padding: '1rem',
                  background: 'rgba(0, 0, 0, 0.2)',
                  borderRadius: '8px',
                  marginBottom: '1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '0.6rem'
                }}>
                  <div style={{ fontSize: '0.75rem', color: HOPPER_COLORS.grey, textAlign: 'center' }}>Token Usage</div>
                  <CircularTokenProgress
                    tokensRemaining={tokenBalance?.tokens_remaining}
                    tokensUsed={tokenBalance?.tokens_used_this_period || 0}
                    monthlyTokens={tokenBalance?.monthly_tokens || 0}
                    overageTokens={tokenBalance?.overage_tokens || 0}
                    unlimited={tokenBalance?.unlimited || false}
                    isLoading={!tokenBalance}
                  />
                  {tokenBalance && !tokenBalance.unlimited && tokenBalance.period_end && (
                    <div style={{ fontSize: '0.65rem', color: HOPPER_COLORS.grey, textAlign: 'center' }}>
                      Resets: {new Date(tokenBalance.period_end).toLocaleDateString()}
                    </div>
                  )}
                </div>

                {/* Available Plans - Always show, even if subscription is null */}
                {availablePlans.filter(plan => !plan.hidden && plan.tokens !== -1).length > 0 && (
                  <div id="subscription-plans" style={{ marginBottom: '1rem' }}>
                    <div style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginBottom: '0.75rem' }}>
                      Available Plans
                    </div>
                    {!subscription && (
                      <div style={{ 
                        padding: '0.75rem', 
                        marginBottom: '0.5rem',
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        borderRadius: '6px',
                        fontSize: '0.75rem',
                        color: HOPPER_COLORS.error
                      }}>
                        ⚠️ No active subscription. Please select a plan below.
                      </div>
                    )}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {availablePlans.filter(plan => !plan.hidden && plan.tokens !== -1).map(plan => {
                        const isCurrent = subscription && subscription.plan_type === plan.key;
                            const canUpgrade = !isCurrent && plan.key !== 'free' && plan.stripe_price_id;
                            const isThisPlanLoading = loadingPlanKey === plan.key; // Only this specific plan is loading
                            return (
                              <div 
                                key={plan.key}
                                onClick={canUpgrade && !isThisPlanLoading ? () => handleUpgrade(plan.key) : undefined}
                                style={{
                                  padding: '0.75rem',
                                  background: isCurrent ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                                  border: isCurrent ? '1px solid rgba(99, 102, 241, 0.5)' : '1px solid rgba(255, 255, 255, 0.1)',
                                  borderRadius: '6px',
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center',
                                  cursor: (canUpgrade || !subscription) && !isThisPlanLoading ? 'pointer' : 'default',
                                  transition: (canUpgrade || !subscription) ? 'all 0.2s ease' : 'none',
                                  opacity: isThisPlanLoading ? 0.6 : 1
                                }}
                                onMouseEnter={(e) => {
                                  if (canUpgrade && !isThisPlanLoading) {
                                    e.currentTarget.style.background = 'rgba(99, 102, 241, 0.15)';
                                    e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.6)';
                                    e.currentTarget.style.transform = 'translateY(-2px)';
                                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(99, 102, 241, 0.3)';
                                  }
                                }}
                                onMouseLeave={(e) => {
                                  if (canUpgrade) {
                                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                                    e.currentTarget.style.border = '1px solid rgba(255, 255, 255, 0.1)';
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.boxShadow = 'none';
                                  }
                                }}
                              >
                                <div>
                                  <div style={{ 
                                    fontSize: '0.95rem', 
                                    fontWeight: '600', 
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                  }}>
                                    <span>{plan.name}</span>
                                    {plan.price && (
                                      <span style={{ 
                                        fontSize: '0.85rem', 
                                        fontWeight: '500', 
                                        color: '#818cf8'
                                      }}>
                                        {(() => {
                                          if (plan.key === 'free') {
                                            return 'Free';
                                          } else if (plan.tokens === -1) {
                                            // Unlimited plan
                                            return plan.price.formatted;
                                          } else {
                                            // New pricing: amount_dollars is the flat monthly fee
                                            const monthlyFee = plan.price.amount_dollars || 0;
                                            const overagePrice = plan.overage_price?.amount_dollars;
                                            
                                            if (overagePrice !== undefined && overagePrice !== null) {
                                              // Display as: "$3/month (1.5c /token)"
                                              const overageCents = (overagePrice * 100).toFixed(1);
                                              return `$${monthlyFee.toFixed(2)}/month (${overageCents}c /token)`;
                                            } else {
                                              // Fallback if overage price not available
                                              return `$${monthlyFee.toFixed(2)}/month`;
                                            }
                                          }
                                        })()}
                                      </span>
                                    )}
                                  </div>
                                  <div style={{ fontSize: '0.75rem', color: HOPPER_COLORS.grey }}>
                                    {plan.description || (plan.tokens === -1 ? 'Unlimited tokens' : `${plan.tokens} tokens/month`)}
                                  </div>
                                </div>
                                {isCurrent ? (
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
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
                                    {subscription && subscription.plan_type !== 'free' && subscription.plan_type !== 'free_daily' && subscription.status === 'active' && (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          const currentTokens = tokenBalance?.tokens_remaining || 0;
                                          setConfirmDialog({
                                            title: 'Cancel Subscription?',
                                            message: `Are you sure you want to cancel your subscription? Your subscription will be canceled immediately and you'll be switched to the free plan. Your current token balance (${currentTokens} tokens) will be preserved.`,
                                            onConfirm: () => {
                                              setConfirmDialog(null);
                                              handleCancelSubscription();
                                            },
                                            onCancel: () => setConfirmDialog(null)
                                          });
                                        }}
                                        disabled={loadingSubscription}
                                        style={{
                                          padding: '0.5rem 0.75rem',
                                          background: 'rgba(239, 68, 68, 0.2)',
                                          border: '1px solid rgba(239, 68, 68, 0.5)',
                                          borderRadius: '4px',
                                          color: HOPPER_COLORS.error,
                                          cursor: loadingSubscription ? 'not-allowed' : 'pointer',
                                          fontSize: '0.75rem',
                                          fontWeight: '600',
                                          transition: 'all 0.2s ease',
                                          opacity: loadingSubscription ? 0.6 : 1
                                        }}
                                        onMouseEnter={(e) => {
                                          if (!loadingSubscription) {
                                            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.3)';
                                            e.currentTarget.style.border = '1px solid rgba(239, 68, 68, 0.7)';
                                          }
                                        }}
                                        onMouseLeave={(e) => {
                                          if (!loadingSubscription) {
                                            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)';
                                            e.currentTarget.style.border = '1px solid rgba(239, 68, 68, 0.5)';
                                          }
                                        }}
                                      >
                                        Cancel
                                      </button>
                                    )}
                                  </div>
                                ) : canUpgrade ? (
                                  <span style={{ 
                                    fontSize: '0.75rem', 
                                    padding: '0.25rem 0.5rem',
                                    background: 'rgba(99, 102, 241, 0.3)',
                                    color: '#818cf8',
                                    borderRadius: '4px',
                                    fontWeight: '600'
                                  }}>
                                    {isThisPlanLoading ? '⏳' : '⬆️ Upgrade'}
                                  </span>
                                ) : !subscription ? (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleUpgrade(plan.key);
                                    }}
                                    disabled={isThisPlanLoading}
                                    style={{
                                      padding: '0.5rem 0.75rem',
                                      background: 'rgba(99, 102, 241, 0.5)',
                                      border: '1px solid rgba(99, 102, 241, 0.7)',
                                      borderRadius: '4px',
                                      color: '#fff',
                                      cursor: isThisPlanLoading ? 'not-allowed' : 'pointer',
                                      fontSize: '0.75rem',
                                      fontWeight: '600',
                                      transition: 'all 0.2s ease',
                                      opacity: isThisPlanLoading ? 0.6 : 1
                                    }}
                                    onMouseEnter={(e) => {
                                      if (!isThisPlanLoading) {
                                        e.currentTarget.style.background = 'rgba(99, 102, 241, 0.7)';
                                        e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.9)';
                                      }
                                    }}
                                    onMouseLeave={(e) => {
                                      if (!isThisPlanLoading) {
                                        e.currentTarget.style.background = 'rgba(99, 102, 241, 0.5)';
                                        e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.7)';
                                      }
                                    }}
                                  >
                                    {isThisPlanLoading ? '⏳' : 'Select Plan'}
                                  </button>
                                ) : plan.key === 'free' && subscription && subscription.plan_type !== 'free' ? (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const currentTokens = tokenBalance?.tokens_remaining || 0;
                                      const isAlreadyCanceled = subscription.status === 'canceled';
                                      setConfirmDialog({
                                        title: 'Switch to Free Plan?',
                                        message: isAlreadyCanceled 
                                          ? `Switch to the free plan? Your current token balance (${currentTokens} tokens) will be preserved.`
                                          : `Are you sure you want to switch to the free plan? Your current subscription will be canceled immediately. Your current token balance (${currentTokens} tokens) will be preserved.`,
                                        onConfirm: () => {
                                          setConfirmDialog(null);
                                          handleCancelSubscription();
                                        },
                                        onCancel: () => setConfirmDialog(null)
                                      });
                                    }}
                                    disabled={loadingSubscription}
                                    style={{
                                      padding: '0.5rem 0.75rem',
                                      background: 'rgba(99, 102, 241, 0.2)',
                                      border: '1px solid rgba(99, 102, 241, 0.5)',
                                      borderRadius: '4px',
                                      color: '#818cf8',
                                      cursor: loadingSubscription ? 'not-allowed' : 'pointer',
                                      fontSize: '0.75rem',
                                      fontWeight: '600',
                                      transition: 'all 0.2s ease',
                                      opacity: loadingSubscription ? 0.6 : 1
                                    }}
                                    onMouseEnter={(e) => {
                                      if (!loadingSubscription) {
                                        e.currentTarget.style.background = 'rgba(99, 102, 241, 0.3)';
                                        e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.7)';
                                      }
                                    }}
                                    onMouseLeave={(e) => {
                                      if (!loadingSubscription) {
                                        e.currentTarget.style.background = 'rgba(99, 102, 241, 0.2)';
                                        e.currentTarget.style.border = '1px solid rgba(99, 102, 241, 0.5)';
                                      }
                                    }}
                                  >
                                    Switch to Free
                                  </button>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
              </div>

              {/* Danger Zone (collapsed by default) */}
              <div className="danger-zone">
                <button
                  type="button"
                  onClick={() => setShowDangerZone(!showDangerZone)}
                  className="danger-zone-button"
                >
                  <span>⚠️ Delete My Account</span>
                  <span style={{ opacity: 0.7 }}>{showDangerZone ? '▴' : '▾'}</span>
                </button>
                {showDangerZone && (
                  <>
                    <p style={{ color: 'var(--text-secondary)', marginTop: '1rem', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: '1.5' }}>
                      Once you delete your account, there is no going back. This will permanently delete:
                    </p>
                    <ul style={{ color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.85rem', paddingLeft: '1.25rem', lineHeight: '1.6' }}>
                      <li>Your account and login credentials</li>
                      <li>All uploaded videos and files</li>
                      <li>All settings and preferences</li>
                      <li>All connected accounts (YouTube, TikTok, Instagram)</li>
                    </ul>
                    <button 
                      onClick={() => setShowDeleteConfirm(true)}
                      className="danger-zone-delete-button"
                    >
                      Delete My Account
                    </button>
                  </>
                )}
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
              <p style={{ marginBottom: '1.5rem', fontSize: '0.9rem', color: HOPPER_COLORS.grey, lineHeight: '1.6' }}>
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
        borderTop: `1px solid ${HOPPER_COLORS.greyBorder}`,
        color: HOPPER_COLORS.grey,
        fontSize: '0.9rem'
      }}>
        <Link 
          to="/terms" 
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            marginRight: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Terms of Service
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/privacy" 
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            margin: '0 1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Privacy Policy
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/help"
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            margin: '0 1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Help
        </Link>
        <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
        <Link 
          to="/delete-your-data"
          style={{ 
            color: HOPPER_COLORS.accent, 
            textDecoration: 'none', 
            marginLeft: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          Delete Your Data
        </Link>
        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
          © {new Date().getFullYear()} hopper
        </div>
        <div style={{ marginTop: '0.25rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
          <a 
            href={process.env.REACT_APP_VERSION && process.env.REACT_APP_VERSION !== 'dev' 
              ? `https://github.com/the3venthoriz0n/hopper/releases/tag/${process.env.REACT_APP_VERSION}`
              : 'https://github.com/the3venthoriz0n/hopper/releases'}
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
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
      {/* Public routes - no auth required */}
      <Route path="/login" element={<Login />} />
      <Route path="/pricing" element={<Pricing />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/delete-your-data" element={<DeleteYourData />} />
      <Route path="/help" element={<Help />} />

      {/* Landing/Root - show public page or redirect to app if authenticated */}
      <Route path="/" element={<LandingOrApp />} />

      {/* Protected routes - require authentication */}
      <Route path="/app/*" element={<ProtectedRoute><AppRoutes /></ProtectedRoute>} />
      
      {/* Admin route - requires admin access */}
      <Route path="/admin" element={<ProtectedRoute requireAdmin><AdminDashboard /></ProtectedRoute>} />
      
      {/* 404 - Must be last */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default App;

