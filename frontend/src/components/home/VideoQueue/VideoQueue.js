import React from 'react';
import VideoItem from './VideoItem';
import { HOPPER_COLORS, rgba, getGradient } from '../../../utils/colors';

export default function VideoQueue({
  videos,
  derivedMessage,
  expandedVideos,
  setExpandedVideos,
  draggedVideo,
  youtube,
  tiktok,
  instagram,
  calculateQueueTokenCost,
  clearUploadedVideos,
  clearAllVideos,
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
  return (
    <>
      {derivedMessage && <div className="message">{derivedMessage}</div>}
      <div className="card">
        <div className="queue-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            Queue ({videos.length})
            <span style={{
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
              🪙 {calculateQueueTokenCost()}
            </span>
          </h2>
          <div className="queue-buttons" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {videos.length > 0 && videos.some(v => v.status === 'uploaded' || v.status === 'completed') && (
              <button
                onClick={clearUploadedVideos}
                style={{
                  padding: '0.5rem 1rem',
                  background: getGradient(HOPPER_COLORS.error, 0.9, 0.9),
                  border: `1px solid ${HOPPER_COLORS.error}`,
                  borderRadius: '8px',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: '600',
                  transition: 'all 0.2s',
                  boxShadow: `0 2px 8px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`
                }}
                onMouseEnter={(e) => {
                  e.target.style.background = getGradient(HOPPER_COLORS.error, 1.0, 1.0);
                  e.target.style.transform = 'translateY(-1px)';
                  e.target.style.boxShadow = `0 4px 12px ${rgba(HOPPER_COLORS.rgb.error, 0.4)}`;
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = getGradient(HOPPER_COLORS.error, 0.9, 0.9);
                  e.target.style.transform = 'translateY(0)';
                  e.target.style.boxShadow = `0 2px 8px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`;
                }}
              >
                Clear Uploaded
              </button>
            )}
            {videos.length > 0 && videos.some(v => v.status !== 'uploading') && (
              <button
                onClick={clearAllVideos}
                style={{
                  padding: '0.5rem 1rem',
                  background: getGradient(HOPPER_COLORS.error, 0.9, 0.9),
                  border: `1px solid ${HOPPER_COLORS.error}`,
                  borderRadius: '8px',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: '600',
                  transition: 'all 0.2s',
                  boxShadow: `0 2px 8px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`
                }}
                onMouseEnter={(e) => {
                  e.target.style.background = getGradient(HOPPER_COLORS.error, 1.0, 1.0);
                  e.target.style.transform = 'translateY(-1px)';
                  e.target.style.boxShadow = `0 4px 12px ${rgba(HOPPER_COLORS.rgb.error, 0.4)}`;
                }}
                onMouseLeave={(e) => {
                  e.target.style.background = getGradient(HOPPER_COLORS.error, 0.9, 0.9);
                  e.target.style.transform = 'translateY(0)';
                  e.target.style.boxShadow = `0 2px 8px ${rgba(HOPPER_COLORS.rgb.error, 0.3)}`;
                }}
              >
                Clear All
              </button>
            )}
          </div>
        </div>
        {videos.length === 0 ? (
          <p className="empty">No videos</p>
        ) : (
          videos.map(v => (
            <VideoItem
              key={v.id}
              video={v}
              isExpanded={expandedVideos.has(v.id)}
              draggedVideo={draggedVideo}
              youtube={youtube}
              tiktok={tiktok}
              instagram={instagram}
              handleDragStart={handleDragStart}
              handleDragEnd={handleDragEnd}
              handleDragOver={handleDragOver}
              handleDrop={handleDrop}
              formatFileSize={formatFileSize}
              setDestinationModal={setDestinationModal}
              setEditingVideo={setEditingVideo}
              removeVideo={removeVideo}
              setMessage={setMessage}
              loadVideos={loadVideos}
              API={API}
              axios={axios}
              expandedVideos={expandedVideos}
              setExpandedVideos={setExpandedVideos}
            />
          ))
        )}
      </div>
    </>
  );
}

