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
export const initiateMultipartUpload = async (filename, fileSize, contentType = null) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/multipart/initiate`, {
    filename,
    file_size: fileSize,
    content_type: contentType
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
export const getPresignedUploadUrl = async (filename, fileSize, contentType = null) => {
  const csrfToken = Cookies.get('csrf_token_client');
  const res = await axios.post(`${API}/upload/presigned`, {
    filename,
    file_size: fileSize,
    content_type: contentType
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
 * @param {function} checkCancellation - Optional function to check if upload is cancelled (returns Promise<boolean>)
 * @returns {Promise<void>}
 */
export const uploadToR2Direct = async (file, uploadUrl, onProgress, checkCancellation = null) => {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let cancellationCheckInterval = null;
    
    // Check cancellation periodically during upload
    if (checkCancellation) {
      cancellationCheckInterval = setInterval(async () => {
        try {
          const cancelled = await checkCancellation();
          if (cancelled) {
            clearInterval(cancellationCheckInterval);
            xhr.abort();
            reject(new Error('Upload cancelled by user'));
          }
        } catch (err) {
          // Ignore errors from cancellation check
          console.warn('Error checking cancellation:', err);
        }
      }, 1000); // Check every second
    }
    
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress({ loaded: e.loaded, total: e.total });
      }
    });
    
    xhr.addEventListener('load', () => {
      if (cancellationCheckInterval) {
        clearInterval(cancellationCheckInterval);
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.statusText}`));
      }
    });
    
    xhr.addEventListener('error', () => {
      if (cancellationCheckInterval) {
        clearInterval(cancellationCheckInterval);
      }
      reject(new Error('Upload failed: network error'));
    });
    
    xhr.addEventListener('abort', () => {
      if (cancellationCheckInterval) {
        clearInterval(cancellationCheckInterval);
      }
      reject(new Error('Upload cancelled by user'));
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
 * @param {function} checkCancellation - Optional function to check if upload is cancelled (returns Promise<boolean>)
 * @returns {Promise<object>} {object_key, size}
 */
export const uploadToR2Multipart = async (file, uploadId, objectKey, onProgress, getPartUrl, completeUpload, checkCancellation = null) => {
  const MULTIPART_PART_SIZE = 100 * 1024 * 1024; // 100MB per part
  const MAX_CONCURRENT_PARTS = 5; // Upload up to 5 parts in parallel
  
  const totalParts = Math.ceil(file.size / MULTIPART_PART_SIZE);
  const parts = [];
  const uploadedParts = [];
  let uploadedBytes = 0;
  let currentXhr = null;
  
  // Upload parts sequentially (can be parallelized later if needed)
  for (let partNumber = 1; partNumber <= totalParts; partNumber++) {
    // Check cancellation before each part
    if (checkCancellation) {
      const cancelled = await checkCancellation();
      if (cancelled) {
        if (currentXhr) {
          currentXhr.abort();
        }
        throw new Error('Upload cancelled by user');
      }
    }
    
    const start = (partNumber - 1) * MULTIPART_PART_SIZE;
    const end = Math.min(start + MULTIPART_PART_SIZE, file.size);
    const partBlob = file.slice(start, end);
    
    // Get multipart part URL for this part
    const { upload_url } = await getPartUrl(objectKey, uploadId, partNumber);
    
    // Upload part
    const etag = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      currentXhr = xhr;
      
      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          // Extract ETag from response headers
          const etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag');
          if (!etag) {
            reject(new Error('Missing ETag in response'));
            return;
          }
          // Remove quotes from ETag if present
          const cleanEtag = etag.replace(/^"|"$/g, '');
          resolve(cleanEtag);
        } else {
          reject(new Error(`Part ${partNumber} upload failed with status ${xhr.status}`));
        }
      });
      
      xhr.addEventListener('error', () => {
        reject(new Error(`Part ${partNumber} upload failed: network error`));
      });
      
      xhr.addEventListener('abort', () => {
        reject(new Error('Upload cancelled by user'));
      });
      
      xhr.open('PUT', upload_url);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.send(partBlob);
    });
    
    currentXhr = null;
    uploadedParts.push({ part_number: partNumber, etag });
    uploadedBytes += (end - start);
    
    // Update progress
    if (onProgress) {
      onProgress({ loaded: uploadedBytes, total: file.size });
    }
  }
  
  // Complete multipart upload
  const result = await completeUpload(objectKey, uploadId, uploadedParts);
  return result;
};