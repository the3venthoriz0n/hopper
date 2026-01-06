import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * YouTube destination component
 * @param {object} props
 */
export default function YouTubeDestination({
  youtube,
  youtubeSettings,
  showSettings,
  setShowSettings,
  connectYoutube,
  disconnectYoutube,
  toggleYoutube,
  updateYoutubeSettings,
  setYoutubeSettings,
}) {
  const getStatusColor = () => {
    if (!youtube.connected) return HOPPER_COLORS.error;
    if (youtube.token_expired) return HOPPER_COLORS.error;
    if (youtube.token_expires_soon) return HOPPER_COLORS.warning;
    return HOPPER_COLORS.tokenGreen;
  };

  const getAccountDisplay = () => {
    if (!youtube.account) return 'Loading account...';
    if (youtube.account.channel_name) {
      return youtube.account.email 
        ? `${youtube.account.channel_name} (${youtube.account.email})`
        : youtube.account.channel_name;
    }
    return youtube.account.email || 'Unknown account';
  };

  return (
    <>
      <div className="destination">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill={HOPPER_COLORS.youtubeRed}/>
            </svg>
            YouTube
          </span>
          <div style={{ 
            width: '10px', 
            height: '10px', 
            borderRadius: '50%', 
            backgroundColor: getStatusColor(),
            flexShrink: 0
          }}></div>
          {youtube.connected && (
            <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
              {getAccountDisplay()}
            </span>
          )}
          {youtube.connected && youtube.token_expired && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expired - reconnect required
            </span>
          )}
          {youtube.connected && !youtube.token_expired && youtube.token_expires_soon && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expires soon
            </span>
          )}
        </div>
        {youtube.connected ? (
          <>
            <label className="toggle">
              <input 
                type="checkbox" 
                checked={youtube.enabled}
                disabled={youtube.token_expired}
                onChange={toggleYoutube}
              />
              <span className="slider"></span>
            </label>
            <button onClick={() => setShowSettings(!showSettings)} className="btn-settings">
              ⚙️
            </button>
          </>
        ) : (
          <button onClick={connectYoutube}>Connect</button>
        )}
      </div>

      {showSettings && youtube.connected && (
        <div className="settings-panel">
          <h3>YouTube Settings</h3>
          
          <div className="setting-group">
            <label>Default Visibility</label>
            <select 
              value={youtubeSettings.visibility}
              onChange={(e) => updateYoutubeSettings('visibility', e.target.value)}
              className="select"
            >
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
            </select>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={youtubeSettings.made_for_kids}
                onChange={(e) => updateYoutubeSettings('made_for_kids', e.target.checked)}
                className="checkbox"
              />
              <span>Made for Kids</span>
            </label>
          </div>

          <div className="setting-group">
            <label>
              YouTube Title Template (Override) <span className="char-counter">{youtubeSettings.title_template?.length || 0}/100</span>
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Override global title template for YouTube only. Leave empty to use global</span>
              </span>
            </label>
            <input 
              type="text"
              value={youtubeSettings.title_template || ''}
              onChange={(e) => setYoutubeSettings({...youtubeSettings, title_template: e.target.value})}
              onBlur={(e) => updateYoutubeSettings('title_template', e.target.value)}
              placeholder="Leave empty to use global template"
              className="input-text"
              maxLength="100"
            />
          </div>

          <div className="setting-group">
            <label>
              YouTube Description Template (Override)
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Override global description template for YouTube only. Leave empty to use global</span>
              </span>
            </label>
            <textarea 
              value={youtubeSettings.description_template || ''}
              onChange={(e) => setYoutubeSettings({...youtubeSettings, description_template: e.target.value})}
              onBlur={(e) => updateYoutubeSettings('description_template', e.target.value)}
              placeholder="Leave empty to use global template"
              className="textarea-text"
              rows="3"
            />
          </div>

          <div className="setting-group">
            <label>
              Video Tags Template
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Comma-separated tags. Use {'{filename}'} or {'{random}'}</span>
              </span>
            </label>
            <input 
              type="text"
              value={youtubeSettings.tags_template}
              onChange={(e) => setYoutubeSettings({...youtubeSettings, tags_template: e.target.value})}
              onBlur={(e) => updateYoutubeSettings('tags_template', e.target.value)}
              placeholder="tag1, tag2, tag3"
              className="input-text"
            />
          </div>

          <div className="setting-divider"></div>
          
          <div className="setting-group">
            <button onClick={disconnectYoutube} className="btn-logout" style={{
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
