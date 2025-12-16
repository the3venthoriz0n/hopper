import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import './App.css';

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
  const [showVerification, setShowVerification] = useState(false);
  const [verificationCode, setVerificationCode] = useState('');
  const [resending, setResending] = useState(false);
  const [showPasswordReset, setShowPasswordReset] = useState(false);
  const [resetToken, setResetToken] = useState('');
  const [sendingReset, setSendingReset] = useState(false);
  const [resettingPassword, setResettingPassword] = useState(false);
  
  // Determine title based on environment
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';

  // Check for Google OAuth errors in URL parameters
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const error = urlParams.get('error');
    const reason = urlParams.get('reason');
    const googleLogin = urlParams.get('google_login'); // Legacy support
    const resetEmail = urlParams.get('reset_email');
    const resetCodeParam = urlParams.get('reset_code');
    
    // Handle new error parameter format (from backend redirect)
    if (error === 'google_login_failed') {
      let errorMessage = '❌ Google login failed. Please try again.';
      if (reason === 'invalid_state') {
        errorMessage = '❌ Google login failed: Invalid or expired session. Please try again.';
      }
      setMessage(errorMessage);
      // Clean up URL without triggering page reload
      window.history.replaceState({}, '', window.location.pathname);
    }
    // Legacy support for old format
    else if (googleLogin === 'error') {
      let errorMessage = '❌ Google login failed';
      if (reason === 'invalid_state') {
        errorMessage = '❌ Google login failed: Invalid or expired session. Please try again.';
      }
      setMessage(errorMessage);
      // Clean up URL without triggering page reload
      window.history.replaceState({}, '', window.location.pathname);
    }

    // If arriving from a password reset link, open the reset UI
    const resetTokenParam = urlParams.get('reset_token');
    if (resetTokenParam) {
      setResetToken(resetTokenParam);
      setShowPasswordReset(true);
      setShowVerification(false);
      setMessage('Enter a new password to complete your reset.');
      // Remove query params from URL
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    setLoading(true);

    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/register';
      const response = await axios.post(
        `${API}${endpoint}`,
        {
          email,
          password,
        },
        { withCredentials: true }
      );

      // Check if email verification is required after registration
      if (!isLogin && response.data.requires_email_verification) {
        setMessage('✅ Registration successful! Please check your email for a verification code.');
        setShowVerification(true);
        setShowPasswordReset(false);
        setLoading(false);
        return;
      }

      setMessage(`✅ ${isLogin ? 'Login' : 'Registration'} successful!`);

      // Allow parent components to react to successful login if they passed a handler
      if (onLoginSuccess) {
        onLoginSuccess(response.data.user);
      }

      // Redirect after successful login/registration into the app shell
      setTimeout(() => {
        if (response.data.user?.is_admin) {
          navigate('/admin');
        } else {
          navigate('/app');
        }
      }, 500);
    } catch (err) {
      // Extract error message from FastAPI response (detail field) or fallback to generic message
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Authentication failed';
      setMessage(`❌ ${errorMsg}`);
      // CRITICAL: Ensure we stay on the login page - prevent ANY navigation on error
      // Stop event propagation and prevent default to avoid any redirects
      e?.preventDefault?.();
      e?.stopPropagation?.();
      
      // Explicitly ensure we're on login page - navigate there if needed (safety check)
      if (window.location.pathname !== '/login' && window.location.pathname !== '/') {
        navigate('/login', { replace: true });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEmail = async (e) => {
    e.preventDefault();
    setMessage('');
    setLoading(true);

    try {
      // Verify the email code
      const verifyResponse = await axios.post(
        `${API}/auth/verify-email`,
        {
          email,
          code: verificationCode,
        }
      );

      setMessage('✅ Email verified! Logging you in...');

      // After verification, automatically log the user in
      const loginResponse = await axios.post(
        `${API}/auth/login`,
        {
          email,
          password,
        },
        { withCredentials: true }
      );

      // Allow parent components to react to successful login
      if (onLoginSuccess) {
        onLoginSuccess(loginResponse.data.user);
      }

      // Redirect to app
      setTimeout(() => {
        if (loginResponse.data.user?.is_admin) {
          navigate('/admin');
        } else {
          navigate('/app');
        }
      }, 500);
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Verification failed';
      setMessage(`❌ ${errorMsg}`);
      setLoading(false);
    }
  };

  const handleResendVerification = async () => {
    if (!email) {
      setMessage('❌ Please enter your email above first.');
      return;
    }
    setResending(true);
    setMessage('');
    try {
      await axios.post(`${API}/auth/resend-verification`, { email });
      setMessage('✅ If this email is registered, a new verification code has been sent.');
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to resend verification email';
      setMessage(`❌ ${errorMsg}`);
    } finally {
      setResending(false);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      setMessage('');
      setLoading(true);
      
      // Get Google OAuth URL from backend
      const response = await axios.get(`${API}/auth/google/login`);
      const authUrl = response.data.url;
      
      // Open OAuth flow in popup (so main app stays on screen)
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
          // Popup closed, stop loading state
          setLoading(false);
          // After OAuth flow completes, session cookie is set on the domain.
          // Send the main window into the app shell where auth check will pick up the session.
          window.location.href = '/app';
        }
      }, 500);
      
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to start Google login';
      setMessage(`❌ ${errorMsg}`);
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h1 className="login-title">
          {appTitle}
        </h1>
        
        {!showVerification && !showPasswordReset && (
          <div className="login-tabs">
            <button
              onClick={() => { setIsLogin(true); setMessage(''); setShowVerification(false); }}
              className={`login-tab ${isLogin ? 'active' : ''}`}
            >
              Login
            </button>
            <button
              onClick={() => { setIsLogin(false); setMessage(''); setShowVerification(false); }}
              className={`login-tab ${!isLogin ? 'active' : ''}`}
            >
              Register
            </button>
          </div>
        )}

        {showVerification ? (
          <form onSubmit={handleVerifyEmail}>
            <div style={{ marginBottom: '1rem', textAlign: 'center' }}>
              <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                We sent a verification code to <strong>{email}</strong>
              </p>
            </div>
            <div
              className="verification-code-container"
              onClick={() => {
                const input = document.getElementById('verification-code-input');
                if (input) {
                  input.focus();
                }
              }}
            >
              {/* Hidden actual input to support typing and paste */}
              <input
                id="verification-code-input"
                type="text"
                inputMode="text"
                autoComplete="one-time-code"
                value={verificationCode}
                onChange={(e) =>
                  setVerificationCode(
                    e.target.value.replace(/[^a-zA-Z0-9]/g, '').slice(0, 6).toUpperCase()
                  )
                }
                className="verification-code-input"
              />
              {Array.from({ length: 6 }).map((_, idx) => (
                <div key={idx} className="verification-code-box">
                  {verificationCode[idx] || ''}
                </div>
              ))}
            </div>
            <button
              type="submit"
              disabled={loading || verificationCode.length !== 6}
              className="login-button"
            >
              {loading ? 'Verifying...' : 'Verify Email'}
            </button>
            <button
              type="button"
              onClick={handleResendVerification}
              disabled={resending}
              className="login-button-secondary"
            >
              {resending ? 'Resending...' : "Didn't get a code? Resend email"}
            </button>
          </form>
        ) : showPasswordReset ? (
          // Show different UI based on whether we have a reset token (from email link)
          resetToken ? (
            // Reset password form (user clicked link from email)
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setMessage('');
                setResettingPassword(true);
                try {
                  await axios.post(`${API}/auth/reset-password`, {
                    token: resetToken,
                    new_password: password,
                  });
                  setMessage('✅ Password has been reset. You can now log in.');
                  setShowPasswordReset(false);
                  setResetToken('');
                  setPassword('');
                  setIsLogin(true);
                } catch (err) {
                  const errorMsg = err.response?.data?.detail || err.message || 'Password reset failed';
                  setMessage(`❌ ${errorMsg}`);
                } finally {
                  setResettingPassword(false);
                }
              }}
            >
              <div style={{ marginBottom: '1rem', textAlign: 'center' }}>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                  Enter a new password to complete your reset.
                </p>
              </div>

              <div className="login-form-group">
                <input
                  type="password"
                  placeholder="New password (min 8 characters)"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="login-input"
                />
              </div>

              <button
                type="submit"
                disabled={resettingPassword || password.length < 8}
                className="login-button"
              >
                {resettingPassword ? 'Resetting...' : 'Reset Password'}
              </button>

              <button
                type="button"
                onClick={() => {
                  setShowPasswordReset(false);
                  setResetToken('');
                  setPassword('');
                  setMessage('');
                  setIsLogin(true);
                }}
                className="login-button-secondary"
              >
                Back to Login
              </button>
            </form>
          ) : (
            // Request password reset form (initial "Forgot password?" step)
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setMessage('');
                setSendingReset(true);
                try {
                  await axios.post(`${API}/auth/forgot-password`, { email });
                  setMessage('✅ If this email is registered, a password reset email has been sent. Check your inbox for the reset link.');
                } catch (err) {
                  const errorMsg = err.response?.data?.detail || err.message || 'Failed to send reset email';
                  setMessage(`❌ ${errorMsg}`);
                } finally {
                  setSendingReset(false);
                }
              }}
            >
              <div style={{ marginBottom: '1rem', textAlign: 'center' }}>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                  Enter your email address and we'll send you a link to reset your password.
                </p>
              </div>

              <div className="login-form-group">
                <input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="login-input"
                />
              </div>

              <button
                type="submit"
                disabled={sendingReset || !email}
                className="login-button"
              >
                {sendingReset ? 'Sending...' : 'Send Reset Email'}
              </button>

              <button
                type="button"
                onClick={() => {
                  setShowPasswordReset(false);
                  setEmail('');
                  setMessage('');
                  setIsLogin(true);
                }}
                className="login-button-secondary"
              >
                Back to Login
              </button>
            </form>
          )
        ) : (
          <form onSubmit={handleSubmit}>
          <div className="login-form-group">
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="login-input"
            />
          </div>

          <div className="login-form-group">
            <input
              type="password"
              placeholder="Password (min 8 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="login-input"
            />
          </div>

          {isLogin && (
            <div style={{ marginBottom: '1rem', textAlign: 'right' }}>
              <button
                type="button"
                onClick={() => {
                  setShowPasswordReset(true);
                  setShowVerification(false);
                  setResetToken('');
                  setMessage('');
                }}
                className="login-link"
              >
                Forgot password?
              </button>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="login-button"
          >
            {loading ? 'Please wait...' : (isLogin ? 'Login' : 'Register')}
          </button>
        </form>
        )}

        {!showVerification && !showPasswordReset && (
          <>
            <div className="login-divider">
              <span>OR</span>
            </div>

            <button
              type="button"
              onClick={handleGoogleLogin}
              disabled={loading}
              className="google-button"
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
          </>
        )}

        {message && (
          <div className={`login-message ${message.startsWith('✅') ? 'success' : 'error'}`}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
}

export default Login;

