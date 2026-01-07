import React, { useState } from 'react';
import axios from 'axios';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';
import { getApiUrl } from '../../../services/api';
import CircularTokenProgress from '../../common/CircularTokenProgress';
import ConfirmDialog from './ConfirmDialog';

/**
 * Account settings modal component
 * @param {object} props
 */
export default function AccountSettingsModal({
  showAccountSettings,
  setShowAccountSettings,
  user,
  subscription,
  tokenBalance,
  availablePlans,
  loadingSubscription,
  loadingPlanKey,
  handleLogout,
  handleOpenStripePortal,
  handleUpgrade,
  handleCancelSubscription,
  setShowDeleteConfirm,
  setConfirmDialog,
}) {
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [sendingResetEmail, setSendingResetEmail] = useState(false);
  const [resetEmailSent, setResetEmailSent] = useState(false);
  const [showDangerZone, setShowDangerZone] = useState(false);
  const [confirmDialog, setLocalConfirmDialog] = useState(null);

  const API = getApiUrl();

  const handleSendPasswordReset = async () => {
    if (!user?.email) return;
    
    setSendingResetEmail(true);
    try {
      await axios.post(`${API}/auth/forgot-password`, { email: user.email });
      setResetEmailSent(true);
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to send reset email';
      alert(`❌ ${errorMsg}`);
    } finally {
      setSendingResetEmail(false);
    }
  };

  const handleCancelClick = (currentTokens) => {
    setLocalConfirmDialog({
      title: 'Cancel Subscription?',
      message: `Are you sure you want to cancel your subscription? Your subscription will be canceled immediately and you'll be switched to the free plan. Your current token balance (${currentTokens} tokens) will be preserved.`,
      onConfirm: () => {
        setLocalConfirmDialog(null);
        handleCancelSubscription();
      },
      onCancel: () => setLocalConfirmDialog(null)
    });
  };

  const handleSwitchToFree = (currentTokens, isAlreadyCanceled) => {
    setLocalConfirmDialog({
      title: 'Switch to Free Plan?',
      message: isAlreadyCanceled 
        ? `Switch to the free plan? Your current token balance (${currentTokens} tokens) will be preserved.`
        : `Are you sure you want to switch to the free plan? Your current subscription will be canceled immediately. Your current token balance (${currentTokens} tokens) will be preserved.`,
      onConfirm: () => {
        setLocalConfirmDialog(null);
        handleCancelSubscription();
      },
      onCancel: () => setLocalConfirmDialog(null)
    });
  };

  if (!showAccountSettings) return null;

  return (
    <>
      <div className="modal-overlay" onClick={() => setShowAccountSettings(false)}>
        <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
          <div className="modal-header">
            <h2>⚙️ Account Settings</h2>
            <button onClick={() => setShowAccountSettings(false)} className="btn-close">×</button>
          </div>
          
          <div className="modal-body">
            <div className="form-group" style={{ 
              padding: '1rem', 
              background: rgba(HOPPER_COLORS.rgb.white, 0.05), 
              borderRadius: '8px',
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.1)}`
            }}>
              <div style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginBottom: '0.25rem' }}>Logged in as</div>
              <div style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'center',
                marginBottom: '0.75rem'
              }}>
                <div style={{ fontSize: '1rem', fontWeight: '500', color: HOPPER_COLORS.white }}>{user.email}</div>
                <button
                  type="button"
                  onClick={() => setShowChangePassword(!showChangePassword)}
                  style={{
                    padding: '0.3rem 0.6rem',
                    background: 'transparent',
                    borderRadius: '999px',
                    border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.25)}`,
                    color: HOPPER_COLORS.light,
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
                      <p style={{ color: HOPPER_COLORS.tokenGreen, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
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
                          border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.25)}`,
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
                        onClick={handleSendPasswordReset}
                        disabled={sendingResetEmail}
                        style={{
                          padding: '0.6rem',
                          background: sendingResetEmail ? rgba(HOPPER_COLORS.rgb.tokenGreen, 0.3) : rgba(HOPPER_COLORS.rgb.tokenGreen, 0.4),
                          borderRadius: '6px',
                          border: `1px solid ${rgba(HOPPER_COLORS.rgb.tokenGreen, 0.7)}`,
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
                          border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.25)}`,
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
                  e.target.style.background = rgba(HOPPER_COLORS.rgb.white, 0.05);
                  e.target.style.borderColor = HOPPER_COLORS.grey;
                  e.target.style.color = 'white';
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = 'transparent';
                  e.target.style.borderColor = HOPPER_COLORS.grey;
                  e.target.style.color = HOPPER_COLORS.grey;
                }}
              >
                🚪 Logout
              </button>
            </div>

            <div className="form-group" style={{ 
              padding: '1.5rem', 
              background: rgba(HOPPER_COLORS.rgb.indigo, 0.1), 
              borderRadius: '8px',
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.3)}`
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ color: HOPPER_COLORS.indigo, fontSize: '1.1rem', marginTop: 0, marginBottom: 0 }}>
                  💳 Subscription & Tokens
                </h3>
                {subscription && subscription.plan_type !== 'free' && subscription.status === 'active' && (
                  <button
                    onClick={handleOpenStripePortal}
                    disabled={loadingSubscription}
                    style={{
                      padding: '0.5rem 0.75rem',
                      background: rgba(HOPPER_COLORS.rgb.indigo, 0.2),
                      border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.5)}`,
                      borderRadius: '6px',
                      color: HOPPER_COLORS.indigo,
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
                        e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.3);
                        e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.7)}`;
                        e.currentTarget.style.transform = 'translateY(-1px)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!loadingSubscription) {
                        e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.2);
                        e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.5)}`;
                        e.currentTarget.style.transform = 'translateY(0)';
                      }
                    }}
                    title="Manage subscription in Stripe"
                  >
                    ⚙️ Manage
                  </button>
                )}
              </div>
              
              <div style={{
                padding: '1rem',
                background: rgba(HOPPER_COLORS.rgb.black, 0.2),
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

              {availablePlans.filter(plan => !plan.hidden && plan.tokens !== -1).length > 0 && (
                <div id="subscription-plans" style={{ marginBottom: '1rem' }}>
                  <div style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginBottom: '0.75rem' }}>
                    Available Plans
                  </div>
                  {!subscription && (
                    <div style={{ 
                      padding: '0.75rem', 
                      marginBottom: '0.5rem',
                      background: rgba(HOPPER_COLORS.rgb.adminRed, 0.1),
                      border: `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.3)}`,
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
                      const isThisPlanLoading = loadingPlanKey === plan.key;
                      
                      const getPriceDisplay = () => {
                        if (plan.key === 'free') return 'Free';
                        if (plan.tokens === -1) return plan.price?.formatted || '';
                        const monthlyFee = plan.price?.amount_dollars || 0;
                        const overagePrice = plan.overage_price?.amount_dollars;
                        if (overagePrice !== undefined && overagePrice !== null) {
                          const overageCents = (overagePrice * 100).toFixed(1);
                          return `$${monthlyFee.toFixed(2)}/month (${overageCents}c /token)`;
                        }
                        return `$${monthlyFee.toFixed(2)}/month`;
                      };
                      
                      return (
                        <div 
                          key={plan.key}
                          onClick={canUpgrade && !isThisPlanLoading ? () => handleUpgrade(plan.key) : undefined}
                          style={{
                            padding: '0.75rem',
                            background: isCurrent ? rgba(HOPPER_COLORS.rgb.indigo, 0.2) : rgba(HOPPER_COLORS.rgb.white, 0.05),
                            border: isCurrent ? `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.5)}` : `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.1)}`,
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
                              e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.15);
                              e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.6)}`;
                              e.currentTarget.style.transform = 'translateY(-2px)';
                              e.currentTarget.style.boxShadow = `0 4px 12px ${rgba(HOPPER_COLORS.rgb.indigo, 0.3)}`;
                            }
                          }}
                          onMouseLeave={(e) => {
                            if (canUpgrade) {
                              e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.white, 0.05);
                              e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.1)}`;
                              e.currentTarget.style.transform = 'translateY(0)';
                              e.currentTarget.style.boxShadow = 'none';
                            }
                          }}
                        >
                          <div>
                            <div style={{ 
                              fontSize: '0.95rem', 
                              fontWeight: '600', 
                              color: HOPPER_COLORS.white,
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.5rem'
                            }}>
                              <span>{plan.name}</span>
                              {plan.price && (
                                <span style={{ 
                                  fontSize: '0.85rem', 
                                  fontWeight: '500', 
                                  color: HOPPER_COLORS.indigoLight
                                }}>
                                  {getPriceDisplay()}
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
                                background: rgba(HOPPER_COLORS.rgb.tokenGreen, 0.2),
                                color: HOPPER_COLORS.tokenGreen,
                                borderRadius: '4px',
                                fontWeight: '600'
                              }}>
                                CURRENT
                              </span>
                              {subscription && subscription.plan_type !== 'free' && subscription.plan_type !== 'free_daily' && subscription.status === 'active' && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancelClick(tokenBalance?.tokens_remaining || 0);
                                  }}
                                  disabled={loadingSubscription}
                                  style={{
                                    padding: '0.5rem 0.75rem',
                                    background: rgba(HOPPER_COLORS.rgb.adminRed, 0.2),
                                    border: `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.5)}`,
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
                                      e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.3);
                                      e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.7)}`;
                                    }
                                  }}
                                  onMouseLeave={(e) => {
                                    if (!loadingSubscription) {
                                      e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.2);
                                      e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.5)}`;
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
                              background: rgba(HOPPER_COLORS.rgb.indigo, 0.3),
                              color: HOPPER_COLORS.indigo,
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
                                background: rgba(HOPPER_COLORS.rgb.indigo, 0.5),
                                border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.7)}`,
                                borderRadius: '4px',
                                color: HOPPER_COLORS.white,
                                cursor: isThisPlanLoading ? 'not-allowed' : 'pointer',
                                fontSize: '0.75rem',
                                fontWeight: '600',
                                transition: 'all 0.2s ease',
                                opacity: isThisPlanLoading ? 0.6 : 1
                              }}
                              onMouseEnter={(e) => {
                                if (!isThisPlanLoading) {
                                  e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.7);
                                  e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.9)}`;
                                }
                              }}
                              onMouseLeave={(e) => {
                                if (!isThisPlanLoading) {
                                  e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.5);
                                  e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.7)}`;
                                }
                              }}
                            >
                              {isThisPlanLoading ? '⏳' : 'Select Plan'}
                            </button>
                          ) : plan.key === 'free' && subscription && subscription.plan_type !== 'free' ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSwitchToFree(tokenBalance?.tokens_remaining || 0, subscription.status === 'canceled');
                              }}
                              disabled={loadingSubscription}
                              style={{
                                padding: '0.5rem 0.75rem',
                                background: rgba(HOPPER_COLORS.rgb.indigo, 0.2),
                                border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.5)}`,
                                borderRadius: '4px',
                                color: HOPPER_COLORS.indigo,
                                cursor: loadingSubscription ? 'not-allowed' : 'pointer',
                                fontSize: '0.75rem',
                                fontWeight: '600',
                                transition: 'all 0.2s ease',
                                opacity: loadingSubscription ? 0.6 : 1
                              }}
                              onMouseEnter={(e) => {
                                if (!loadingSubscription) {
                                  e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.3);
                                  e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.7)}`;
                                }
                              }}
                              onMouseLeave={(e) => {
                                if (!loadingSubscription) {
                                  e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.indigo, 0.2);
                                  e.currentTarget.style.border = `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.5)}`;
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
                  <p style={{ color: HOPPER_COLORS.grey, marginTop: '1rem', marginBottom: '1rem', fontSize: '0.9rem', lineHeight: '1.5' }}>
                    Once you delete your account, there is no going back. This will permanently delete:
                  </p>
                  <ul style={{ color: HOPPER_COLORS.grey, marginBottom: '1rem', fontSize: '0.85rem', paddingLeft: '1.25rem', lineHeight: '1.6' }}>
                    <li>Your account and login credentials</li>
                    <li>All uploaded videos and files</li>
                    <li>All settings and preferences</li>
                    <li>All connected accounts (YouTube, TikTok, Instagram)</li>
                  </ul>
                  <button 
                    onClick={() => {
                      setShowAccountSettings(false);
                      setShowDeleteConfirm(true);
                    }}
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
      {confirmDialog && (
        <ConfirmDialog 
          confirmDialog={confirmDialog} 
          setConfirmDialog={setLocalConfirmDialog}
        />
      )}
    </>
  );
}

