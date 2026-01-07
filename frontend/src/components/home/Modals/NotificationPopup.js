import React from 'react';
import { HOPPER_COLORS, rgba, getGradient } from '../../../utils/colors';

/**
 * Notification popup component
 * @param {object} props
 * @param {object|null} props.notification - Notification object with type, title, message, videoFilename
 * @param {function} props.setNotification - Function to set notification (null to dismiss)
 * @param {function} props.setShowAccountSettings - Function to show account settings
 */
export default function NotificationPopup({ notification, setNotification, setShowAccountSettings }) {
  if (!notification) return null;

  const getBackgroundGradient = () => {
    if (notification.type === 'error') {
      return getGradient(HOPPER_COLORS.error, 1.0, 0.9);
    } else if (notification.type === 'info') {
      return getGradient(HOPPER_COLORS.info, 1.0, 0.9);
    }
    return getGradient(HOPPER_COLORS.success, 1.0, 0.9);
  };

  const getBorderColor = () => {
    if (notification.type === 'error') return HOPPER_COLORS.error;
    if (notification.type === 'info') return HOPPER_COLORS.info;
    return HOPPER_COLORS.success;
  };

  const getIcon = () => {
    if (notification.type === 'error') return '⚠️';
    if (notification.type === 'info') return 'ℹ️';
    return '✅';
  };

  return (
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
        background: getBackgroundGradient(),
        border: `2px solid ${getBorderColor()}`,
        borderRadius: '12px',
        boxShadow: `0 10px 40px ${rgba(HOPPER_COLORS.rgb.black, 0.3)}`,
        color: HOPPER_COLORS.white,
        animation: 'slideInRight 0.3s ease-out',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', flex: 1 }}>
          <span style={{ fontSize: '1.5rem', flexShrink: 0 }}>
            {getIcon()}
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
            color: HOPPER_COLORS.white,
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
            color: HOPPER_COLORS.white,
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
  );
}
