import React, { useState, useEffect } from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * Edit video modal component
 * @param {object} props
 */
export default function EditVideoModal({
  editingVideo,
  videos,
  youtubeSettings,
  tiktok,
  tiktokCreatorInfo,
  closeEditModal,
  recomputeVideoTitle,
  updateVideoSettings,
}) {
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [editCommercialContentDisclosure, setEditCommercialContentDisclosure] = useState(false);
  const [editCommercialContentYourBrand, setEditCommercialContentYourBrand] = useState(false);
  const [editCommercialContentBranded, setEditCommercialContentBranded] = useState(false);
  const [editTiktokPrivacy, setEditTiktokPrivacy] = useState('');

  const currentEditingVideo = videos.find(v => v.id === editingVideo?.id) || editingVideo;
  
  useEffect(() => {
    if (currentEditingVideo) {
      const title = currentEditingVideo.custom_settings?.title || currentEditingVideo.youtube_title || '';
      setEditTitleLength(title.length);
      setEditCommercialContentDisclosure(currentEditingVideo.custom_settings?.commercial_content_disclosure ?? false);
      setEditCommercialContentYourBrand(currentEditingVideo.custom_settings?.commercial_content_your_brand ?? false);
      setEditCommercialContentBranded(currentEditingVideo.custom_settings?.commercial_content_branded ?? false);
      setEditTiktokPrivacy(currentEditingVideo.custom_settings?.privacy_level || '');
    }
  }, [currentEditingVideo]);

  if (!editingVideo || !currentEditingVideo) return null;

  const handleSave = () => {
    const title = document.getElementById('edit-title')?.value || '';
    const description = document.getElementById('edit-description')?.value || '';
    const tags = document.getElementById('edit-tags')?.value || '';
    const visibility = document.getElementById('edit-visibility')?.value || 'private';
    const madeForKids = document.getElementById('edit-made-for-kids')?.checked || false;
    const scheduledTime = document.getElementById('edit-scheduled-time')?.value || '';
    
    const settings = {
      title: title || null,
      description: description || null,
      tags: tags || null,
      visibility,
      made_for_kids: madeForKids,
      scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : ''
    };
    
    if (tiktok.enabled && tiktok.connected) {
      const tiktokPrivacy = editTiktokPrivacy || document.getElementById('edit-tiktok-privacy')?.value || '';
      const tiktokAllowComments = document.getElementById('edit-tiktok-allow-comments')?.checked || false;
      const tiktokAllowDuet = document.getElementById('edit-tiktok-allow-duet')?.checked || false;
      const tiktokAllowStitch = document.getElementById('edit-tiktok-allow-stitch')?.checked || false;
      
      if (tiktokPrivacy) {
        settings.privacy_level = tiktokPrivacy;
      }
      settings.allow_comments = tiktokAllowComments;
      settings.allow_duet = tiktokAllowDuet;
      settings.allow_stitch = tiktokAllowStitch;
      settings.commercial_content_disclosure = editCommercialContentDisclosure;
      settings.commercial_content_your_brand = editCommercialContentYourBrand;
      settings.commercial_content_branded = editCommercialContentBranded;
    }
    
    updateVideoSettings(currentEditingVideo.id, settings);
  };

  const privacyLabelMap = {
    'PUBLIC_TO_EVERYONE': 'Everyone',
    'MUTUAL_FOLLOW_FRIENDS': 'Friends',
    'FOLLOWER_OF_CREATOR': 'Followers',
    'SELF_ONLY': 'Only you'
  };

  return (
    <div className="modal-overlay" onClick={closeEditModal}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Edit Video Settings</h2>
          <button onClick={closeEditModal} className="btn-close">×</button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <label>
                Video Title <span className="char-counter">{editTitleLength}/100</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Leave empty to use template. Click "Recompute" to regenerate from current template.</span>
                </span>
              </label>
              <button 
                type="button"
                onClick={() => recomputeVideoTitle(currentEditingVideo.id)}
                className="btn-recompute-title"
                style={{
                  padding: '0.4rem 0.8rem',
                  fontSize: '0.85rem',
                  background: rgba(HOPPER_COLORS.rgb.purple, 0.2),
                  border: `1px solid ${rgba(HOPPER_COLORS.rgb.purple, 0.4)}`,
                  borderRadius: '4px',
                  color: HOPPER_COLORS.purple,
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
                title="Recompute title from current template"
              >
                🔄 Recompute
              </button>
            </div>
            <input 
              type="text"
              defaultValue={currentEditingVideo.custom_settings?.title || currentEditingVideo.youtube_title}
              id="edit-title"
              className="input-text"
              placeholder="Video title"
              maxLength="100"
              onInput={(e) => setEditTitleLength(e.target.value.length)}
            />
          </div>
          
          <div className="form-group">
            <label>
              Description
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Leave empty to use global template</span>
              </span>
            </label>
            <textarea 
              defaultValue={currentEditingVideo.custom_settings?.description || ''}
              id="edit-description"
              className="textarea-text"
              rows="4"
              placeholder="Video description"
            />
          </div>
          
          <div className="form-group">
            <label>
              Tags
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Comma-separated tags. Leave empty to use global template</span>
              </span>
            </label>
            <input 
              type="text"
              defaultValue={currentEditingVideo.custom_settings?.tags || ''}
              id="edit-tags"
              className="input-text"
              placeholder="tag1, tag2, tag3"
            />
          </div>
          
          <div className="form-group">
            <label>Visibility</label>
            <select 
              defaultValue={currentEditingVideo.custom_settings?.visibility || youtubeSettings.visibility}
              id="edit-visibility"
              className="select"
            >
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
            </select>
          </div>
          
          <div className="form-group">
            <label className="checkbox-label">
              <input 
                type="checkbox"
                defaultChecked={currentEditingVideo.custom_settings?.made_for_kids ?? youtubeSettings.made_for_kids}
                id="edit-made-for-kids"
                className="checkbox"
              />
              <span>Made for Kids</span>
            </label>
          </div>

          <div className="form-group">
            <label>
              Scheduled Time
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Leave empty for immediate upload (if enabled) or use global schedule</span>
              </span>
            </label>
            <input 
              type="datetime-local"
              defaultValue={currentEditingVideo.scheduled_time ? (() => {
                const date = new Date(currentEditingVideo.scheduled_time);
                const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
                return localDate.toISOString().slice(0, 16);
              })() : ''}
              id="edit-scheduled-time"
              className="input-text"
            />
          </div>
          
          {tiktok.enabled && tiktok.connected && (
            <>
              <div className="form-group">
                <label>TikTok Privacy Level</label>
                <select 
                  value={editTiktokPrivacy}
                  id="edit-tiktok-privacy"
                  className="select"
                  required
                  onChange={(e) => setEditTiktokPrivacy(e.target.value)}
                  title={
                    editCommercialContentDisclosure && 
                    editCommercialContentBranded && 
                    editTiktokPrivacy === 'SELF_ONLY'
                      ? "Branded content visibility cannot be set to private."
                      : undefined
                  }
                >
                  <option value="">-- Select Privacy Level --</option>
                  {Array.isArray(tiktokCreatorInfo?.privacy_level_options) ? tiktokCreatorInfo.privacy_level_options.map(option => {
                    const isPrivate = option === 'SELF_ONLY';
                    const brandedContentSelected = editCommercialContentDisclosure && editCommercialContentBranded;
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
                {editCommercialContentDisclosure && editCommercialContentBranded && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: HOPPER_COLORS.warningAmber }}>
                    ⚠️ Branded content requires public or friends visibility
                  </div>
                )}
              </div>
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    defaultChecked={currentEditingVideo.custom_settings?.allow_comments ?? false}
                    id="edit-tiktok-allow-comments"
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
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    defaultChecked={currentEditingVideo.custom_settings?.allow_duet ?? false}
                    id="edit-tiktok-allow-duet"
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
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    defaultChecked={currentEditingVideo.custom_settings?.allow_stitch ?? false}
                    id="edit-tiktok-allow-stitch"
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
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    checked={editCommercialContentDisclosure}
                    id="edit-tiktok-commercial-content-disclosure"
                    className="checkbox"
                    onChange={(e) => {
                      const newValue = e.target.checked;
                      setEditCommercialContentDisclosure(newValue);
                      if (!newValue) {
                        setEditCommercialContentYourBrand(false);
                        setEditCommercialContentBranded(false);
                      }
                    }}
                  />
                  <span>Content Disclosure</span>
                </label>
              </div>
              
              {editCommercialContentDisclosure && (
                <>
                  <div className="form-group" style={{ marginLeft: '1.5rem' }}>
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        checked={editCommercialContentYourBrand}
                        id="edit-tiktok-commercial-content-your-brand"
                        className="checkbox"
                        onChange={(e) => setEditCommercialContentYourBrand(e.target.checked)}
                      />
                      <span>Your Brand</span>
                    </label>
                  </div>
                  
                  <div className="form-group" style={{ marginLeft: '1.5rem' }}>
                    <label className="checkbox-label">
                      <input 
                        type="checkbox"
                        checked={editCommercialContentBranded}
                        id="edit-tiktok-commercial-content-branded"
                        className="checkbox"
                        onChange={(e) => setEditCommercialContentBranded(e.target.checked)}
                        disabled={editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded}
                      />
                      <span style={{
                        opacity: (editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded) ? 0.5 : 1
                      }}>
                        Branded Content
                      </span>
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">
                          {editTiktokPrivacy === 'SELF_ONLY' && !editCommercialContentBranded
                            ? "Branded content visibility cannot be set to private. Please change privacy level to public or friends first."
                            : "You are promoting another brand or a third party. This content will be classified as Branded Content."}
                        </span>
                      </span>
                    </label>
                  </div>
                  
                  {(editCommercialContentYourBrand || editCommercialContentBranded) && (
                    <div className="form-group" style={{ marginLeft: '1.5rem', marginTop: '0.5rem' }}>
                      <div style={{
                        padding: '0.75rem',
                        background: rgba(HOPPER_COLORS.rgb.infoBlue, 0.1),
                        border: `1px solid ${rgba(HOPPER_COLORS.rgb.infoBlue, 0.3)}`,
                        borderRadius: '6px',
                        fontSize: '0.85rem',
                        color: HOPPER_COLORS.infoBlue
                      }}>
                        {editCommercialContentYourBrand && editCommercialContentBranded
                          ? "Your photo/video will be labeled as 'Paid partnership'"
                          : editCommercialContentBranded
                          ? "Your photo/video will be labeled as 'Paid partnership'"
                          : "Your photo/video will be labeled as 'Promotional content'"
                        }
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
        <div className="modal-footer">
          <button onClick={closeEditModal} className="btn-cancel">
            Cancel
          </button>
          <button onClick={handleSave} className="btn-save">
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}

