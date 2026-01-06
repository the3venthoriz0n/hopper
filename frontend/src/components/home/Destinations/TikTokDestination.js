import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * TikTok destination component
 * @param {object} props
 */
export default function TikTokDestination({
  tiktok,
  tiktokSettings,
  tiktokCreatorInfo,
  showTiktokSettings,
  setShowTiktokSettings,
  connectTiktok,
  disconnectTiktok,
  toggleTiktok,
  updateTiktokSettings,
  setTiktokSettings,
}) {
  const getStatusColor = () => {
    if (!tiktok.connected) return HOPPER_COLORS.error;
    if (tiktok.token_expired) return HOPPER_COLORS.error;
    if (tiktok.token_expires_soon) return HOPPER_COLORS.warning;
    return HOPPER_COLORS.tokenGreen;
  };

  const getAccountDisplay = () => {
    if (!tiktok.account) return 'Loading account...';
    if (tiktok.account.display_name) {
      return tiktok.account.username 
        ? `${tiktok.account.display_name} (@${tiktok.account.username})`
        : tiktok.account.display_name;
    }
    return tiktok.account.username ? `@${tiktok.account.username}` : 'Unknown account';
  };

  const privacyLabelMap = {
    'PUBLIC_TO_EVERYONE': 'Everyone',
    'MUTUAL_FOLLOW_FRIENDS': 'Friends',
    'FOLLOWER_OF_CREATOR': 'Followers',
    'SELF_ONLY': 'Only you'
  };

  return (
    <>
      <div className="destination">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" fill={HOPPER_COLORS.white}/>
            </svg>
            TikTok
          </span>
          <div style={{ 
            width: '10px', 
            height: '10px', 
            borderRadius: '50%', 
            backgroundColor: getStatusColor(),
            flexShrink: 0
          }}></div>
          {tiktok.connected && (
            <span className="account-info" style={{ fontSize: '0.9em', color: HOPPER_COLORS.grey, marginLeft: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
              {getAccountDisplay()}
            </span>
          )}
          {tiktok.connected && tiktok.token_expired && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.error, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expired - reconnect required
            </span>
          )}
          {tiktok.connected && !tiktok.token_expired && tiktok.token_expires_soon && (
            <span style={{ fontSize: '0.85em', color: HOPPER_COLORS.warning, marginLeft: '8px', fontWeight: '500' }}>
              ⚠️ Token expires soon
            </span>
          )}
        </div>
        {tiktok.connected ? (
          <>
            <label className="toggle">
              <input 
                type="checkbox" 
                checked={tiktok.enabled}
                disabled={tiktok.token_expired}
                onChange={toggleTiktok}
              />
              <span className="slider"></span>
            </label>
            <button onClick={() => setShowTiktokSettings(!showTiktokSettings)} className="btn-settings">
              ⚙️
            </button>
          </>
        ) : (
          <button onClick={connectTiktok}>Connect</button>
        )}
      </div>

      {showTiktokSettings && tiktok.connected && (
        <div className="settings-panel">
          <h3>TikTok Settings</h3>
          
          <div className="setting-group">
            <label>Privacy Level</label>
            <select 
              value={tiktokSettings.privacy_level || ''}
              onChange={(e) => updateTiktokSettings('privacy_level', e.target.value || null)}
              className="select"
              required
              title={
                tiktokSettings.commercial_content_disclosure && 
                tiktokSettings.commercial_content_branded && 
                tiktokSettings.privacy_level === 'SELF_ONLY'
                  ? "Branded content visibility cannot be set to private."
                  : undefined
              }
            >
              <option value="">-- Select Privacy Level --</option>
              {Array.isArray(tiktokCreatorInfo?.privacy_level_options) ? tiktokCreatorInfo.privacy_level_options.map(option => {
                const isPrivate = option === 'SELF_ONLY';
                const brandedContentSelected = tiktokSettings.commercial_content_disclosure && tiktokSettings.commercial_content_branded;
                const isDisabled = isPrivate && brandedContentSelected;
                
                return (
                  <option 
                    key={option} 
                    value={option}
                    disabled={isDisabled}
                    title={isDisabled ? "Branded content visibility cannot be set to private." : undefined}
                  >
                    {privacyLabelMap[option] || option}
                  </option>
                );
              }) : null}
            </select>
            {tiktokSettings.commercial_content_disclosure && tiktokSettings.commercial_content_branded && (
              <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: HOPPER_COLORS.warningAmber }}>
                ⚠️ Branded content requires public or friends visibility
              </div>
            )}
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={tiktokSettings.allow_comments ?? false}
                onChange={(e) => updateTiktokSettings('allow_comments', e.target.checked)}
                className="checkbox"
                disabled={tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled}
              />
              <span style={{ 
                opacity: (tiktokCreatorInfo?.disable_comment || tiktokCreatorInfo?.comment_disabled) ? 0.5 : 1 
              }}>
                Allow Comments
              </span>
            </label>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={tiktokSettings.allow_duet ?? false}
                onChange={(e) => updateTiktokSettings('allow_duet', e.target.checked)}
                className="checkbox"
                disabled={tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled}
              />
              <span style={{ 
                opacity: (tiktokCreatorInfo?.disable_duet || tiktokCreatorInfo?.duet_disabled) ? 0.5 : 1 
              }}>
                Allow Duet
              </span>
            </label>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={tiktokSettings.allow_stitch ?? false}
                onChange={(e) => updateTiktokSettings('allow_stitch', e.target.checked)}
                className="checkbox"
                disabled={tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled}
              />
              <span style={{ 
                opacity: (tiktokCreatorInfo?.disable_stitch || tiktokCreatorInfo?.stitch_disabled) ? 0.5 : 1 
              }}>
                Allow Stitch
              </span>
            </label>
          </div>

          <div className="setting-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                checked={tiktokSettings.commercial_content_disclosure ?? false}
                onChange={(e) => {
                  const newValue = e.target.checked;
                  setTiktokSettings({...tiktokSettings, commercial_content_disclosure: newValue});
                  updateTiktokSettings('commercial_content_disclosure', newValue);
                  if (!newValue) {
                    setTiktokSettings(prev => ({...prev, commercial_content_your_brand: false, commercial_content_branded: false}));
                    updateTiktokSettings('commercial_content_your_brand', false);
                    updateTiktokSettings('commercial_content_branded', false);
                  }
                }}
                className="checkbox"
              />
              <span>Content Disclosure</span>
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Indicate whether this content promotes yourself, a brand, product or service</span>
              </span>
            </label>
          </div>

          {tiktokSettings.commercial_content_disclosure && (
            <>
              <div className="setting-group" style={{ marginLeft: '1.5rem' }}>
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    checked={tiktokSettings.commercial_content_your_brand ?? false}
                    onChange={(e) => {
                      const newValue = e.target.checked;
                      setTiktokSettings({...tiktokSettings, commercial_content_your_brand: newValue});
                      updateTiktokSettings('commercial_content_your_brand', newValue);
                    }}
                    className="checkbox"
                  />
                  <span>Your Brand</span>
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">You are promoting yourself or your own business. This content will be classified as Brand Organic.</span>
                  </span>
                </label>
              </div>

              <div className="setting-group" style={{ marginLeft: '1.5rem' }}>
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    checked={tiktokSettings.commercial_content_branded ?? false}
                    onChange={(e) => {
                      const newValue = e.target.checked;
                      setTiktokSettings({...tiktokSettings, commercial_content_branded: newValue});
                      updateTiktokSettings('commercial_content_branded', newValue);
                    }}
                    className="checkbox"
                    disabled={tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded}
                  />
                  <span style={{
                    opacity: (tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded) ? 0.5 : 1
                  }}>
                    Branded Content
                  </span>
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">
                      {tiktokSettings.privacy_level === 'SELF_ONLY' && !tiktokSettings.commercial_content_branded
                        ? "Branded content visibility cannot be set to private. Please change privacy level to public or friends first."
                        : "You are promoting another brand or a third party. This content will be classified as Branded Content."}
                    </span>
                  </span>
                </label>
              </div>

              {(tiktokSettings.commercial_content_your_brand || tiktokSettings.commercial_content_branded) && (
                <div className="setting-group" style={{ marginLeft: '1.5rem', marginTop: '0.5rem' }}>
                  <div style={{
                    padding: '0.75rem',
                    background: rgba(HOPPER_COLORS.rgb.infoBlue, 0.1),
                    border: `1px solid ${rgba(HOPPER_COLORS.rgb.infoBlue, 0.3)}`,
                    borderRadius: '6px',
                    fontSize: '0.85rem',
                    color: HOPPER_COLORS.infoBlue
                  }}>
                    {tiktokSettings.commercial_content_your_brand && tiktokSettings.commercial_content_branded
                      ? "Your photo/video will be labeled as 'Paid partnership'"
                      : tiktokSettings.commercial_content_branded
                      ? "Your photo/video will be labeled as 'Paid partnership'"
                      : "Your photo/video will be labeled as 'Promotional content'"
                    }
                  </div>
                </div>
              )}
            </>
          )}

          <div className="setting-group">
            <label>
              TikTok Title Template (Caption) (Override) <span className="char-counter">{tiktokSettings.title_template?.length || 0}/2200</span>
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Override global title template for TikTok only. This is the video caption (max 2200 characters). Leave empty to use global</span>
              </span>
            </label>
            <input 
              type="text"
              value={tiktokSettings.title_template || ''}
              onChange={(e) => setTiktokSettings({...tiktokSettings, title_template: e.target.value})}
              onBlur={(e) => updateTiktokSettings('title_template', e.target.value)}
              placeholder="Leave empty to use global template"
              className="input-text"
              maxLength="2200"
            />
          </div>

          <div className="setting-divider"></div>
          
          <div className="setting-group">
            <button onClick={disconnectTiktok} className="btn-logout" style={{
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
