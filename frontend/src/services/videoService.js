import axios from './api';
import { getApiUrl } from './api';
import Cookies from 'js-cookie';

const API = getApiUrl();

/**
 * Load all videos
 * @returns {Promise<Array>} Videos array
 */
export const loadVideos = async () => {
  const res = await axios.get(`${API}/videos`);
  return res.data;
};

/**
 * Upload video file
 * @param {File} file - Video file
 * @param {function} onUploadProgress - Progress callback
 * @param {number} timeout - Request timeout in ms
 * @returns {Promise<object>} Video data
 */
export const uploadVideo = async (file, onUploadProgress, timeout) => {
  const form = new FormData();
  form.append('file', file);
  
  const csrfToken = Cookies.get('csrf_token_client');
  if (csrfToken) {
    form.append('csrf_token', csrfToken);
  }
  
  const res = await axios.post(`${API}/videos`, form, {
    timeout,
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
    onUploadProgress
  });
  
  return res.data;
};

/**
 * Delete video
 * @param {string|number} id - Video ID
 * @returns {Promise<void>}
 */
export const deleteVideo = async (id) => {
  await axios.delete(`${API}/videos/${id}`);
};

/**
 * Delete all videos (except uploading)
 * @returns {Promise<object>} Delete result
 */
export const deleteAllVideos = async () => {
  const res = await axios.delete(`${API}/videos`);
  return res.data;
};

/**
 * Delete uploaded videos
 * @returns {Promise<object>} Delete result
 */
export const deleteUploadedVideos = async () => {
  const res = await axios.delete(`${API}/videos/uploaded`);
  return res.data;
};

/**
 * Cancel scheduled videos
 * @returns {Promise<object>} Cancel result
 */
export const cancelScheduled = async () => {
  const res = await axios.post(`${API}/videos/cancel-scheduled`);
  return res.data;
};

/**
 * Cancel video upload (unified - handles both R2 and destination uploads)
 * Backend automatically detects upload type and cancels appropriately.
 * @param {string|number} id - Video ID
 * @returns {Promise<void>}
 */
export const cancelVideoUpload = async (id) => {
  const csrfToken = Cookies.get('csrf_token_client');
  await axios.post(`${API}/videos/${id}/cancel`, {}, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
};

/**
 * Cancel R2 upload (kept for backward compatibility)
 * Note: This now calls the unified /cancel endpoint which handles both R2 and destination uploads.
 * @param {string|number} id - Video ID
 * @returns {Promise<void>}
 */
export const cancelR2Upload = async (id) => {
  // Backend /cancel-r2 now calls the same unified cancel_upload service
  // Keep this function for backward compatibility
  const csrfToken = Cookies.get('csrf_token_client');
  await axios.post(`${API}/videos/${id}/cancel-r2`, {}, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
};

/**
 * Check if R2 upload is cancelled (for polling during upload)
 * @param {string|number} id - Video ID
 * @returns {Promise<boolean>}
 */
export const checkR2Cancelled = async (id) => {
  const res = await axios.get(`${API}/videos/${id}/r2-cancelled`);
  return res.data.cancelled;
};

/**
 * Abort R2 upload (works for both single and multipart uploads)
 * @param {string|number} videoId - Video ID
 * @returns {Promise<void>}
 */
export const abortR2Upload = async (videoId) => {
  const csrfToken = Cookies.get('csrf_token_client');
  try {
    await axios.post(`${API}/upload/abort`, {
      video_id: videoId
    }, {
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
    });
  } catch (err) {
    // Log but don't throw - cleanup failure shouldn't block cancellation
    console.warn('Failed to abort R2 upload:', err);
  }
};

/**
 * Update R2 upload progress (publishes via WebSocket)
 * @param {string|number} videoId - Video ID
 * @param {number} progressPercent - Progress percentage (0-100)
 * @returns {Promise<void>}
 */
export const updateR2UploadProgress = async (videoId, progressPercent) => {
  const csrfToken = Cookies.get('csrf_token_client');
  try {
    await axios.post(`${API}/videos/${videoId}/progress`, {
      video_id: videoId,
      progress_percent: progressPercent
    }, {
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
    });
  } catch (err) {
    // Log but don't throw - progress update failure shouldn't block upload
    console.warn('Failed to update R2 upload progress:', err);
  }
};

/**
 * Update video settings
 * @param {string|number} videoId - Video ID
 * @param {object} settings - Settings object
 * @returns {Promise<void>}
 */
export const updateVideoSettings = async (videoId, settings) => {
  const filteredSettings = {};
  Object.entries(settings).forEach(([key, value]) => {
    if (value !== null && value !== undefined) {
      filteredSettings[key] = value;
    }
  });
  
  await axios.patch(`${API}/videos/${videoId}`, filteredSettings);
};

/**
 * Recompute video title
 * @param {string|number} videoId - Video ID
 * @returns {Promise<void>}
 */
export const recomputeVideoTitle = async (videoId) => {
  await axios.post(`${API}/videos/${videoId}/recompute-title`);
};

/**
 * Recompute video field for specific platform
 * @param {string|number} videoId - Video ID
 * @param {string} platform - Platform name
 * @returns {Promise<void>}
 */
export const recomputeVideoField = async (videoId, platform) => {
  await axios.post(`${API}/videos/${videoId}/recompute-title?platform=${platform}`);
};

/**
 * Recompute all videos for platform
 * @param {string} platform - Platform name
 * @returns {Promise<object>} Recompute result
 */
export const recomputeAllVideos = async (platform) => {
  const res = await axios.post(`${API}/videos/recompute-all/${platform}`);
  return res.data;
};

/**
 * Reorder videos
 * @param {Array<string|number>} videoIds - Array of video IDs in new order
 * @returns {Promise<void>}
 */
export const reorderVideos = async (videoIds) => {
  await axios.post(`${API}/videos/reorder`, { video_ids: videoIds });
};

/**
 * Upload videos (start upload process)
 * @returns {Promise<object>} Upload result
 */
export const uploadVideos = async () => {
  const res = await axios.post(`${API}/upload`);
  return res.data;
};

/**
 * Retry failed video upload
 * @param {string|number} id - Video ID
 * @returns {Promise<void>}
 */
export const retryVideoUpload = async (id) => {
  await axios.post(`${API}/videos/${id}/retry`);
};

/**
 * Get queue token count (backend is source of truth)
 * @returns {Promise<number>} Queue token count
 */
export const getQueueTokenCount = async () => {
  const res = await axios.get(`${API}/videos/queue-token-count`);
  return res.data.queue_token_count;
};


/**
 * Initiate multipart upload for large files
 * @param {string} filename - File name
 * @param {number} fileSize - File size in bytes
 * @param {string} contentType - Content type (MIME type)
 * @returns {Promise<object>} {upload_id, object_key, expires_in}
 */
export const initiateMultipartUpload = async (filename, fileSize, contentType = null, videoId = null) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/multipart/initiate`, {
    filename,
    file_size: fileSize,
    content_type: contentType,
    video_id: videoId
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Get multipart part URL for uploading a part in multipart upload
 * @param {string} objectKey - R2 object key
 * @param {string} uploadId - Multipart upload ID
 * @param {number} partNumber - Part number (1-indexed)
 * @returns {Promise<object>} {upload_url, expires_in}
 * Note: This uses multipart part URLs, not the single-file presigned endpoint
 */
export const getMultipartPartUrl = async (objectKey, uploadId, partNumber) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/multipart/part-url`, {
    object_key: objectKey,
    upload_id: uploadId,
    part_number: partNumber
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Complete multipart upload
 * @param {string} objectKey - R2 object key
 * @param {string} uploadId - Multipart upload ID
 * @param {Array<{part_number: number, etag: string}>} parts - Array of parts with ETags
 * @returns {Promise<object>} {object_key, size}
 */
export const completeMultipartUpload = async (objectKey, uploadId, parts) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/multipart/complete`, {
    object_key: objectKey,
    upload_id: uploadId,
    parts: parts.map(p => ({ part_number: p.part_number, etag: p.etag }))
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Initiate upload - create video record immediately with 'uploading' status
 * @param {string} filename - File name
 * @param {number} fileSize - File size in bytes
 * @returns {Promise<object>} Video data
 */
export const initiateUpload = async (filename, fileSize) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/initiate`, {
    filename,
    file_size: fileSize
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Confirm upload and update video record
 * @param {number} videoId - Video ID
 * @param {string} objectKey - R2 object key
 * @param {string} filename - File name
 * @param {number} fileSize - File size in bytes
 * @returns {Promise<object>} Video data
 */
export const confirmUpload = async (videoId, objectKey, filename, fileSize) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/confirm`, {
    video_id: videoId,
    object_key: objectKey,
    filename,
    file_size: fileSize
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Fail upload - remove video record on upload failure
 * @param {number} videoId - Video ID
 * @returns {Promise<object>} Response
 */
export const failUpload = async (videoId) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/fail`, {
    video_id: videoId
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Get presigned upload URL for single file upload
 * @param {string} filename - File name
 * @param {number} fileSize - File size in bytes
 * @param {string} contentType - Content type (MIME type), optional
 * @returns {Promise<object>} {upload_url, object_key, expires_in}
 */
export const getPresignedUploadUrl = async (filename, fileSize, contentType = null, videoId = null) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/presigned`, {
    filename,
    file_size: fileSize,
    content_type: contentType,
    video_id: videoId
  }, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
  });
  return res.data;
};

/**
 * Upload file directly to R2 using presigned URL
 * @param {File} file - File to upload
 * @param {string} uploadUrl - Presigned upload URL
 * @param {function} onProgress - Progress callback (receives {loaded, total})
 * @param {object} cancellationListener - Cancellation listener object with isCancelled(videoId) method
 * @param {number} videoId - Video ID for cancellation checking and cleanup
 * @returns {Promise<void>}
 */
export const uploadToR2Direct = async (file, uploadUrl, onProgress, cancellationListener = null, videoId = null) => {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let cancellationCheckInterval = null;
    let isCancelled = false; // Track if we intentionally cancelled
    let isResolved = false; // Prevent multiple rejections/resolutions
    
    // Helper to reject with cancellation message
    const rejectCancelled = () => {
      if (!isResolved) {
        isResolved = true;
        isCancelled = true;
        if (cancellationCheckInterval) {
          clearInterval(cancellationCheckInterval);
        }
        reject(new Error('Upload cancelled by user'));
      }
    };
    
    // Check cancellation using event listener (real-time, no polling delay)
    if (cancellationListener && videoId) {
      cancellationCheckInterval = setInterval(() => {
        try {
          // Use event-driven cancellation check (instant, no HTTP request)
          if (cancellationListener.isCancelled(videoId)) {
            clearInterval(cancellationCheckInterval);
            isCancelled = true;
            xhr.abort();
            // Clean up R2 upload (abort multipart if applicable)
            abortR2Upload(videoId).catch(err => {
              console.warn('Failed to abort R2 upload on cancellation:', err);
            });
            rejectCancelled();
          }
        } catch (err) {
          // Ignore errors from cancellation check
          console.warn('Error checking cancellation:', err);
        }
      }, 100); // Check frequently (100ms) since it's just checking a Set, no HTTP overhead
    }
    
    let lastReportedProgress = -1;
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        const percent = Math.round((e.loaded * 100) / e.total);
        onProgress({ loaded: e.loaded, total: e.total });
        
        // Report progress to backend for WebSocket publishing (throttled to 1% increments)
        if (videoId && (percent - lastReportedProgress >= 1 || percent === 100)) {
          lastReportedProgress = percent;
          updateR2UploadProgress(videoId, percent).catch(err => {
            // Silently fail - progress updates are best effort
          });
        }
      }
    });
    
    xhr.addEventListener('load', () => {
      if (isResolved || isCancelled) return;
      if (cancellationCheckInterval) {
        clearInterval(cancellationCheckInterval);
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        isResolved = true;
        resolve();
      } else {
        isResolved = true;
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.statusText}`));
      }
    });
    
    xhr.addEventListener('error', () => {
      // If we intentionally cancelled, use cancellation message
      if (isCancelled) {
        rejectCancelled();
        return;
      }
      if (isResolved) return;
      if (cancellationCheckInterval) {
        clearInterval(cancellationCheckInterval);
      }
      isResolved = true;
      reject(new Error('Upload failed: network error'));
    });
    
    xhr.addEventListener('abort', () => {
      rejectCancelled();
    });
    
    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.send(file);
  });
};

/**
 * Upload file to R2 using multipart upload
 * @param {File} file - File to upload
 * @param {string} uploadId - Multipart upload ID
 * @param {string} objectKey - R2 object key
 * @param {function} onProgress - Progress callback (receives {loaded, total})
 * @param {function} getPartUrl - Function to get multipart part URL for a part
 * @param {function} completeUpload - Function to complete multipart upload
 * @param {object} cancellationListener - Cancellation listener object with isCancelled(videoId) method
 * @param {number} videoId - Video ID for cancellation checking and cleanup
 * @returns {Promise<object>} {object_key, size}
 */
export const uploadToR2Multipart = async (file, uploadId, objectKey, onProgress, getPartUrl, completeUpload, cancellationListener = null, videoId = null) => {
  const MULTIPART_PART_SIZE = 100 * 1024 * 1024; // 100MB per part
  const MAX_CONCURRENT_PARTS = 5; // Upload up to 5 parts in parallel
  
  const totalParts = Math.ceil(file.size / MULTIPART_PART_SIZE);
  const parts = [];
  const uploadedParts = [];
  let uploadedBytes = 0;
  let currentXhr = null;
  let isCancelled = false; // Track cancellation state across the loop
  let lastReportedProgress = -1; // Track last reported progress for throttling
  
  // Upload parts sequentially (can be parallelized later if needed)
  for (let partNumber = 1; partNumber <= totalParts; partNumber++) {
    // Check cancellation before each part (event-driven, instant check)
    if (cancellationListener && videoId && cancellationListener.isCancelled(videoId)) {
      isCancelled = true;
      if (currentXhr) {
        currentXhr.abort();
      }
      // Clean up R2 upload (abort multipart upload) - fire immediately
      abortR2Upload(videoId).catch(err => {
        console.warn('Failed to abort R2 upload on cancellation:', err);
      });
      throw new Error('Upload cancelled by user');
    }
    
    // If cancelled, break immediately (shouldn't reach here, but safety check)
    if (isCancelled) {
      throw new Error('Upload cancelled by user');
    }
    
    const start = (partNumber - 1) * MULTIPART_PART_SIZE;
    const end = Math.min(start + MULTIPART_PART_SIZE, file.size);
    const partBlob = file.slice(start, end);
    
    // Check cancellation again before getting part URL (event-driven)
    if (cancellationListener && videoId && cancellationListener.isCancelled(videoId)) {
      isCancelled = true;
      abortR2Upload(videoId).catch(err => {
        console.warn('Failed to abort R2 upload on cancellation:', err);
      });
      throw new Error('Upload cancelled by user');
    }
    
    // Get multipart part URL for this part
    const { upload_url } = await getPartUrl(objectKey, uploadId, partNumber);
    
    // Check cancellation one more time right before uploading the part (event-driven)
    if (cancellationListener && videoId && cancellationListener.isCancelled(videoId)) {
      isCancelled = true;
      abortR2Upload(videoId).catch(err => {
        console.warn('Failed to abort R2 upload on cancellation:', err);
      });
      throw new Error('Upload cancelled by user');
    }
    
    // Upload part - wrap in try-catch to handle cancellation even if part completes
    let etag;
    try {
      etag = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      currentXhr = xhr;
      let partCancelled = false;
      let isResolved = false;
      let partCancellationCheckInterval = null;
      
      // Helper to reject with cancellation message
      const rejectCancelled = () => {
        if (!isResolved) {
          isResolved = true;
          partCancelled = true;
          isCancelled = true; // Set outer flag
          if (partCancellationCheckInterval) {
            clearInterval(partCancellationCheckInterval);
          }
          reject(new Error('Upload cancelled by user'));
        }
      };
      
      // Check cancellation periodically during part upload (event-driven, no HTTP overhead)
      if (cancellationListener && videoId) {
        partCancellationCheckInterval = setInterval(() => {
          try {
            // Use event-driven cancellation check (instant, no HTTP request)
            if (cancellationListener.isCancelled(videoId)) {
              clearInterval(partCancellationCheckInterval);
              partCancelled = true;
              isCancelled = true; // Set outer flag
              xhr.abort();
              // Clean up R2 upload (abort multipart upload) - fire immediately
              abortR2Upload(videoId).catch(err => {
                console.warn('Failed to abort R2 upload on cancellation:', err);
              });
              rejectCancelled();
            }
          } catch (err) {
            // Ignore errors from cancellation check
            console.warn('Error checking cancellation:', err);
          }
        }, 100); // Check frequently (100ms) since it's just checking a Set, no HTTP overhead
      }
      
      xhr.addEventListener('load', () => {
        if (isResolved || partCancelled) return;
        if (partCancellationCheckInterval) {
          clearInterval(partCancellationCheckInterval);
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          // Extract ETag from response headers
          const etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag');
          if (!etag) {
            isResolved = true;
            reject(new Error('Missing ETag in response'));
            return;
          }
          // Remove quotes from ETag if present
          const cleanEtag = etag.replace(/^"|"$/g, '');
          isResolved = true;
          resolve(cleanEtag);
        } else {
          isResolved = true;
          reject(new Error(`Part ${partNumber} upload failed with status ${xhr.status}`));
        }
      });
      
      xhr.addEventListener('error', () => {
        // If we intentionally cancelled, use cancellation message
        if (partCancelled) {
          rejectCancelled();
          return;
        }
        if (isResolved) return;
        if (partCancellationCheckInterval) {
          clearInterval(partCancellationCheckInterval);
        }
        isResolved = true;
        reject(new Error(`Part ${partNumber} upload failed: network error`));
      });
      
      xhr.addEventListener('abort', () => {
        rejectCancelled();
      });
      
      xhr.open('PUT', upload_url);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.send(partBlob);
      });
      
      // Check cancellation immediately after part completes (before adding to uploadedParts)
      if (cancellationListener && videoId && !isCancelled) {
        if (cancellationListener.isCancelled(videoId)) {
          isCancelled = true;
          // Clean up R2 upload (abort multipart upload) - fire immediately
          abortR2Upload(videoId).catch(err => {
            console.warn('Failed to abort R2 upload on cancellation:', err);
          });
          throw new Error('Upload cancelled by user');
        }
      }
    } catch (err) {
      // If cancellation error, re-throw immediately
      if (err.message?.includes('cancelled') || err.message?.includes('aborted')) {
        // Make sure abort is called if not already
        if (videoId && !isCancelled) {
          isCancelled = true;
          abortR2Upload(videoId).catch(abortErr => {
            console.warn('Failed to abort R2 upload on cancellation:', abortErr);
          });
        }
        throw err;
      }
      // Re-throw other errors
      throw err;
    }
    
    currentXhr = null;
    uploadedParts.push({ part_number: partNumber, etag });
    uploadedBytes += (end - start);
    
    // Update progress
    if (onProgress) {
      const percent = Math.round((uploadedBytes * 100) / file.size);
      onProgress({ loaded: uploadedBytes, total: file.size });
      
      // Report progress to backend for WebSocket publishing (throttled to 1% increments)
      if (videoId && (percent - lastReportedProgress >= 1 || percent === 100)) {
        lastReportedProgress = percent;
        updateR2UploadProgress(videoId, percent).catch(err => {
          // Silently fail - progress updates are best effort
        });
      }
    }
  }
  
  // If cancelled, don't complete the upload
  if (isCancelled) {
    throw new Error('Upload cancelled by user');
  }
  
  // Complete multipart upload
  const result = await completeUpload(objectKey, uploadId, uploadedParts);
  return result;
};