import React, { useState, useEffect } from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

/**
 * Destination details modal component
 * Shows upload details and allows overriding settings for a specific platform
 * @param {object} props
 */
export default function DestinationDetailsModal({
  destinationModal,
  setDestinationModal,
  videos,
  recomputeVideoField,
  saveDestinationOverrides,
  expandedDestinationErrors,
  setExpandedDestinationErrors,
}) {
  const [overrideInputValues, setOverrideInputValues] = useState({});

  const video = videos.find(v => v.id === destinationModal?.videoId);
  if (!destinationModal || !video) return null;

  const platform = destinationModal.platform;
  const platformNames = {
    youtube: 'YouTube',
    tiktok: 'TikTok',
    instagram: 'Instagram'
  };

  const platformData = video.upload_properties?.[platform] || {};
  const platformStatusData = video.platform_statuses?.[platform] || {status: 'pending', error: null};
  const platformStatus = typeof platformStatusData === 'object' ? platformStatusData.status : platformStatusData;
  const platformErrorFromStatus = typeof platformStatusData === 'object' ? platformStatusData.error : null;
  
  let platformError = platformData.error || platformErrorFromStatus || null;
  if (!platformError && platform === 'tiktok') {
    platformError = video.tiktok_publish_error || null;
  }
  if (!platformError && platformStatus === 'failed' && video.error) {
    const platformKeywords = {
      youtube: ['youtube', 'google'],
      tiktok: ['tiktok'],
      instagram: ['instagram', 'facebook']
    };
    const keywords = platformKeywords[platform] || [];
    const errorLower = video.error.toLowerCase();
    
    if (keywords.some(keyword => errorLower.includes(keyword))) {
      platformError = video.error;
    } else if (!video.error.includes('Upload failed for all destinations') && 
               !video.error.includes('but failed for others')) {
      platformError = video.error;
    }
  }

  const customSettings = video.custom_settings || {};
  const modalKey = `${video.id}-${platform}`;

  useEffect(() => {
    if (!overrideInputValues[modalKey]) {
      const initial = {};
      if (platform === 'youtube') {
        initial.youtube_title = customSettings.youtube_title || platformData.title || '';
      } else if (platform === 'tiktok') {
        initial.title = customSettings.title || platformData.title || '';
      } else if (platform === 'instagram') {
        initial.title = customSettings.title || platformData.caption || '';
      }
      setOverrideInputValues(prev => ({ ...prev, [modalKey]: initial }));
    }
  }, [modalKey, platform, customSettings, platformData]);

  const overrideValues = overrideInputValues[modalKey] || {};

  const updateOverrideValue = (key, value) => {
    setOverrideInputValues(prev => ({
      ...prev,
      [modalKey]: {
        ...(prev[modalKey] || {}),
        [key]: value
      }
    }));
  };

  const formatTags = (tags) => {
    if (!tags) return '';
    if (Array.isArray(tags)) return tags.join(', ');
    if (typeof tags === 'string') return tags.split(',').map(t => t.trim()).join(', ');
    return String(tags);
  };

  const formatBoolean = (value, undefinedText = 'Not set') => {
    if (value === undefined || value === null) return undefinedText;
    return value ? 'Yes' : 'No';
  };

  const handleSaveOverrides = async () => {
    try {
      const overrides = {};
      
      if (platform === 'youtube') {
        const descEl = document.getElementById(`dest-override-description-${video.id}-${platform}`);
        const tagsEl = document.getElementById(`dest-override-tags-${video.id}-${platform}`);
        const visibilityEl = document.getElementById(`dest-override-visibility-${video.id}-${platform}`);
        const madeForKidsEl = document.getElementById(`dest-override-made-for-kids-${video.id}-${platform}`);
        
        if (overrideValues.youtube_title) overrides.title = overrideValues.youtube_title;
        if (descEl?.value) overrides.description = descEl.value;
        if (tagsEl?.value) overrides.tags = tagsEl.value;
        if (visibilityEl?.value) overrides.visibility = visibilityEl.value;
        overrides.made_for_kids = madeForKidsEl?.checked ?? false;
      } else if (platform === 'tiktok') {
        const privacyEl = document.getElementById(`dest-override-privacy-${video.id}-${platform}`);
        
        if (overrideValues.title) overrides.title = overrideValues.title;
        if (privacyEl?.value) overrides.privacy_level = privacyEl.value;
      } else if (platform === 'instagram') {
        const mediaTypeEl = document.getElementById(`dest-override-media-type-${video.id}-${platform}`);
        const shareToFeedEl = document.getElementById(`dest-override-share-to-feed-${video.id}-${platform}`);
        const coverUrlEl = document.getElementById(`dest-override-cover-url-${video.id}-${platform}`);
        const disableCommentsEl = document.getElementById(`dest-override-disable-comments-${video.id}-${platform}`);
        const disableLikesEl = document.getElementById(`dest-override-disable-likes-${video.id}-${platform}`);
        
        if (overrideValues.title) overrides.title = overrideValues.title;
        if (mediaTypeEl?.value) overrides.media_type = mediaTypeEl.value;
        if (disableCommentsEl !== null) overrides.disable_comments = disableCommentsEl.checked;
        if (disableLikesEl !== null) overrides.disable_likes = disableLikesEl.checked;
        
        const mediaType = mediaTypeEl?.value || customSettings.media_type || platformData.media_type || 'REELS';
        if (mediaType === 'REELS' && shareToFeedEl !== null) {
          overrides.share_to_feed = shareToFeedEl.checked;
        }
        
        if (coverUrlEl?.value) overrides.cover_url = coverUrlEl.value;
      }
      
      const success = await saveDestinationOverrides(video.id, platform, overrides);
      if (success) {
        setDestinationModal(null);
      }
    } catch (err) {
      console.error('Error saving destination overrides:', err);
    }
  };

  const toggleErrorExpansion = () => {
    const errorKey = `${video.id}-${platform}`;
    setExpandedDestinationErrors(prev => {
      const newSet = new Set(prev);
      if (newSet.has(errorKey)) {
        newSet.delete(errorKey);
      } else {
        newSet.add(errorKey);
      }
      return newSet;
    });
  };

  const isErrorExpanded = expandedDestinationErrors.has(`${video.id}-${platform}`);

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
        zIndex: 10000,
        padding: '1rem'
      }}
      onClick={() => setDestinationModal(null)}
    >
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: '700px',
          width: '100%',
          maxHeight: '90vh',
          overflowY: 'auto'
        }}
      >
        <div className="modal-header">
          <h2>
            {platformNames[platform]} Upload Details
            {platformStatus === 'success' && <span style={{ color: HOPPER_COLORS.success, marginLeft: '8px' }}>✓</span>}
            {platformStatus === 'failed' && <span style={{ color: HOPPER_COLORS.error, marginLeft: '8px' }}>✕</span>}
            {platformStatus === 'uploading' && <span style={{ color: HOPPER_COLORS.info, marginLeft: '8px' }}>⏳</span>}
          </h2>
          <button className="btn-close" onClick={() => setDestinationModal(null)}>×</button>
        </div>
        
        <div className="modal-body">
          <div className="setting-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <label>Upload Status</label>
              {platformStatus === 'failed' && (
                <button
                  onClick={toggleErrorExpansion}
                  style={{
                    padding: '0.375rem 0.75rem',
                    background: rgba(HOPPER_COLORS.rgb.error, 0.1),
                    border: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`,
                    borderRadius: '6px',
                    color: HOPPER_COLORS.error,
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: '500',
                    transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.background = rgba(HOPPER_COLORS.rgb.error, 0.2);
                    e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.error, 0.5);
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.background = rgba(HOPPER_COLORS.rgb.error, 0.1);
                    e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.error, 0.3);
                  }}
                >
                  {isErrorExpanded ? 'Hide Error' : 'Show Error'}
                </button>
              )}
            </div>
            <div style={{
              padding: '0.75rem',
              background: platformStatus === 'success' 
                ? rgba(HOPPER_COLORS.rgb.success, 0.1)
                : platformStatus === 'failed'
                ? rgba(HOPPER_COLORS.rgb.error, 0.1)
                : rgba(HOPPER_COLORS.rgb.white, 0.05),
              border: `1px solid ${
                platformStatus === 'success'
                  ? HOPPER_COLORS.success
                  : platformStatus === 'failed'
                  ? HOPPER_COLORS.error
                  : rgba(HOPPER_COLORS.rgb.white, 0.2)
              }`,
              borderRadius: '6px',
              color: platformStatus === 'success'
                ? HOPPER_COLORS.success
                : platformStatus === 'failed'
                ? HOPPER_COLORS.error
                : HOPPER_COLORS.grey,
              fontWeight: '500'
            }}>
              {platformStatus === 'success' && '✓ Upload Successful'}
              {platformStatus === 'failed' && '✕ Upload Failed'}
              {platformStatus === 'uploading' && '⏳ Uploading...'}
              {platformStatus === 'pending' && '⏳ Pending Upload'}
            </div>
          </div>
          
          {platformStatus === 'failed' && isErrorExpanded && (
            <div className="setting-group">
              <label>{platformNames[platform]} Upload Error</label>
              <div style={{
                padding: '0.75rem',
                background: rgba(HOPPER_COLORS.rgb.error, 0.1),
                border: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`,
                borderRadius: '6px',
                color: HOPPER_COLORS.error,
                fontSize: '0.9rem',
                wordBreak: 'break-word'
              }}>
                {platformError ? (
                  platformError
                ) : (
                  <div style={{ fontStyle: 'italic', opacity: 0.8 }}>
                    No detailed error message available. The upload failed but no specific error was captured.
                    {video.error && (
                      <div style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: `1px solid ${rgba(HOPPER_COLORS.rgb.error, 0.2)}` }}>
                        <strong>General error:</strong> {video.error}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          
          <div className="setting-group">
            <label>Upload Metadata</label>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.75rem',
              padding: '0.75rem',
              background: rgba(HOPPER_COLORS.rgb.white, 0.03),
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.white, 0.1)}`,
              borderRadius: '6px',
              fontSize: '0.9rem'
            }}>
              {/* Filename - shown for all platforms */}
              {video.filename && (
                <div>
                  <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Filename:</span>
                  <div style={{
                    marginTop: '0.25rem',
                    padding: '0.5rem',
                    background: rgba(HOPPER_COLORS.rgb.base, 0.2),
                    borderRadius: '4px',
                    color: HOPPER_COLORS.light,
                    wordBreak: 'break-word'
                  }}>
                    {video.filename}
                  </div>
                </div>
              )}
              {platform === 'youtube' && (
                <>
                  <div>
                    <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Title:</span>
                    <div style={{
                      marginTop: '0.25rem',
                      padding: '0.5rem',
                      background: rgba(HOPPER_COLORS.rgb.base, 0.2),
                      borderRadius: '4px',
                      color: HOPPER_COLORS.light,
                      wordBreak: 'break-word'
                    }}>
                      {platformData.title || video.youtube_title || video.filename}
                    </div>
                  </div>
                  {platformData.description && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Description:</span>
                      <div style={{
                        marginTop: '0.25rem',
                        padding: '0.5rem',
                        background: rgba(HOPPER_COLORS.rgb.base, 0.2),
                        borderRadius: '4px',
                        color: HOPPER_COLORS.light,
                        maxHeight: '150px',
                        overflowY: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word'
                      }}>
                        {platformData.description}
                      </div>
                    </div>
                  )}
                  {platformData.tags && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Tags:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>{formatTags(platformData.tags)}</span>
                    </div>
                  )}
                  {platformData.visibility && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Visibility:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light, textTransform: 'capitalize' }}>
                        {platformData.visibility}
                      </span>
                    </div>
                  )}
                  {platformData.made_for_kids !== undefined && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Made for Kids:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>{formatBoolean(platformData.made_for_kids)}</span>
                    </div>
                  )}
                </>
              )}
              {platform === 'tiktok' && (
                <>
                  {platformData.title && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Title:</span>
                      <div style={{
                        marginTop: '0.25rem',
                        padding: '0.5rem',
                        background: rgba(HOPPER_COLORS.rgb.base, 0.2),
                        borderRadius: '4px',
                        color: HOPPER_COLORS.light,
                        wordBreak: 'break-word'
                      }}>
                        {platformData.title}
                      </div>
                    </div>
                  )}
                  {platformData.privacy_level && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Privacy Level:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light, textTransform: 'capitalize' }}>
                        {platformData.privacy_level}
                      </span>
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.25rem' }}>
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Allow Comments:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>{formatBoolean(platformData.allow_comments)}</span>
                    </div>
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Allow Duet:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>{formatBoolean(platformData.allow_duet)}</span>
                    </div>
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Allow Stitch:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>{formatBoolean(platformData.allow_stitch)}</span>
                    </div>
                    {platformData.commercial_content_disclosure !== undefined && (
                      <div>
                        <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Commercial Disclosure:</span>{' '}
                        <span style={{ color: HOPPER_COLORS.light }}>{formatBoolean(platformData.commercial_content_disclosure)}</span>
                      </div>
                    )}
                  </div>
                  {(platformData.commercial_content_your_brand || platformData.commercial_content_branded) && (
                    <div style={{
                      marginTop: '0.25rem',
                      padding: '0.5rem',
                      background: rgba(HOPPER_COLORS.rgb.warning, 0.1),
                      borderRadius: '4px',
                      border: `1px solid ${rgba(HOPPER_COLORS.rgb.warning, 0.3)}`
                    }}>
                      <strong style={{ color: HOPPER_COLORS.warning }}>Commercial Content:</strong>
                      <div style={{ marginTop: '0.25rem', color: HOPPER_COLORS.light, fontSize: '0.85rem' }}>
                        {platformData.commercial_content_your_brand && <div>• Your Brand</div>}
                        {platformData.commercial_content_branded && <div>• Branded Content</div>}
                      </div>
                    </div>
                  )}
                  {video.tiktok_publish_status && (
                    <div style={{
                      marginTop: '0.5rem',
                      padding: '0.5rem',
                      background: video.tiktok_publish_status === 'PUBLISHED' 
                        ? rgba(HOPPER_COLORS.rgb.success, 0.1)
                        : rgba(HOPPER_COLORS.rgb.info, 0.1),
                      borderRadius: '4px',
                      border: `1px solid ${
                        video.tiktok_publish_status === 'PUBLISHED' 
                          ? rgba(HOPPER_COLORS.rgb.success, 0.3)
                          : rgba(HOPPER_COLORS.rgb.info, 0.3)
                      }`
                    }}>
                      <strong>Publish Status:</strong>{' '}
                      <span style={{ 
                        color: video.tiktok_publish_status === 'PUBLISHED' 
                          ? HOPPER_COLORS.success
                          : HOPPER_COLORS.info,
                        textTransform: 'capitalize'
                      }}>{video.tiktok_publish_status}</span>
                    </div>
                  )}
                </>
              )}
              {platform === 'instagram' && (
                <>
                  {platformData.caption && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Caption:</span>
                      <div style={{
                        marginTop: '0.25rem',
                        padding: '0.5rem',
                        background: rgba(HOPPER_COLORS.rgb.base, 0.2),
                        borderRadius: '4px',
                        color: HOPPER_COLORS.light,
                        maxHeight: '150px',
                        overflowY: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word'
                      }}>
                        {platformData.caption}
                      </div>
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.25rem' }}>
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Media Type:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>
                        {platformData.media_type || 'REELS'}
                      </span>
                    </div>
                    {(platformData.media_type === 'REELS' || !platformData.media_type) && (
                      <div>
                        <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Share to Feed:</span>{' '}
                        <span style={{ color: HOPPER_COLORS.light }}>
                          {platformData.share_to_feed !== false ? 'Yes' : 'No'}
                        </span>
                      </div>
                    )}
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Comments:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>
                        {platformData.disable_comments ? 'Disabled' : 'Enabled'}
                      </span>
                    </div>
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Likes:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>
                        {platformData.disable_likes ? 'Disabled' : 'Enabled'}
                      </span>
                    </div>
                  </div>
                  {platformData.cover_url && (
                    <div>
                      <span style={{ fontWeight: '600', color: HOPPER_COLORS.light }}>Cover Image:</span>{' '}
                      <span style={{ color: HOPPER_COLORS.light }}>Custom thumbnail set</span>
                    </div>
                  )}
                </>
              )}
              {(!platformData || Object.keys(platformData).length === 0) && (
                <div style={{ 
                  color: HOPPER_COLORS.grey,
                  fontStyle: 'italic',
                  textAlign: 'center',
                  padding: '1rem'
                }}>
                  No upload metadata available yet. Metadata will be computed when the upload is processed.
                </div>
              )}
            </div>
          </div>
          
          <div className="setting-group">
            <label>
              Override Settings (Optional)
              <span className="tooltip-wrapper">
                <span className="tooltip-icon">i</span>
                <span className="tooltip-text">Override default settings for this video on {platformNames[platform]} only</span>
              </span>
            </label>
            
            {platform === 'youtube' && (
              <>
                <div className="setting-group">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label htmlFor={`dest-override-title-${video.id}-${platform}`}>
                      Title <span className="char-counter">{(overrideValues.youtube_title || '').length}/100</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => recomputeVideoField(video.id, platform, 'title')}
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
                    id={`dest-override-title-${video.id}-${platform}`}
                    value={overrideValues.youtube_title || ''}
                    onChange={(e) => updateOverrideValue('youtube_title', e.target.value)}
                    placeholder={platformData.title || video.filename}
                    maxLength={100}
                    className="input-text"
                  />
                </div>
                
                <div className="setting-group">
                  <label htmlFor={`dest-override-description-${video.id}-${platform}`}>Description</label>
                  <textarea
                    id={`dest-override-description-${video.id}-${platform}`}
                    defaultValue={customSettings.description || platformData.description || ''}
                    placeholder={platformData.description || 'Enter description...'}
                    rows={4}
                    className="textarea-text"
                  />
                </div>
                
                <div className="setting-group">
                  <label htmlFor={`dest-override-tags-${video.id}-${platform}`}>Tags (comma-separated)</label>
                  <input
                    type="text"
                    id={`dest-override-tags-${video.id}-${platform}`}
                    defaultValue={customSettings.tags || formatTags(platformData.tags) || ''}
                    placeholder={formatTags(platformData.tags) || 'Enter tags...'}
                    className="input-text"
                  />
                </div>
                
                <div className="setting-group">
                  <label htmlFor={`dest-override-visibility-${video.id}-${platform}`}>Visibility</label>
                  <select
                    id={`dest-override-visibility-${video.id}-${platform}`}
                    defaultValue={customSettings.visibility || platformData.visibility || 'private'}
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
                      id={`dest-override-made-for-kids-${video.id}-${platform}`}
                      defaultChecked={customSettings.made_for_kids !== undefined ? customSettings.made_for_kids : platformData.made_for_kids || false}
                      className="checkbox"
                    />
                    <span>Made for Kids</span>
                  </label>
                </div>
              </>
            )}
            
            {platform === 'tiktok' && (
              <>
                <div className="setting-group">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label htmlFor={`dest-override-title-${video.id}-${platform}`}>
                      Title <span className="char-counter">{(overrideValues.title || '').length}/2200</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => recomputeVideoField(video.id, platform, 'title')}
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
                    id={`dest-override-title-${video.id}-${platform}`}
                    value={overrideValues.title || ''}
                    onChange={(e) => updateOverrideValue('title', e.target.value)}
                    placeholder={platformData.title || 'Enter title...'}
                    maxLength={2200}
                    className="input-text"
                  />
                </div>
                
                <div className="setting-group">
                  <label htmlFor={`dest-override-privacy-${video.id}-${platform}`}>Privacy Level</label>
                  <select
                    id={`dest-override-privacy-${video.id}-${platform}`}
                    defaultValue={customSettings.privacy_level || platformData.privacy_level || ''}
                    className="select"
                  >
                    <option value="">Use default</option>
                    <option value="PUBLIC_TO_EVERYONE">Public to Everyone</option>
                    <option value="MUTUAL_FOLLOW_FRIENDS">Friends</option>
                    <option value="FOLLOWER_OF_CREATOR">Followers</option>
                    <option value="SELF_ONLY">Only you</option>
                  </select>
                </div>
              </>
            )}
            
            {platform === 'instagram' && (
              <>
                <div className="setting-group">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <label htmlFor={`dest-override-caption-${video.id}-${platform}`}>
                      Title/Caption <span className="char-counter">{(overrideValues.title || '').length}/2200</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => recomputeVideoField(video.id, platform, 'caption')}
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
                      title="Recompute caption from current template"
                    >
                      🔄 Recompute
                    </button>
                  </div>
                  <textarea
                    id={`dest-override-caption-${video.id}-${platform}`}
                    value={overrideValues.title || ''}
                    onChange={(e) => updateOverrideValue('title', e.target.value)}
                    placeholder={platformData.caption || video.filename}
                    rows={4}
                    maxLength={2200}
                    className="textarea-text"
                  />
                </div>

                <div className="setting-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      id={`dest-override-disable-comments-${video.id}-${platform}`}
                      defaultChecked={customSettings.disable_comments !== undefined ? customSettings.disable_comments : (platformData.disable_comments ?? false)}
                      className="checkbox"
                    />
                    <span>Disable Comments</span>
                  </label>
                </div>

                <div className="setting-group">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      id={`dest-override-disable-likes-${video.id}-${platform}`}
                      defaultChecked={customSettings.disable_likes !== undefined ? customSettings.disable_likes : (platformData.disable_likes ?? false)}
                      className="checkbox"
                    />
                    <span>Disable Likes</span>
                  </label>
                </div>

                <div className="setting-group">
                  <label htmlFor={`dest-override-media-type-${video.id}-${platform}`}>Media Type</label>
                  <select
                    id={`dest-override-media-type-${video.id}-${platform}`}
                    defaultValue={customSettings.media_type || platformData.media_type || 'REELS'}
                    className="select"
                  >
                    <option value="REELS">Reels</option>
                    <option value="VIDEO">Video (Feed Post)</option>
                  </select>
                </div>

                {(() => {
                  const currentMediaType = customSettings.media_type || platformData.media_type || 'REELS';
                  if (currentMediaType !== 'REELS') return null;
                  
                  return (
                    <div className="setting-group">
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          id={`dest-override-share-to-feed-${video.id}-${platform}`}
                          defaultChecked={customSettings.share_to_feed !== undefined ? customSettings.share_to_feed : (platformData.share_to_feed ?? true)}
                          className="checkbox"
                        />
                        <span>Share Reel to Feed</span>
                      </label>
                    </div>
                  );
                })()}

                <div className="setting-group">
                  <label htmlFor={`dest-override-cover-url-${video.id}-${platform}`}>Cover Image URL (Optional)</label>
                  <input
                    type="text"
                    id={`dest-override-cover-url-${video.id}-${platform}`}
                    defaultValue={customSettings.cover_url || platformData.cover_url || ''}
                    placeholder="https://example.com/image.jpg"
                    className="input-text"
                  />
                </div>
              </>
            )}
          </div>
        </div>
        
        <div className="modal-footer">
          <button
            onClick={() => setDestinationModal(null)}
            className="btn-cancel"
          >
            Cancel
          </button>
          <button
            onClick={handleSaveOverrides}
            className="btn-save"
          >
            Save Overrides
          </button>
        </div>
      </div>
    </div>
  );
}

