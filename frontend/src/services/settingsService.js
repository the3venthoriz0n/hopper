import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Settings service - handles settings API calls
 */
export const settingsService = {
  /**
   * Load global settings
   */
  async loadGlobalSettings() {
    return await axios.get(`${API}/global/settings`);
  },

  /**
   * Update global settings
   */
  async updateGlobalSettings(key, value) {
    return await axios.post(`${API}/global/settings`, { [key]: value });
  },

  /**
   * Load YouTube settings
   */
  async loadYoutubeSettings() {
    return await axios.get(`${API}/youtube/settings`);
  },

  /**
   * Update YouTube settings
   */
  async updateYoutubeSettings(key, value) {
    return await axios.post(`${API}/youtube/settings`, { [key]: value });
  },

  /**
   * Load TikTok settings
   */
  async loadTiktokSettings() {
    return await axios.get(`${API}/tiktok/settings`);
  },

  /**
   * Update TikTok settings
   */
  async updateTiktokSettings(key, value) {
    return await axios.post(`${API}/tiktok/settings`, { [key]: value });
  },

  /**
   * Load Instagram settings
   */
  async loadInstagramSettings() {
    return await axios.get(`${API}/instagram/settings`);
  },

  /**
   * Update Instagram settings
   */
  async updateInstagramSettings(key, value) {
    return await axios.post(`${API}/instagram/settings`, { [key]: value });
  },

  /**
   * Add word to wordbank
   */
  async addWordToWordbank(word) {
    return await axios.post(`${API}/global/wordbank`, { word });
  },

  /**
   * Remove word from wordbank
   */
  async removeWordFromWordbank(word) {
    return await axios.delete(`${API}/global/wordbank`, {
      data: { word }
    });
  },

  /**
   * Clear wordbank
   */
  async clearWordbank() {
    return await axios.delete(`${API}/global/wordbank/clear`);
  },

  /**
   * Load upload limits
   */
  async loadUploadLimits() {
    return await axios.get(`${API}/upload/limits`);
  },
};

