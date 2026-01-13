import axios from 'axios';
import Cookies from 'js-cookie';

// Axios will now automatically read the 'csrf_token_client' cookie 
// and put it into the 'X-CSRF-Token' header for every request.
axios.defaults.withCredentials = true;
axios.defaults.xsrfCookieName = 'csrf_token_client';
axios.defaults.xsrfHeaderName = 'X-CSRF-Token';

// CSRF Token Management
let csrfToken = null;

/**
 * Build API URL helper function
 * @returns {string} API base URL
 */
export const getApiUrl = () => {
  const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
  return `${backendUrl}/api`;
};

/**
 * Get WebSocket URL - constructs URL through nginx proxy
 * This ensures WebSocket connects through nginx, not directly to backend port
 * @param {string} url - Optional WebSocket URL path (default: '/ws')
 * @returns {string} WebSocket URL
 */
export const getWebSocketUrl = (url = '/ws') => {
  // If URL is already a full WebSocket URL, return it
  if (url.startsWith('ws://') || url.startsWith('wss://')) {
    return url;
  }
  
  // Construct WebSocket URL using current window location (through nginx)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const hostname = window.location.hostname;
  const port = window.location.port ? `:${window.location.port}` : '';
  
  // Use current window location to ensure it goes through nginx proxy
  return `${protocol}//${hostname}${port}${url}`;
};

// Response interceptor for error handling and CSRF token refresh
axios.interceptors.response.use(
  (response) => {
    // ROOT CAUSE FIX: Always refresh CSRF token from response headers
    // This prevents stale token issues when token is refreshed between requests
    const token = response.headers['x-csrf-token'] || response.headers['X-CSRF-Token'];
    if (token) {
      // Update cookie so it's available for next request
      Cookies.set('csrf_token_client', token, { 
        secure: true, 
        sameSite: 'lax',
        path: '/'
      });
      // Update in-memory token
      csrfToken = token;
    }
    return response;
  },
  (error) => Promise.reject(error)
);

// Request interceptor for CSRF token
axios.interceptors.request.use(
  (config) => {
    // Read the non-HttpOnly cookie we set in the backend
    const token = Cookies.get('csrf_token_client');
    
    if (token) {
      config.headers['X-CSRF-Token'] = token;
    }
    
    return config;
  },
  (error) => Promise.reject(error)
);

// Export configured axios instance
export default axios;
