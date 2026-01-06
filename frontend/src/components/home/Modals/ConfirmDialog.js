import React from 'react';
import { HOPPER_COLORS, rgba, getGradient } from '../../../utils/colors';

/**
 * Confirmation dialog component
 * @param {object} props
 * @param {object|null} props.confirmDialog - Dialog object with title, message, onConfirm, onCancel
 * @param {function} props.setConfirmDialog - Function to set dialog (null to dismiss)
 */
export default function ConfirmDialog({ confirmDialog, setConfirmDialog }) {
  if (!confirmDialog) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: rgba(HOPPER_COLORS.rgb.black, 0.5),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10001,
        animation: 'fadeIn 0.2s ease-out'
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          confirmDialog.onCancel();
        }
      }}
    >
      <div
        className="confirm-dialog"
        style={{
          background: getGradient(HOPPER_COLORS.black, 0.98, 0.98),
          border: `2px solid ${rgba(HOPPER_COLORS.rgb.error, 0.5)}`,
          borderRadius: '16px',
          padding: '2rem',
          minWidth: '400px',
          maxWidth: '500px',
          boxShadow: `0 20px 60px ${rgba(HOPPER_COLORS.rgb.black, 0.5)}`,
          color: 'white',
          animation: 'scaleIn 0.2s ease-out',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1rem' }}>
          <span style={{ fontSize: '2rem', flexShrink: 0 }}>⚠️</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '1.3rem', fontWeight: '700', marginBottom: '0.75rem' }}>
              {confirmDialog.title}
            </div>
            <div style={{ fontSize: '1rem', lineHeight: '1.6', opacity: 0.9 }}>
              {confirmDialog.message}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
          <button
            onClick={confirmDialog.onCancel}
            style={{
              padding: '0.75rem 1.5rem',
              background: rgba(HOPPER_COLORS.rgb.grey, 0.2),
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.grey, 0.4)}`,
              borderRadius: '8px',
              color: 'white',
              cursor: 'pointer',
              fontSize: '1rem',
              fontWeight: '600',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.grey, 0.3);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.grey, 0.6);
            }}
            onMouseLeave={(e) => {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.grey, 0.2);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.grey, 0.4);
            }}
          >
            Cancel
          </button>
          <button
            onClick={confirmDialog.onConfirm}
            style={{
              padding: '0.75rem 1.5rem',
              background: getGradient(HOPPER_COLORS.error, 1.0, 0.9),
              border: `1px solid ${HOPPER_COLORS.error}`,
              borderRadius: '8px',
              color: 'white',
              cursor: 'pointer',
              fontSize: '1rem',
              fontWeight: '600',
              transition: 'all 0.2s',
              boxShadow: `0 4px 12px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`
            }}
            onMouseEnter={(e) => {
              e.target.style.background = getGradient(HOPPER_COLORS.errorDark, 1.0, 1.0);
              e.target.style.transform = 'translateY(-1px)';
              e.target.style.boxShadow = `0 6px 16px ${rgba(HOPPER_COLORS.rgb.error, 0.4)}`;
            }}
            onMouseLeave={(e) => {
              e.target.style.background = getGradient(HOPPER_COLORS.error, 1.0, 0.9);
              e.target.style.transform = 'translateY(0)';
              e.target.style.boxShadow = `0 4px 12px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`;
            }}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
