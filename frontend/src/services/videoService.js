import axios from './api';
import { getApiUrl } from './api';
import Cookies from 'js-cookie';

const API = getApiUrl();

/**
 * Video service - handles video-related API calls
 */
export const videoService = {
  /**
   * Load all videos
   */
  async loadVideos() {
    return await axios.get(`${API}/videos`);
  },

  /**
   * Add video (upload file)
   */
  async addVideo(formData, onUploadProgress, timeout) {
    const csrfToken = Cookies.get('csrf_token_client');
    if (csrfToken) {
      formData.append('csrf_token', csrfToken);
    }
    
    return await axios.post(`${API}/videos`, formData, {
      timeout,
      maxContentLength: Infinity,
      maxBodyLength: Infinity,
      onUploadProgress
    });
  },

  /**
   * Delete video
   */
  async deleteVideo(videoId) {
    return await axios.delete(`${API}/videos/${videoId}`);
  },

  /**
   * Delete all videos
   */
  async deleteAllVideos() {
    return await axios.delete(`${API}/videos`);
  },

  /**
   * Delete uploaded videos
   */
  async deleteUploadedVideos() {
    return await axios.delete(`${API}/videos/uploaded`);
  },

  /**
   * Update video settings
   */
  async updateVideo(videoId, settings) {
    const filteredSettings = {};
    Object.entries(settings).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        filteredSettings[key] = value;
      }
    });
    return await axios.patch(`${API}/videos/${videoId}`, filteredSettings);
  },

  /**
   * Reorder videos
   */
  async reorderVideos(videoIds) {
    return await axios.post(`${API}/videos/reorder`, { video_ids: videoIds });
  },

  /**
   * Cancel video upload
   */
  async cancelVideo(videoId, csrfToken) {
    return await axios.post(`${API}/videos/${videoId}/cancel`, {}, {
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
    });
  },

  /**
   * Cancel scheduled videos
   */
  async cancelScheduled() {
    return await axios.post(`${API}/videos/cancel-scheduled`);
  },

  /**
   * Recompute video title
   */
  async recomputeTitle(videoId, platform = null) {
    const url = platform 
      ? `${API}/videos/${videoId}/recompute-title?platform=${platform}`
      : `${API}/videos/${videoId}/recompute-title`;
    return await axios.post(url);
  },

  /**
   * Recompute all videos for platform
   */
  async recomputeAll(platform) {
    return await axios.post(`${API}/videos/recompute-all/${platform}`);
  },

  /**
   * Upload videos (start upload process)
   */
  async upload() {
    return await axios.post(`${API}/upload`);
  },
};

