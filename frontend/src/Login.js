import React, { useState } from 'react';
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
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

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
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Authentication failed';
      setMessage(`❌ ${errorMsg}`);
    } finally {
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
        🐸 hopper
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

