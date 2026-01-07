import React from 'react';
import { PLATFORM_CONFIG } from '../../../utils/platformConfig';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

const flexTextStyle = { 
  flex: 1, 
  minWidth: 0, 
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  display: 'block',
  width: '100%'
};

export default function VideoItem({
  video: v,
  draggedVideo,
  youtube,
  tiktok,
  instagram,
  handleDragStart,
  handleDragEnd,
  handleDragOver,
  handleDrop,
  formatFileSize,
  setDestinationModal,
  setEditingVideo,
  removeVideo,
  setMessage,
  loadVideos,
  API,
  axios
}) {
  const uploadProps = v.upload_properties || {};
  const youtubeProps = uploadProps.youtube || {};

  const getTitle = () => {
    const platforms = [
      { name: 'youtube', state: youtube },
      { name: 'tiktok', state: tiktok },
      { name: 'instagram', state: instagram },
    ];
    
    for (const { name, state } of platforms) {
      if (state.enabled) {
        const titleField = PLATFORM_CONFIG[name].title_field;
        const title = v[titleField];
        if (title) {
          return title;
        }
      }
    }
    
    return v.filename;
  };

  return (
    <div 
      className={`video ${draggedVideo?.id === v.id ? 'dragging' : ''}`}
      onDragOver={handleDragOver}
      onDrop={(e) => handleDrop(e, v, setMessage)}
    >
      <div 
        className="drag-handle" 
        title="Drag to reorder"
        draggable={v.status !== 'uploading'}
        onDragStart={(e) => handleDragStart(e, v)}
        onDragEnd={handleDragEnd}
      >⋮⋮</div>
      <div className="video-info-container">
        <div className="video-titles">
          <div className="youtube-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ flexShrink: 0 }}>
              <path d="M8 5v14l11-7z" fill="currentColor"/>
            </svg>
            <span style={flexTextStyle}>
              {getTitle()}
              {v.title_too_long && (
                <span className="title-warning" title={`Title truncated from ${v.title_original_length} to 100 characters`}>
                  ⚠️ {v.title_original_length}
                </span>
              )}
            </span>
          </div>
          {v.platform_statuses && (
            <div className="platform-status-buttons" style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '6px', 
              marginTop: '4px',
              flexWrap: 'wrap'
            }}>
              {Object.entries(v.platform_statuses).map(([platform, statusData]) => {
                const status = typeof statusData === 'object' ? statusData.status : statusData;
                if (status === 'not_enabled') return null;
                
                const platformNames = {
                  youtube: 'YouTube',
                  tiktok: 'TikTok',
                  instagram: 'Instagram'
                };
                
                let platformIcon;
                if (platform === 'youtube') {
                  platformIcon = (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill={HOPPER_COLORS.youtubeRed}/>
                    </svg>
                  );
                } else if (platform === 'tiktok') {
                  platformIcon = (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" fill={HOPPER_COLORS.white}/>
                    </svg>
                  );
                } else if (platform === 'instagram') {
                  platformIcon = (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" fill={HOPPER_COLORS.instagramPink}/>
                    </svg>
                  );
                }
                
                let borderColor, backgroundColor, boxShadow, title;
                if (status === 'success') {
                  borderColor = HOPPER_COLORS.success;
                  backgroundColor = rgba(HOPPER_COLORS.rgb.success, 0.1);
                  boxShadow = `0 0 8px ${rgba(HOPPER_COLORS.rgb.success, 0.4)}`;
                  title = `${platformNames[platform]}: Upload successful - Click to view/edit`;
                } else if (status === 'failed') {
                  borderColor = HOPPER_COLORS.error;
                  backgroundColor = rgba(HOPPER_COLORS.rgb.error, 0.1);
                  boxShadow = `0 0 8px ${rgba(HOPPER_COLORS.rgb.error, 0.4)}`;
                  title = `${platformNames[platform]}: Upload failed - Click to view errors/edit`;
                } else {
                  borderColor = rgba(HOPPER_COLORS.rgb.white, 0.2);
                  backgroundColor = rgba(HOPPER_COLORS.rgb.white, 0.05);
                  boxShadow = 'none';
                  title = `${platformNames[platform]}: Will upload to this platform - Click to configure`;
                }
                
                return (
                  <button
                    key={platform}
                    className="destination-status-button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDestinationModal({ videoId: v.id, platform, video: v });
                    }}
                    title={title}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: '4px 6px',
                      border: `2px solid ${borderColor}`,
                      borderRadius: '6px',
                      background: backgroundColor,
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      opacity: status === 'pending' ? 0.7 : 1,
                      minWidth: '32px',
                      height: '28px',
                      boxShadow: boxShadow
                    }}
                    onMouseEnter={(e) => {
                      if (status === 'pending') {
                        e.currentTarget.style.opacity = '1';
                        e.currentTarget.style.borderColor = rgba(HOPPER_COLORS.rgb.info, 0.5);
                      } else {
                        e.currentTarget.style.transform = 'scale(1.05)';
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (status === 'pending') {
                        e.currentTarget.style.opacity = '0.7';
                        e.currentTarget.style.borderColor = rgba(HOPPER_COLORS.rgb.white, 0.2);
                      } else {
                        e.currentTarget.style.transform = 'scale(1)';
                      }
                    }}
                  >
                    {platformIcon}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {v.tiktok_publish_status && (
          <div style={{
            marginTop: '6px',
            fontSize: '0.75rem',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}>
            <span style={{ color: HOPPER_COLORS.grey, flexShrink: 0 }}>TikTok:</span>
            <span style={flexTextStyle}>
              {v.tiktok_publish_status === 'PUBLISHED' && (
                <span style={{ color: HOPPER_COLORS.tokenGreen, fontWeight: '500' }}>Published</span>
              )}
              {v.tiktok_publish_status === 'PROCESSING' && (
                <span style={{ color: HOPPER_COLORS.warning, fontWeight: '500' }}>Processing...</span>
              )}
              {v.tiktok_publish_status === 'FAILED' && (
                <span style={{ color: HOPPER_COLORS.error, fontWeight: '500' }}>Failed</span>
              )}
              {!['PUBLISHED', 'PROCESSING', 'FAILED'].includes(v.tiktok_publish_status) && (
                <span style={{ color: HOPPER_COLORS.grey, fontWeight: '500' }}>{v.tiktok_publish_status}</span>
              )}
              {v.tiktok_publish_error && (
                <span style={{ color: HOPPER_COLORS.error, fontSize: '0.7rem', marginLeft: '4px' }} title={v.tiktok_publish_error}>({v.tiktok_publish_error})</span>
              )}
            </span>
          </div>
        )}
        {v.status === 'uploading' && (
          <div className="progress-bar">
            <div 
              className="progress-fill" 
              style={{ 
                width: `${v.upload_progress !== undefined ? v.upload_progress : (v.progress || 0)}%` 
              }}
            ></div>
          </div>
        )}
        <div className="status" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={flexTextStyle}>
            {v.status === 'uploading' ? (
              v.upload_progress !== undefined ? (
                <span>Uploading {v.upload_progress}%</span>
              ) : v.progress !== undefined && v.progress < 100 ? (
                <span>Uploading to server {v.progress}%</span>
              ) : (
                <span>Processing...</span>
              )
            ) : v.status === 'failed' ? (
              <span style={{ color: HOPPER_COLORS.error }}>Upload Failed</span>
            ) : v.status === 'cancelled' ? (
              <span style={{ color: HOPPER_COLORS.grey }}>Cancelled</span>
            ) : v.scheduled_time ? (
              <span>Scheduled for {new Date(v.scheduled_time).toLocaleString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
              })}</span>
            ) : (
              <span>{v.status}</span>
            )}
          </span>
        </div>
      </div>
      <div className="video-actions">
        {v.status === 'failed' && (
          <button 
            onClick={async () => {
              try {
                await axios.post(`${API}/videos/${v.id}/retry`);
                if (setMessage) setMessage('🔄 Retrying upload...');
                if (loadVideos) loadVideos();
              } catch (err) {
                if (setMessage) setMessage(`❌ ${err.response?.data?.detail || err.message || 'Failed to retry upload'}`);
              }
            }}
            className="retry-upload-btn"
            title="Retry failed upload"
            style={{
              height: '32px',
              minWidth: '32px',
              padding: '0.5rem 0.75rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxSizing: 'border-box'
            }}
          >
            🔄 Retry
          </button>
        )}
        {v.file_size_bytes && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            padding: '0.5rem 0.75rem',
            background: rgba(HOPPER_COLORS.rgb.indigo, 0.15),
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.indigo, 0.3)}`,
            borderRadius: '6px',
            fontSize: '0.75rem',
            color: HOPPER_COLORS.grey,
            fontWeight: '500',
            height: '32px',
            minWidth: '32px',
            boxSizing: 'border-box'
          }}>
            🪙 {v.tokens_consumed || v.tokens_required || 0}
          </div>
        )}
        <button 
          onClick={() => setEditingVideo(v)} 
          className="btn-edit"
          title="Edit video"
          style={{
            height: '32px',
            minWidth: '32px',
            width: '32px',
            padding: '0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.25rem',
            lineHeight: '1',
            background: 'transparent',
            border: `1px solid ${HOPPER_COLORS.greyBorder}`,
            borderRadius: '6px',
            color: HOPPER_COLORS.grey,
            cursor: 'pointer',
            transition: 'all 0.2s',
            boxSizing: 'border-box'
          }}
        >
          ✏️
        </button>
        <button 
          onClick={() => removeVideo(v.id, setMessage)} 
          disabled={v.status === 'uploading'}
          style={{
            height: '32px',
            minWidth: '32px',
            width: '32px',
            padding: '0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.25rem',
            lineHeight: '1',
            background: rgba(HOPPER_COLORS.rgb.adminRed, 0.1),
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.adminRed, 0.3)}`,
            borderRadius: '6px',
            color: HOPPER_COLORS.adminRed,
            cursor: v.status === 'uploading' ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s',
            boxSizing: 'border-box'
          }}
          onMouseEnter={(e) => {
            if (v.status !== 'uploading') {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.2);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.5);
            }
          }}
          onMouseLeave={(e) => {
            if (v.status !== 'uploading') {
              e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.1);
              e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.3);
            }
          }}
          title="Delete video"
        >
          ×
        </button>
      </div>
    </div>
  );
}

