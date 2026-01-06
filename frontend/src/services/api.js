import axios from 'axios';
import Cookies from 'js-cookie';

// Axios will now automatically read the 'csrf_token_client' cookie 
// and put it into the 'X-CSRF-Token' header for every request.
axios.defaults.withCredentials = true;
axios.defaults.xsrfCookieName = 'csrf_token_client';
axios.defaults.xsrfHeaderName = 'X-CSRF-Token';

// CSRF Token Management
// Note: Token is automatically read from cookie via interceptor
// This variable is kept for legacy compatibility but is not actively used
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
 * Get WebSocket URL using API base URL (not window.location.host)
 * This ensures WebSocket connects through nginx proxy, not directly to backend port
 * @returns {string} WebSocket URL
 */
export const getWebSocketUrl = () => {
  const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
  // Remove protocol and /api if present, construct ws:// or wss://
  const wsProtocol = backendUrl.startsWith('https') ? 'wss:' : 'ws:';
  const baseUrl = backendUrl.replace(/^https?:\/\//, '').replace(/\/api$/, '');
  return `${wsProtocol}//${baseUrl}/ws`;
};

// Response interceptor
axios.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);

// Request interceptor - injects CSRF token from cookie
axios.interceptors.request.use(
  (config) => {
    // Read the non-HttpOnly cookie we set in the backend
    const token = Cookies.get('csrf_token_client');
    
    if (token) {
      config.headers['X-CSRF-Token'] = token;
      csrfToken = token; // Keep for legacy compatibility
    }
    
    return config;
  },
  (error) => Promise.reject(error)
);

// Export axios instance for use in services
export default axios;

