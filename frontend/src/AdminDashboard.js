import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import './App.css';

// Circular Progress Component for Token Usage
const CircularTokenProgress = ({ tokensRemaining, tokensUsed, monthlyTokens, overageTokens, unlimited, isLoading }) => {
  if (unlimited) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          background: 'conic-gradient(from 0deg, #10b981 0deg 360deg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative'
        }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: '#0a0a0a',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1rem',
            fontWeight: '700',
            color: '#10b981'
          }}>
            ∞
          </div>
        </div>
        <div style={{ fontSize: '0.6rem', color: '#999', textAlign: 'center' }}>Unlimited</div>
      </div>
    );
  }

  // monthlyTokens = starting balance for period (plan + granted tokens)
  const effectiveMonthlyTokens = monthlyTokens || 0;
  
  // Calculate percentage: tokensUsed / monthlyTokens
  const percentage = effectiveMonthlyTokens > 0 ? (tokensUsed / effectiveMonthlyTokens) * 100 : 0;
  const hasOverage = overageTokens > 0;
  
  // Color based on usage - red when in overage, amber when high usage, green otherwise
  let progressColor = '#10b981'; // green
  if (hasOverage) {
    progressColor = '#ef4444'; // red when in overage
  } else if (percentage >= 90) {
    progressColor = '#f59e0b'; // amber when 90% or more used
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
            stroke="rgba(255, 255, 255, 0.1)"
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
          gap: '0.05rem'
        }}>
          <div style={{ fontSize: '0.65rem', fontWeight: '700', color: isLoading ? '#666' : '#fff', lineHeight: '1' }}>
            {tokensUsed}
          </div>
          <div style={{ fontSize: '0.5rem', color: isLoading ? '#444' : '#999', lineHeight: '1' }}>
            / {effectiveMonthlyTokens}
          </div>
        </div>
      </div>
    </div>
  );
};

// Get CSRF token from axios interceptor
let csrfToken = null;

// Intercept responses to extract CSRF token
axios.interceptors.response.use(
  (response) => {
    const token = response.headers['x-csrf-token'] || response.headers['X-CSRF-Token'];
    if (token) {
      csrfToken = token;
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/';
    }
    return Promise.reject(error);
  }
);

// Intercept requests to add CSRF token to ALL requests (including GET for admin endpoints)
axios.interceptors.request.use(
  (config) => {
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

function AdminDashboard() {
  const navigate = useNavigate();
  
  const getApiUrl = () => {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
    return `${backendUrl}/api`;
  };
  
  const API = getApiUrl();
  
  const [users, setUsers] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userDetails, setUserDetails] = useState(null);
  const [tokenAmount, setTokenAmount] = useState('');
  const [grantReason, setGrantReason] = useState('');
  const [deductAmount, setDeductAmount] = useState('');
  const [deductReason, setDeductReason] = useState('');
  const [deductResult, setDeductResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [limit] = useState(50);
  const [transactions, setTransactions] = useState([]);
  const [showTransactions, setShowTransactions] = useState(false);
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserIsAdmin, setNewUserIsAdmin] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [userToDelete, setUserToDelete] = useState(null);
  const [resetPassword, setResetPassword] = useState('');
  const [availablePlans, setAvailablePlans] = useState([]);

  // Fetch CSRF token on mount
  useEffect(() => {
    const fetchCsrfToken = async () => {
      try {
        const response = await axios.get(`${API}/auth/csrf`, { withCredentials: true });
        if (response.headers['x-csrf-token'] || response.headers['X-CSRF-Token']) {
          csrfToken = response.headers['x-csrf-token'] || response.headers['X-CSRF-Token'];
        }
      } catch (err) {
        console.error('Failed to fetch CSRF token:', err);
      }
    };
    fetchCsrfToken();
  }, []);

  // Load users when page or searchTerm changes
  useEffect(() => {
    loadUsers();
  }, [page, searchTerm]);

  // Load available plans on mount
  useEffect(() => {
    loadPlans();
  }, []);

  const loadPlans = async () => {
    try {
      const res = await axios.get(`${API}/subscription/plans`);
      setAvailablePlans(res.data.plans || []);
    } catch (err) {
      console.error('Failed to load plans:', err);
    }
  };

  const loadUsers = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        page: page.toString(),
        limit: limit.toString()
      });
      if (searchTerm) {
        params.append('search', searchTerm);
      }
      const response = await axios.get(`${API}/admin/users?${params.toString()}`, {
        headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
        withCredentials: true
      });
      setUsers(response.data.users);
      setTotal(response.data.total);
    } catch (err) {
      if (err.response?.status === 403 || err.response?.status === 401) {
        setMessage('❌ Admin access required');
        setTimeout(() => navigate('/'), 2000);
      } else {
        setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
      }
    } finally {
      setLoading(false);
    }
  };

  const loadUserDetails = async (userId) => {
    try {
      setLoading(true);
      const response = await axios.get(`${API}/admin/users/${userId}`, {
        headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
        withCredentials: true
      });
      setUserDetails(response.data);
      setSelectedUser(response.data.user);
    } catch (err) {
      setMessage(`❌ Error loading user details: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const loadTransactions = async (userId) => {
    try {
      setLoading(true);
      const response = await axios.get(`${API}/admin/users/${userId}/transactions?limit=50`, {
        headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
        withCredentials: true
      });
      setTransactions(response.data.transactions);
      setShowTransactions(true);
    } catch (err) {
      setMessage(`❌ Error loading transactions: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleGrantTokens = async (userId) => {
    if (!tokenAmount || parseInt(tokenAmount) <= 0) {
      setMessage('❌ Please enter a valid token amount');
      return;
    }

    setLoading(true);
    try {
      await axios.post(
        `${API}/admin/users/${userId}/grant-tokens`,
        { amount: parseInt(tokenAmount), reason: grantReason },
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage(`✅ Granted ${tokenAmount} tokens`);
      setTokenAmount('');
      setGrantReason('');
      await loadUserDetails(userId);
      await loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDeductTokens = async (userId) => {
    if (!deductAmount || parseInt(deductAmount) <= 0) {
      setMessage('❌ Please enter a valid token amount');
      return;
    }

    setLoading(true);
    setDeductResult(null);
    try {
      const response = await axios.post(
        `${API}/admin/users/${userId}/deduct-tokens`,
        { amount: parseInt(deductAmount), reason: deductReason },
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage(`✅ Deducted ${deductAmount} tokens`);
      setDeductResult(response.data.transaction);
      setDeductAmount('');
      setDeductReason('');
      await loadUserDetails(userId);
      await loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleUnlimitedPlan = async (userId, enroll) => {
    setLoading(true);
    try {
      if (enroll) {
        await axios.post(
          `${API}/admin/users/${userId}/unlimited-plan`,
          {},
          { 
            headers: { 'X-CSRF-Token': csrfToken },
            withCredentials: true
          }
        );
        setMessage(`✅ Enrolled user in unlimited plan`);
      } else {
        await axios.delete(
          `${API}/admin/users/${userId}/unlimited-plan`,
          { 
            headers: { 'X-CSRF-Token': csrfToken },
            withCredentials: true
          }
        );
        setMessage(`✅ Unenrolled user from unlimited plan`);
      }
      loadUserDetails(userId);
      loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSwitchPlan = async (userId, planKey) => {
    setLoading(true);
    try {
      const res = await axios.post(
        `${API}/admin/users/${userId}/switch-plan`,
        { plan_key: planKey },
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage(`✅ ${res.data.message || `Switched user to ${planKey} plan`}`);
      loadUserDetails(userId);
      loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    if (!newUserEmail || !newUserPassword) {
      setMessage('❌ Please fill in all required fields');
      return;
    }
    if (newUserPassword.length < 8) {
      setMessage('❌ Password must be at least 8 characters long');
      return;
    }

    setLoading(true);
    try {
      await axios.post(
        `${API}/admin/users`,
        {
          email: newUserEmail,
          password: newUserPassword,
          is_admin: newUserIsAdmin
        },
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage(`✅ User ${newUserEmail} created successfully`);
      setNewUserEmail('');
      setNewUserPassword('');
      setNewUserIsAdmin(false);
      setShowCreateUser(false);
      loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async () => {
    if (!userToDelete) return;
    
    setLoading(true);
    try {
      await axios.delete(
        `${API}/admin/users/${userToDelete.id}`,
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage(`✅ User ${userToDelete.email} deleted successfully`);
      setShowDeleteConfirm(false);
      setUserToDelete(null);
      setSelectedUser(null);
      setUserDetails(null);
      loadUsers();
    } catch (err) {
      setMessage(`❌ Error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const confirmDelete = (user) => {
    setUserToDelete(user);
    setShowDeleteConfirm(true);
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    loadUsers();
  };

  const handleResetPassword = async (userId) => {
    if (!resetPassword || resetPassword.length < 8) {
      setMessage('❌ New password must be at least 8 characters long');
      return;
    }

    setLoading(true);
    try {
      await axios.post(
        `${API}/admin/users/${userId}/reset-password`,
        { password: resetPassword },
        { 
          headers: { 'X-CSRF-Token': csrfToken },
          withCredentials: true
        }
      );
      setMessage('✅ Password reset successfully');
      setResetPassword('');
    } catch (err) {
      setMessage(`❌ Error resetting password: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-container">
      <div className="admin-wrapper">
        <div className="admin-header">
          <h1 className="admin-title">🔐 Admin Dashboard</h1>
          <button
            onClick={() => navigate('/app')}
            className="admin-button"
          >
            ← Back to App
          </button>
        </div>

        {message && (
          <div className={`admin-message ${message.includes('✅') ? 'success' : 'error'}`}>
            {message}
          </div>
        )}

        {/* Create User Section */}
        <div className="admin-card">
          <div className="admin-card-header">
            <h2 className="admin-card-title">Create User</h2>
            <button
              onClick={() => setShowCreateUser(!showCreateUser)}
              className={`admin-button ${showCreateUser ? 'admin-button-danger' : 'admin-button-primary'}`}
            >
              {showCreateUser ? 'Cancel' : '+ Create User'}
            </button>
          </div>

          {showCreateUser && (
            <form onSubmit={handleCreateUser} className="admin-form">
              <input
                type="email"
                value={newUserEmail}
                onChange={(e) => setNewUserEmail(e.target.value)}
                placeholder="Email address"
                required
                className="admin-input"
              />
              <input
                type="password"
                value={newUserPassword}
                onChange={(e) => setNewUserPassword(e.target.value)}
                placeholder="Password (min 8 characters)"
                required
                minLength={8}
                className="admin-input"
              />
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-primary)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={newUserIsAdmin}
                  onChange={(e) => setNewUserIsAdmin(e.target.checked)}
                  style={{ cursor: 'pointer' }}
                />
                <span style={{ fontSize: '0.9rem' }}>Make this user an admin</span>
              </label>
              <button
                type="submit"
                disabled={loading || !newUserEmail || !newUserPassword}
                className="admin-button admin-button-primary"
                style={{ opacity: (loading || !newUserEmail || !newUserPassword) ? 0.6 : 1, cursor: (loading || !newUserEmail || !newUserPassword) ? 'not-allowed' : 'pointer' }}
              >
                {loading ? 'Creating...' : 'Create User'}
              </button>
            </form>
          )}
        </div>

        {/* Delete Confirmation Dialog */}
        {showDeleteConfirm && userToDelete && (
          <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'var(--bg-overlay)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000
          }}>
            <div style={{
              background: 'rgba(30, 30, 46, 0.95)',
              borderRadius: '8px',
              padding: '2rem',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              maxWidth: '400px',
              width: '90%'
            }}>
              <h3 style={{ color: '#fff', marginTop: 0, marginBottom: '1rem' }}>Confirm Delete</h3>
              <p style={{ color: '#e0e0e0', marginBottom: '1.5rem' }}>
                Are you sure you want to delete user <strong style={{ color: '#fff' }}>{userToDelete.email}</strong>?
                <br />
                <span style={{ color: '#ef4444', fontSize: '0.85rem' }}>This action cannot be undone.</span>
              </p>
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    setUserToDelete(null);
                  }}
                  disabled={loading}
                  style={{
                    padding: '0.5rem 1rem',
                    background: 'rgba(255, 255, 255, 0.1)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '4px',
                    color: '#fff',
                    cursor: loading ? 'not-allowed' : 'pointer',
                    fontSize: '0.9rem'
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleDeleteUser}
                  disabled={loading}
                  style={{
                    padding: '0.5rem 1rem',
                    background: 'rgba(239, 68, 68, 0.5)',
                    border: '1px solid rgba(239, 68, 68, 0.7)',
                    borderRadius: '4px',
                    color: '#fff',
                    cursor: loading ? 'not-allowed' : 'pointer',
                    fontSize: '0.9rem',
                    fontWeight: '500'
                  }}
                >
                  {loading ? 'Deleting...' : 'Delete User'}
                </button>
              </div>
            </div>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
          {/* Users List */}
          <div style={{
            background: 'rgba(255, 255, 255, 0.05)',
            borderRadius: '8px',
            padding: '1.5rem',
            border: '1px solid rgba(255, 255, 255, 0.1)'
          }}>
            <h2 style={{ color: '#fff', marginTop: 0, marginBottom: '1rem' }}>Users</h2>
            
            <form onSubmit={handleSearch} style={{ marginBottom: '1rem' }}>
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search by email..."
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  background: 'rgba(0, 0, 0, 0.3)',
                  border: '1px solid rgba(255, 255, 255, 0.2)',
                  borderRadius: '4px',
                  color: '#fff',
                  fontSize: '0.9rem'
                }}
              />
            </form>

            {loading && <div style={{ color: '#999', textAlign: 'center', padding: '1rem' }}>Loading...</div>}
            
            <div style={{ maxHeight: '600px', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)' }}>
                    <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999', fontSize: '0.85rem' }}>ID</th>
                    <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999', fontSize: '0.85rem' }}>Email</th>
                    <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999', fontSize: '0.85rem' }}>Plan</th>
                    <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999', fontSize: '0.85rem' }}>Admin</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(user => (
                    <tr 
                      key={user.id}
                      onClick={() => loadUserDetails(user.id)}
                      style={{
                        cursor: 'pointer',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                        background: selectedUser?.id === user.id ? 'rgba(99, 102, 241, 0.2)' : 'transparent'
                      }}
                      onMouseEnter={(e) => {
                        if (selectedUser?.id !== user.id) {
                          e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (selectedUser?.id !== user.id) {
                          e.currentTarget.style.background = 'transparent';
                        }
                      }}
                    >
                      <td style={{ padding: '0.75rem', fontSize: '0.9rem' }}>{user.id}</td>
                      <td style={{ padding: '0.75rem', fontSize: '0.9rem' }}>{user.email}</td>
                      <td style={{ padding: '0.75rem', fontSize: '0.9rem', textTransform: 'capitalize' }}>
                        {user.plan_type || 'N/A'}
                      </td>
                      <td style={{ padding: '0.75rem', fontSize: '0.9rem' }}>
                        {user.is_admin ? '✅' : '❌'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {total > limit && (
              <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{
                    padding: '0.5rem 1rem',
                    background: page === 1 ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.3)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '4px',
                    color: '#fff',
                    cursor: page === 1 ? 'not-allowed' : 'pointer',
                    fontSize: '0.9rem'
                  }}
                >
                  Previous
                </button>
                <span style={{ color: '#999', fontSize: '0.9rem' }}>
                  Page {page} of {Math.ceil(total / limit)}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(Math.ceil(total / limit), p + 1))}
                  disabled={page >= Math.ceil(total / limit)}
                  style={{
                    padding: '0.5rem 1rem',
                    background: page >= Math.ceil(total / limit) ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.3)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '4px',
                    color: '#fff',
                    cursor: page >= Math.ceil(total / limit) ? 'not-allowed' : 'pointer',
                    fontSize: '0.9rem'
                  }}
                >
                  Next
                </button>
              </div>
            )}
          </div>

          {/* User Details */}
          <div style={{
            background: 'rgba(255, 255, 255, 0.05)',
            borderRadius: '8px',
            padding: '1.5rem',
            border: '1px solid rgba(255, 255, 255, 0.1)'
          }}>
            {selectedUser ? (
              <>
                <h2 style={{ color: '#fff', marginTop: 0, marginBottom: '1rem' }}>
                  User: {selectedUser.email}
                </h2>

                {userDetails && (
                  <>
                    <div style={{ marginBottom: '1.5rem' }}>
                      <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.75rem' }}>Token Balance</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem' }}>
                        <CircularTokenProgress
                          tokensRemaining={userDetails.token_balance?.tokens_remaining ?? 0}
                          tokensUsed={userDetails.token_usage?.tokens_used_this_period ?? 0}
                          monthlyTokens={userDetails.token_balance?.monthly_tokens ?? 0}
                          overageTokens={userDetails.token_balance?.overage_tokens ?? 0}
                          unlimited={userDetails.token_balance?.unlimited ?? false}
                          isLoading={loading}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '0.9rem', color: '#fff', marginBottom: '0.25rem' }}>
                            Remaining: <span style={{ color: '#818cf8', fontWeight: '600' }}>
                              {userDetails.token_balance?.unlimited 
                                ? '∞ Unlimited' 
                                : userDetails.token_balance?.tokens_remaining ?? 'N/A'}
                            </span>
                          </div>
                          {userDetails.token_balance?.overage_tokens > 0 && (
                            <div style={{ fontSize: '0.85rem', color: '#fbbf24', marginTop: '0.25rem' }}>
                              Overage: {userDetails.token_balance.overage_tokens} tokens
                            </div>
                          )}
                        </div>
                      </div>
                      {userDetails.subscription && (
                        <div style={{ fontSize: '0.85rem', color: '#999', marginTop: '0.5rem' }}>
                          Plan: {userDetails.subscription.plan_type} ({userDetails.subscription.status})
                        </div>
                      )}
                    </div>

                    {userDetails.token_usage && (
                      <div style={{ marginBottom: '1.5rem', padding: '1rem', background: 'rgba(0, 0, 0, 0.2)', borderRadius: '6px' }}>
                        <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.5rem' }}>Token Usage</div>
                        <div style={{ fontSize: '0.9rem', color: '#fff', marginBottom: '0.25rem' }}>
                          This Period: <span style={{ color: '#818cf8', fontWeight: '600' }}>{userDetails.token_usage.tokens_used_this_period}</span>
                        </div>
                        <div style={{ fontSize: '0.9rem', color: '#fff' }}>
                          Total All Time: <span style={{ color: '#818cf8', fontWeight: '600' }}>{userDetails.token_usage.total_tokens_used}</span>
                        </div>
                      </div>
                    )}

                    <div style={{ marginBottom: '1.5rem' }}>
                      <h3 style={{ color: '#fff', fontSize: '1rem', marginBottom: '0.75rem' }}>Grant Tokens</h3>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <input
                          type="number"
                          value={tokenAmount}
                          onChange={(e) => setTokenAmount(e.target.value)}
                          placeholder="Token amount"
                          style={{
                            padding: '0.5rem',
                            background: 'rgba(0, 0, 0, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            fontSize: '0.9rem'
                          }}
                        />
                        <input
                          type="text"
                          value={grantReason}
                          onChange={(e) => setGrantReason(e.target.value)}
                          placeholder="Reason (optional)"
                          style={{
                            padding: '0.5rem',
                            background: 'rgba(0, 0, 0, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            fontSize: '0.9rem'
                          }}
                        />
                        <button
                          onClick={() => handleGrantTokens(selectedUser.id)}
                          disabled={loading || !tokenAmount}
                          style={{
                            padding: '0.75rem',
                            background: loading || !tokenAmount ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.5)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading || !tokenAmount ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem',
                            fontWeight: '500'
                          }}
                        >
                          Grant Tokens
                        </button>
                      </div>
                    </div>

                    <div style={{ marginBottom: '1.5rem' }}>
                      <h3 style={{ color: '#fff', fontSize: '1rem', marginBottom: '0.75rem' }}>Deduct Tokens (Test Overage)</h3>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <input
                          type="number"
                          value={deductAmount}
                          onChange={(e) => setDeductAmount(e.target.value)}
                          placeholder="Token amount to deduct"
                          style={{
                            padding: '0.5rem',
                            background: 'rgba(0, 0, 0, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            fontSize: '0.9rem'
                          }}
                        />
                        <input
                          type="text"
                          value={deductReason}
                          onChange={(e) => setDeductReason(e.target.value)}
                          placeholder="Reason (optional)"
                          style={{
                            padding: '0.5rem',
                            background: 'rgba(0, 0, 0, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            fontSize: '0.9rem'
                          }}
                        />
                        <button
                          onClick={() => handleDeductTokens(selectedUser.id)}
                          disabled={loading || !deductAmount}
                          style={{
                            padding: '0.75rem',
                            background: loading || !deductAmount ? 'rgba(255, 255, 255, 0.05)' : 'rgba(239, 68, 68, 0.5)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading || !deductAmount ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem',
                            fontWeight: '500'
                          }}
                        >
                          Deduct Tokens
                        </button>
                        {deductResult && (
                          <div style={{
                            marginTop: '0.75rem',
                            padding: '0.75rem',
                            background: 'rgba(0, 0, 0, 0.4)',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            borderRadius: '4px',
                            fontSize: '0.85rem'
                          }}>
                            <div style={{ color: '#fff', marginBottom: '0.5rem', fontWeight: '600' }}>Transaction Details:</div>
                            <div style={{ color: '#ccc', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                              <div>Balance: {deductResult.balance_before} → {deductResult.balance_after}</div>
                              <div>Used: {deductResult.tokens_used_before} → {deductResult.tokens_used_after}</div>
                              <div>Included: {deductResult.included_tokens}</div>
                              <div style={{ color: deductResult.overage_after > 0 ? '#fbbf24' : '#ccc' }}>
                                Overage: {deductResult.overage_before} → {deductResult.overage_after}
                                {deductResult.new_overage > 0 && ` (+${deductResult.new_overage} new)`}
                              </div>
                              {deductResult.triggered_meter_event && (
                                <div style={{ color: '#10b981', fontWeight: '600', marginTop: '0.25rem' }}>
                                  ✅ Meter event triggered for {deductResult.new_overage} overage tokens
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    <div style={{ marginBottom: '1.5rem' }}>
                      <h3 style={{ color: '#fff', fontSize: '1rem', marginBottom: '0.75rem' }}>Reset User Password</h3>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <input
                          type="password"
                          value={resetPassword}
                          onChange={(e) => setResetPassword(e.target.value)}
                          placeholder="New password (min 8 characters)"
                          minLength={8}
                          style={{
                            padding: '0.5rem',
                            background: 'rgba(0, 0, 0, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            fontSize: '0.9rem'
                          }}
                        />
                        <button
                          onClick={() => handleResetPassword(selectedUser.id)}
                          disabled={loading || !resetPassword || resetPassword.length < 8}
                          style={{
                            padding: '0.75rem',
                            background: loading || !resetPassword || resetPassword.length < 8
                              ? 'rgba(255, 255, 255, 0.05)'
                              : 'rgba(239, 68, 68, 0.4)',
                            border: '1px solid rgba(239, 68, 68, 0.7)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading || !resetPassword || resetPassword.length < 8 ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem',
                            fontWeight: '500'
                          }}
                        >
                          Reset Password
                        </button>
                      </div>
                    </div>

                    {/* Plan switching temporarily disabled - requires payment method for paid plans
                    <div style={{ marginBottom: '1.5rem' }}>
                      <h3 style={{ color: '#fff', fontSize: '1rem', marginBottom: '0.75rem' }}>Switch Plan</h3>
                      <div style={{ marginBottom: '0.75rem', color: '#999', fontSize: '0.85rem' }}>
                        Current Plan: <span style={{ color: '#fff', fontWeight: '600', textTransform: 'capitalize' }}>
                          {userDetails.user?.plan_type || 'N/A'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                        {availablePlans.map(plan => {
                          const isCurrentPlan = plan.key === userDetails.user?.plan_type;
                          return (
                            <button
                              key={plan.key}
                              onClick={() => handleSwitchPlan(selectedUser.id, plan.key)}
                              disabled={loading || isCurrentPlan}
                              style={{
                                padding: '0.5rem 1rem',
                                background: loading || isCurrentPlan
                                  ? 'rgba(255, 255, 255, 0.05)'
                                  : 'rgba(99, 102, 241, 0.5)',
                                border: isCurrentPlan 
                                  ? '1px solid rgba(34, 197, 94, 0.5)' 
                                  : '1px solid rgba(255, 255, 255, 0.2)',
                                borderRadius: '4px',
                                color: isCurrentPlan ? '#22c55e' : '#fff',
                                cursor: loading || isCurrentPlan ? 'not-allowed' : 'pointer',
                                fontSize: '0.9rem',
                                fontWeight: '500',
                                textTransform: 'capitalize'
                              }}
                            >
                              {plan.name} {isCurrentPlan ? '(current)' : ''}
                            </button>
                          );
                        })}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#666', fontStyle: 'italic' }}>
                        Note: Overage will be invoiced before switching. Tokens will be preserved.
                      </div>
                    </div>
                    */}

                    <div style={{ marginBottom: '1.5rem' }}>
                      <h3 style={{ color: '#fff', fontSize: '1rem', marginBottom: '0.75rem' }}>Unlimited Plan</h3>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                          onClick={() => handleUnlimitedPlan(selectedUser.id, true)}
                          disabled={loading || userDetails.user?.plan_type === 'unlimited'}
                          style={{
                            padding: '0.5rem 1rem',
                            background: loading || userDetails.user?.plan_type === 'unlimited' ? 'rgba(255, 255, 255, 0.05)' : 'rgba(34, 197, 94, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading || userDetails.user?.plan_type === 'unlimited' ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          Enroll Unlimited Plan
                        </button>
                        <button
                          onClick={() => handleUnlimitedPlan(selectedUser.id, false)}
                          disabled={loading || userDetails.user?.plan_type !== 'unlimited'}
                          style={{
                            padding: '0.5rem 1rem',
                            background: loading || userDetails.user?.plan_type !== 'unlimited' ? 'rgba(255, 255, 255, 0.05)' : 'rgba(239, 68, 68, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading || userDetails.user?.plan_type !== 'unlimited' ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          Unenroll Unlimited Plan
                        </button>
                      </div>
                    </div>

                    <div>
                      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                        <button
                          onClick={() => loadTransactions(selectedUser.id)}
                          disabled={loading}
                          style={{
                            padding: '0.5rem 1rem',
                            background: 'rgba(99, 102, 241, 0.3)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          View Transactions
                        </button>
                        <button
                          onClick={() => confirmDelete(selectedUser)}
                          disabled={loading}
                          style={{
                            padding: '0.5rem 1rem',
                            background: 'rgba(239, 68, 68, 0.3)',
                            border: '1px solid rgba(239, 68, 68, 0.5)',
                            borderRadius: '4px',
                            color: '#fff',
                            cursor: loading ? 'not-allowed' : 'pointer',
                            fontSize: '0.9rem'
                          }}
                        >
                          Delete User
                        </button>
                      </div>

                      {showTransactions && transactions.length > 0 && (
                        <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead>
                              <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.1)' }}>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999' }}>Type</th>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999' }}>Tokens</th>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: '#999' }}>Date</th>
                              </tr>
                            </thead>
                            <tbody>
                              {transactions.map(t => (
                                <tr key={t.id} style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                                  <td style={{ padding: '0.5rem' }}>{t.transaction_type}</td>
                                  <td style={{ padding: '0.5rem', color: t.tokens > 0 ? '#4ade80' : '#ef4444' }}>
                                    {t.tokens > 0 ? '+' : ''}{t.tokens}
                                  </td>
                                  <td style={{ padding: '0.5rem', color: '#999' }}>
                                    {new Date(t.created_at).toLocaleString()}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </>
            ) : (
              <div style={{ color: '#999', textAlign: 'center', padding: '2rem' }}>
                Select a user to view details
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AdminDashboard;

