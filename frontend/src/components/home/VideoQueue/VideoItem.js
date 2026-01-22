import React from 'react';
import { PLATFORM_CONFIG } from '../../../utils/platformConfig';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';
import PerimeterProgress from './PerimeterProgress';

const flexTextStyle = { 
  flex: 1, 
  minWidth: 0, 
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  display: 'block',
  width: '100%'
};

// Button dimensions constants - single source of truth
const BUTTON_CONFIG = {
  BORDER_WIDTH: 2,
  PADDING_VERTICAL: 4,
  PADDING_HORIZONTAL: 4,
  SIZE: 32, // Square buttons: same width and height
  BORDER_RADIUS: 6
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
                
                // Use neutral border for all states - perimeter progress indicator shows status
                const borderColor = rgba(HOPPER_COLORS.rgb.white, 0.2);
                const backgroundColor = rgba(HOPPER_COLORS.rgb.white, 0.05);
                
                let title;
                if (status === 'success') {
                  title = `${platformNames[platform]}: Upload successful - Click to view/edit`;
                } else if (status === 'failed') {
                  title = `${platformNames[platform]}: Upload failed - Click to view errors/edit`;
                } else {
                  title = `${platformNames[platform]}: Will upload to this platform - Click to configure`;
                }
                
                // Get platform-specific progress if available
                const platformProgress = v.platform_progress?.[platform];
                
                // Determine progress value and status for perimeter indicator
                // Status priority: success > failed > uploading > pending
                // Only explicit 'success' or 'failed' from backend show colored borders
                // Everything else (pending, undefined, etc.) shows grey
                let progressValue = 0; // Start at 0 to avoid blip to 100%
                let progressStatus = 'pending'; // Default: grey border
                
                if (status === 'success') {
                  // Explicit success from backend - green border
                  progressValue = 100;
                  progressStatus = 'success';
                } else if (status === 'failed') {
                  // Explicit failed from backend - red border
                  progressValue = 100;
                  progressStatus = 'failed';
                } else if (platformProgress !== undefined && typeof platformProgress === 'number' && platformProgress >= 0 && platformProgress <= 100) {
                  // Actively uploading - show progress with orange border
                  // Check if video is uploading OR platform has progress data
                  if (v.status === 'uploading' || status === 'pending') {
                    progressValue = Math.max(0, Math.min(100, platformProgress));
                    progressStatus = 'uploading';
                  } else {
                    // Has progress but video not actively uploading - show as pending
                    progressValue = 0;
                    progressStatus = 'pending';
                  }
                } else {
                  // Pending or any other state - show empty grey border (0% progress)
                  progressValue = 0;
                  progressStatus = 'pending';
                }
                
                return (
                  <div
                    key={platform}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '2px'
                    }}
                  >
                    <button
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
                        padding: `${BUTTON_CONFIG.PADDING_VERTICAL}px ${BUTTON_CONFIG.PADDING_HORIZONTAL}px`,
                        border: 'none',
                        borderRadius: `${BUTTON_CONFIG.BORDER_RADIUS}px`,
                        background: backgroundColor,
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        opacity: status === 'pending' ? 0.7 : 1,
                        width: `${BUTTON_CONFIG.SIZE}px`,
                        height: `${BUTTON_CONFIG.SIZE}px`,
                        minWidth: `${BUTTON_CONFIG.SIZE}px`,
                        position: 'relative' // For perimeter progress positioning
                      }}
                      onMouseEnter={(e) => {
                        if (status === 'pending') {
                          e.currentTarget.style.opacity = '1';
                        } else {
                          e.currentTarget.style.transform = 'scale(1.05)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (status === 'pending') {
                          e.currentTarget.style.opacity = '0.7';
                        } else {
                          e.currentTarget.style.transform = 'scale(1)';
                        }
                      }}
                    >
                      {platformIcon}
                      {/* Perimeter progress indicator - shows status for all states, acts as the border */}
                      <PerimeterProgress
                        progress={progressValue}
                        status={progressStatus}
                        buttonSize={BUTTON_CONFIG.SIZE}
                        padding={BUTTON_CONFIG.PADDING_VERTICAL}
                        borderRadius={BUTTON_CONFIG.BORDER_RADIUS}
                        strokeWidth={2}
                      />
                    </button>
                    {/* Percentage display - always reserve space, only show when uploading */}
                    <span
                      style={{
                        fontSize: '0.6rem',
                        color: HOPPER_COLORS.warning,
                        fontWeight: '500',
                        lineHeight: '1',
                        minHeight: '0.7rem',
                        visibility: (progressStatus === 'uploading' && platformProgress !== undefined && typeof platformProgress === 'number') ? 'visible' : 'hidden'
                      }}
                    >
                      {platformProgress !== undefined && typeof platformProgress === 'number' ? Math.round(platformProgress) : 0}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          {/* Progress bar for hopper server uploads (NOT for destination uploads) */}
          {/* Only show during R2 upload: status is 'uploading', has upload_progress < 100, and no platform_progress (destination uploads haven't started) */}
          {v.status === 'uploading' && 
           v.upload_progress !== undefined && 
           v.upload_progress < 100 && 
           (!v.platform_progress || Object.keys(v.platform_progress).length === 0) && (
            <div className="progress-bar" style={{ marginTop: '0.5rem' }}>
              <div 
                className="progress-fill" 
                style={{ width: `${v.upload_progress}%` }}
              />
            </div>
          )}
        </div>
        {/* Status section - only shows non-upload statuses (scheduled, cancelled, etc.) */}
        <div className="status" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={flexTextStyle}>
            {v.status === 'cancelled' ? (
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
            ) : null}
          </span>
        </div>
      </div>
      <div className="video-actions">
        {/* Retry button for failed or cancelled videos */}
        {(v.status === 'failed' || v.status === 'cancelled') && (
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
            title="Retry upload"
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
        {(() => {
          // Check if video is actively uploading (status or platform progress)
          const isVideoUploading = v.status === 'uploading' || 
            (v.platform_progress && Object.values(v.platform_progress).some(
              progress => typeof progress === 'number' && progress >= 0 && progress < 100
            ));
          
          return (
            <button 
              onClick={() => {
                if (isVideoUploading) {
                  if (setMessage) setMessage('⚠️ Cannot delete video while uploading. Please cancel the upload first.');
                  return;
                }
                removeVideo(v.id, setMessage);
              }} 
              disabled={isVideoUploading}
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
                cursor: isVideoUploading ? 'not-allowed' : 'pointer',
                opacity: isVideoUploading ? 0.5 : 1,
                transition: 'all 0.2s',
                boxSizing: 'border-box'
              }}
              onMouseEnter={(e) => {
                if (!isVideoUploading) {
                  e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.2);
                  e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.5);
                }
              }}
              onMouseLeave={(e) => {
                if (!isVideoUploading) {
                  e.target.style.background = rgba(HOPPER_COLORS.rgb.adminRed, 0.1);
                  e.target.style.borderColor = rgba(HOPPER_COLORS.rgb.adminRed, 0.3);
                }
              }}
              title={isVideoUploading ? 'Cannot delete while uploading. Cancel upload first.' : 'Delete video'}
            >
              ×
            </button>
          );
        })()}
      </div>
    </div>
  );
}

