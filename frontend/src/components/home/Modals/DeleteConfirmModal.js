import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * Delete confirmation modal
 * @param {object} props
 * @param {boolean} props.showDeleteConfirm - Whether modal is visible
 * @param {function} props.setShowDeleteConfirm - Function to set visibility
 * @param {function} props.handleDeleteAccount - Function to handle account deletion
 */
export default function DeleteConfirmModal({ showDeleteConfirm, setShowDeleteConfirm, handleDeleteAccount }) {
  if (!showDeleteConfirm) return null;

  return (
    <div className="modal-overlay" onClick={() => setShowDeleteConfirm(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '450px' }}>
        <div className="modal-header">
          <h2 style={{ color: HOPPER_COLORS.adminRed }}>⚠️ Delete Account</h2>
          <button onClick={() => setShowDeleteConfirm(false)} className="btn-close">×</button>
        </div>
        
        <div className="modal-body">
          <p style={{ marginBottom: '1rem', fontSize: '1rem', lineHeight: '1.6', color: HOPPER_COLORS.white }}>
            Are you absolutely sure you want to delete your account?
          </p>
          <p style={{ marginBottom: '1.5rem', fontSize: '0.9rem', color: HOPPER_COLORS.grey, lineHeight: '1.6' }}>
            This action <strong style={{ color: HOPPER_COLORS.adminRed }}>cannot be undone</strong>. All your data will be permanently deleted.
          </p>
          
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button 
              onClick={() => setShowDeleteConfirm(false)}
              className="btn-cancel"
              style={{ flex: 1 }}
            >
              Cancel
            </button>
            <button 
              onClick={handleDeleteAccount}
              style={{
                flex: 1,
                padding: '0.75rem',
                background: HOPPER_COLORS.adminRed,
                color: HOPPER_COLORS.white,
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '1rem',
                fontWeight: '600',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = HOPPER_COLORS.errorDark;
                e.target.style.transform = 'translateY(-2px)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = HOPPER_COLORS.adminRed;
                e.target.style.transform = 'translateY(0)';
              }}
            >
              Yes, Delete Everything
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
