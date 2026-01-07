import React from 'react';
import { Link } from 'react-router-dom';
import { HOPPER_COLORS, rgba, getGradient } from '../../utils/colors';
import CircularTokenProgress from '../common/CircularTokenProgress';

/**
 * Home header component with title, admin link, token balance, user email, and settings button
 * @param {object} props
 * @param {string} props.appTitle - App title
 * @param {boolean} props.isAdmin - Whether user is admin
 * @param {object} props.user - Current user
 * @param {object} props.tokenBalance - Token balance
 * @param {function} props.setShowAccountSettings - Function to show account settings
 */
export default function HomeHeader({ appTitle, isAdmin, user, tokenBalance, setShowAccountSettings }) {
  return (
    <div className="app-header">
      <h1 className="app-title">🐸 {appTitle}</h1>
      <div className="app-header-right">
        {isAdmin && (
          <Link
            to="/admin"
            className="admin-button-link"
            style={{
              padding: '0.5rem 1rem',
              background: rgba(HOPPER_COLORS.rgb.adminRed, 0.15),
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.3)}`,
              borderRadius: '20px',
              color: HOPPER_COLORS.adminRed,
              textDecoration: 'none',
              fontSize: '0.9rem',
              fontWeight: '500',
              transition: 'all 0.2s',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.25);
              e.currentTarget.style.transform = 'translateY(-2px)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.15);
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            <span>🔐</span>
            <span>Admin</span>
          </Link>
        )}
        <div 
          className="token-balance-indicator"
          style={{
            padding: '0.4rem 0.8rem',
            background: getGradient(HOPPER_COLORS.indigo, 0.15, 0.15),
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.3)}`,
            borderRadius: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
          onClick={() => setShowAccountSettings(true)}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = getGradient(HOPPER_COLORS.indigo, 0.25, 0.25);
            e.currentTarget.style.transform = 'translateY(-2px)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = getGradient(HOPPER_COLORS.indigo, 0.15, 0.15);
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
            border: `1px solid ${HOPPER_COLORS.greyBorder}`,
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
            e.target.style.background = HOPPER_COLORS.lightGreyBg;
            e.target.style.borderColor = HOPPER_COLORS.link;
            e.target.style.color = HOPPER_COLORS.link;
          }}
          onMouseLeave={(e) => {
            e.target.style.background = 'transparent';
            e.target.style.borderColor = HOPPER_COLORS.greyBorder;
            e.target.style.color = HOPPER_COLORS.grey;
          }}
          title="Account Settings"
        >
          ⚙️
        </button>
      </div>
    </div>
  );
}
