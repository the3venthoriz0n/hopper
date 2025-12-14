import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

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
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [limit] = useState(50);
  const [transactions, setTransactions] = useState([]);
  const [showTransactions, setShowTransactions] = useState(false);

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
      loadUserDetails(userId);
      loadUsers();
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

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    loadUsers();
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%)',
      color: '#e0e0e0',
      padding: '2rem',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '2rem'
        }}>
          <h1 style={{ color: '#fff', margin: 0, fontSize: '2rem' }}>🔐 Admin Dashboard</h1>
          <button
            onClick={() => navigate('/')}
            style={{
              padding: '0.5rem 1rem',
              background: 'rgba(255, 255, 255, 0.1)',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              borderRadius: '6px',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '0.9rem'
            }}
          >
            ← Back to App
          </button>
        </div>

        {message && (
          <div style={{
            padding: '1rem',
            marginBottom: '1rem',
            background: message.includes('✅') ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
            border: `1px solid ${message.includes('✅') ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)'}`,
            borderRadius: '6px',
            color: message.includes('✅') ? '#4ade80' : '#ef4444'
          }}>
            {message}
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
                      <div style={{ fontSize: '0.85rem', color: '#999', marginBottom: '0.5rem' }}>Token Balance</div>
                      <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#818cf8' }}>
                        {userDetails.token_balance?.unlimited 
                          ? '∞ Unlimited' 
                          : userDetails.token_balance?.tokens_remaining ?? 'N/A'}
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
                          fontSize: '0.9rem',
                          marginBottom: '1rem'
                        }}
                      >
                        View Transactions
                      </button>

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

