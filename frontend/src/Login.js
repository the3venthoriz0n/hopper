import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

// Build API URL at runtime - always use HTTPS for production-like domains
const getApiUrl = () => {
  if (process.env.REACT_APP_BACKEND_URL) {
    return `${process.env.REACT_APP_BACKEND_URL}/api`;
  }
  // Try to infer backend URL from frontend hostname
  const hostname = window.location.hostname;
  if (hostname.includes('hopper-')) {
    const backendHostname = hostname.replace('hopper-', 'api-');
    return `https://${backendHostname}/api`;
  }
  // Fallback to same hostname
  return `https://${hostname}/api`;
};

const API = getApiUrl();

function Login({ onLoginSuccess }) {
  const navigate = useNavigate();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  
  // Determine title based on environment
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';

  // Check for Google OAuth errors in URL parameters
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const googleLogin = urlParams.get('google_login');
    const reason = urlParams.get('reason');
    
    if (googleLogin === 'error') {
      let errorMessage = '❌ Google login failed';
      if (reason === 'invalid_state') {
        errorMessage = '❌ Google login failed: Invalid or expired session. Please try again.';
      }
      setMessage(errorMessage);
      // Clean up URL without triggering page reload
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    setLoading(true);

    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/register';
      const response = await axios.post(`${API}${endpoint}`, {
        email,
        password
      }, { withCredentials: true });

      setMessage(`✅ ${isLogin ? 'Login' : 'Registration'} successful!`);
      if (onLoginSuccess) {
        onLoginSuccess(response.data.user);
      }
      // Redirect admins to admin dashboard
      if (response.data.user?.is_admin) {
        setTimeout(() => navigate('/admin'), 500);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Authentication failed';
      setMessage(`❌ ${errorMsg}`);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      setMessage('');
      setLoading(true);
      
      // Get Google OAuth URL from backend
      const response = await axios.get(`${API}/auth/google/login`);
      const authUrl = response.data.url;
      
      // Open OAuth flow in popup
      const width = 500;
      const height = 600;
      const left = window.screen.width / 2 - width / 2;
      const top = window.screen.height / 2 - height / 2;
      
      const popup = window.open(
        authUrl,
        'Google Login',
        `width=${width},height=${height},left=${left},top=${top}`
      );
      
      // Poll to detect when popup closes
      const checkPopup = setInterval(() => {
        if (!popup || popup.closed) {
          clearInterval(checkPopup);
          // Popup closed, check auth status
          setLoading(false);
          // Trigger auth check which will log user in if session exists
          window.location.reload();
        }
      }, 500);
      
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to start Google login';
      setMessage(`❌ ${errorMsg}`);
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: '#1a1a2e'
    }}>
      <div style={{
        background: '#16213e',
        padding: '2rem',
        borderRadius: '8px',
        maxWidth: '400px',
        width: '100%',
        boxShadow: '0 4px 6px rgba(0,0,0,0.3)'
      }}>
        <h1 style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          {appTitle}
        </h1>
        
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <button
            onClick={() => { setIsLogin(true); setMessage(''); }}
            style={{
              padding: '0.5rem 1rem',
              marginRight: '0.5rem',
              background: isLogin ? '#0f3460' : 'transparent',
              border: '1px solid #0f3460',
              color: 'white',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            Login
          </button>
          <button
            onClick={() => { setIsLogin(false); setMessage(''); }}
            style={{
              padding: '0.5rem 1rem',
              background: !isLogin ? '#0f3460' : 'transparent',
              border: '1px solid #0f3460',
              color: 'white',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            Register
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '0.75rem',
                background: '#1a1a2e',
                border: '1px solid #0f3460',
                borderRadius: '4px',
                color: 'white',
                fontSize: '1rem'
              }}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <input
              type="password"
              placeholder="Password (min 8 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              style={{
                width: '100%',
                padding: '0.75rem',
                background: '#1a1a2e',
                border: '1px solid #0f3460',
                borderRadius: '4px',
                color: 'white',
                fontSize: '1rem'
              }}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '0.75rem',
              background: '#e94560',
              border: 'none',
              borderRadius: '4px',
              color: 'white',
              fontSize: '1rem',
              fontWeight: 'bold',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? 'Please wait...' : (isLogin ? 'Login' : 'Register')}
          </button>
        </form>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          margin: '1.5rem 0 1rem 0'
        }}>
          <div style={{ flex: 1, height: '1px', background: '#0f3460' }}></div>
          <span style={{ padding: '0 1rem', color: '#999', fontSize: '0.875rem' }}>OR</span>
          <div style={{ flex: 1, height: '1px', background: '#0f3460' }}></div>
        </div>

        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={loading}
          style={{
            width: '100%',
            padding: '0.75rem',
            background: 'white',
            border: '1px solid #dadce0',
            borderRadius: '4px',
            color: '#3c4043',
            fontSize: '1rem',
            fontWeight: '500',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.6 : 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.5rem'
          }}
        >
          <svg width="18" height="18" xmlns="http://www.w3.org/2000/svg">
            <g fill="none" fillRule="evenodd">
              <path d="M17.6 9.2l-.1-1.8H9v3.4h4.8C13.6 12 13 13 12 13.6v2.2h3a8.8 8.8 0 0 0 2.6-6.6z" fill="#4285F4"/>
              <path d="M9 18c2.4 0 4.5-.8 6-2.2l-3-2.2a5.4 5.4 0 0 1-8-2.9H1V13a9 9 0 0 0 8 5z" fill="#34A853"/>
              <path d="M4 10.7a5.4 5.4 0 0 1 0-3.4V5H1a9 9 0 0 0 0 8l3-2.3z" fill="#FBBC05"/>
              <path d="M9 3.6c1.3 0 2.5.4 3.4 1.3L15 2.3A9 9 0 0 0 1 5l3 2.4a5.4 5.4 0 0 1 5-3.7z" fill="#EA4335"/>
            </g>
          </svg>
          {loading ? 'Please wait...' : 'Continue with Google'}
        </button>

        {message && (
          <div style={{
            marginTop: '1rem',
            padding: '0.75rem',
            background: message.startsWith('✅') ? '#1a5928' : '#5a1a1a',
            borderRadius: '4px',
            textAlign: 'center'
          }}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
}

export default Login;

