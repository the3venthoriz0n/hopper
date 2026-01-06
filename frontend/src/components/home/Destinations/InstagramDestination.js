import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * Instagram destination component
 * @param {object} props
 */
export default function InstagramDestination({
  instagram,
  instagramSettings,
  showInstagramSettings,
  setShowInstagramSettings,
  connectInstagram,
  disconnectInstagram,
  toggleInstagram,
  updateInstagramSettings,
  setInstagramSettings,
}) {
  const getStatusColor = () => {
    if (!instagram.connected) return HOPPER_COLORS.error;
    if (instagram.token_expired) return HOPPER_COLORS.error;
    if (instagram.token_expires_soon) return HOPPER_COLORS.warning;
    return HOPPER_COLORS.tokenGreen;
  };

  const getAccountDisplay = () => {
    if (!instagram.account) return 'Loading account...';
    if (instagram.account.username) {
      return `@${instagram.account.username}`;
    }
    return instagram.account.user_id 
      ? `Account (${instagram.account.user_id})` 
      : 'Unknown account';
  };

  return (
    <>
      <div className="destination">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" fill={HOPPER_COLORS.instagramPink}/>
            </svg>
            Instagram
          </span>
          <div style={{ 
            width: '10px', 
            height: '10px', 
            borderRadius: '50%', 
            backgroundColor: getStatusColor(),
            flexShrink: 0
          }}></div>
          {instagram.connected && (
            <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
              {getAccountDisplay()}
            </span>
          )}
          {instagram.connected && instagram.token_expired && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expired - reconnect required
            </span>
          )}
          {instagram.connected && !instagram.token_expired && instagram.token_expires_soon && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expires soon
            </span>
          )}
        </div>
        {instagram.connected ? (
          <>
            <label className="toggle">
              <input 
                type="checkbox" 
                checked={instagram.enabled}
                disabled={instagram.token_expired}
                onChange={toggleInstagram}
              />
              <span className="slider"></span>
            </label>
            <button onClick={() => setShowInstagramSettings(!showInstagramSettings)} className="btn-settings">
              ⚙️
            </button>
          </>
        ) : (
          <button onClick={connectInstagram}>Connect</button>
        )}
      </div>

      {showInstagramSettings && instagram.connected && (
        <div className="settings-panel">
          <h3>Instagram Settings</h3>
          
          <div className="setting-group">
            <label>
              Caption Template (Override) <span className="char-counter">{instagramSettings.caption_template?.length || 0}/2200</span>
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Override global title template for Instagram only. This is the video caption (max 2200 characters). Leave empty to use global</span>
              </span>
            </label>
            <input 
              type="text"
              value={instagramSettings.caption_template || ''}
              onChange={(e) => setInstagramSettings({...instagramSettings, caption_template: e.target.value})}
              onBlur={(e) => updateInstagramSettings('caption_template', e.target.value)}
              placeholder="Leave empty to use global template"
              className="input-text"
              maxLength="2200"
            />
          </div>

          <div className="setting-group">
            <label>
              Media Type
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Choose whether to post as a Reel or regular Video feed post</span>
              </span>
            </label>
            <select
              value={instagramSettings.media_type || 'REELS'}
              onChange={(e) => updateInstagramSettings('media_type', e.target.value)}
              className="select"
            >
              <option value="REELS">Reels</option>
              <option value="VIDEO">Video (Feed Post)</option>
            </select>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={instagramSettings.share_to_feed ?? true}
                onChange={(e) => updateInstagramSettings('share_to_feed', e.target.checked)}
                className="checkbox"
                disabled={(instagramSettings.media_type || 'REELS') !== 'REELS'}
              />
              <span>Share Reel to Feed</span>
              <span className="tooltip-wrapper" style={{ marginLeft: '8px' }}>
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">When enabled, your Reel will also appear in your feed (only applies to Reels)</span>
              </span>
            </label>
          </div>

          <div className="setting-group">
            <label>
              Cover Image URL (Optional)
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">URL to a custom thumbnail image for your video</span>
              </span>
            </label>
            <input 
              type="text"
              value={instagramSettings.cover_url || ''}
              onChange={(e) => setInstagramSettings({...instagramSettings, cover_url: e.target.value})}
              onBlur={(e) => updateInstagramSettings('cover_url', e.target.value)}
              placeholder="https://example.com/image.jpg (optional)"
              className="input-text"
            />
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={instagramSettings.disable_comments}
                onChange={(e) => updateInstagramSettings('disable_comments', e.target.checked)}
                className="checkbox"
              />
              <span>Disable Comments</span>
            </label>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={instagramSettings.disable_likes}
                onChange={(e) => updateInstagramSettings('disable_likes', e.target.checked)}
                className="checkbox"
              />
              <span>Disable Likes</span>
            </label>
          </div>
          
          <div className="setting-divider"></div>
          
          <div className="setting-group">
            <button onClick={disconnectInstagram} className="btn-logout" style={{
              width: '100%',
              padding: '0.75rem',
              background: rgba(HOPPER_COLORS.rgb.adminRed, 0.1),
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.3)}`,
              borderRadius: '6px',
              color: HOPPER_COLORS.adminRed,
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: '500',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.2);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.5);
            }}
            onMouseLeave={(e) => {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.1);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.3);
            }}>
              Log Out
            </button>
          </div>
        </div>
      )}
    </>
  );
}
