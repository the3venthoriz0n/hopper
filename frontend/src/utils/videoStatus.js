/**
 * Check if a video is currently in progress (actively uploading)
 * 
 * A video is considered "in progress" if:
 * - Video status is "uploading" (R2 upload or destination uploads in progress)
 * - Any platform is "uploading" (actively uploading, not just pending)
 * - Video status is "partial" (some succeeded, others still uploading/failed)
 * - Platform progress shows active uploads (< 100%)
 * - R2 upload progress shows active upload (< 100% and no platform progress)
 * 
 * NOTE: "pending" status (overall or platform) means "ready to upload" NOT "in progress"
 * - Overall status "pending" = R2 upload done, ready for destination uploads (NOT in progress)
 * - Platform status "pending" = destination not started yet (NOT in progress)
 * 
 * @param {object} video - Video object with platform_statuses and status
 * @returns {boolean} True if video is actively uploading, false otherwise
 */
export const isVideoInProgress = (video) => {
  if (!video) return false;
  
  // Explicitly exclude cancelled videos - they are not in progress
  if (video.status === 'cancelled') {
    return false;
  }
  
  // First check: If overall status is "uploading", video is definitely in progress
  // This catches R2 uploads, immediate uploads, and scheduled uploads that have started
  if (video.status === 'uploading') {
    return true;
  }
  
  // Check platform statuses for "uploading" (NOT "pending" - pending means not started)
  // This catches cases where platform uploads have started but overall status hasn't updated yet
  if (video.platform_statuses) {
    const hasUploading = Object.values(video.platform_statuses).some(
      statusData => {
        const status = typeof statusData === 'object' ? statusData.status : statusData;
        // Only "uploading" is in progress, "pending" means ready to start (not in progress)
        return status === 'uploading';
      }
    );
    if (hasUploading) return true;
  }
  
  // Check platform progress - if any platform has progress < 100%, upload is in progress
  if (video.platform_progress && Object.keys(video.platform_progress).length > 0) {
    const hasInProgressProgress = Object.values(video.platform_progress).some(
      progress => typeof progress === 'number' && progress >= 0 && progress < 100
    );
    if (hasInProgressProgress) return true;
  }
  
  // Check if status is partial (some succeeded, others still uploading/failed)
  // Backend should keep status as "uploading" if any are uploading, but check here as safety
  if (video.status === 'partial') return true;
  
  // Additional check: R2 upload in progress (even if status isn't "uploading" yet)
  // This catches R2 uploads that are in progress but status hasn't been updated
  if (video.upload_progress !== undefined && 
      video.upload_progress < 100 && 
      (!video.platform_progress || Object.keys(video.platform_progress).length === 0)) {
    return true;
  }
  
  return false;
};
