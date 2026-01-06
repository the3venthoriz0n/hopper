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
 * Cancel video upload
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
