import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Platform service - handles platform connection/disconnection API calls
 */
export const platformService = {
  /**
   * Get OAuth URL for platform connection
   */
  async getOAuthUrl(platform) {
    const res = await axios.get(`${API}/auth/${platform}`);
    return res.data.url;
  },

  /**
   * Disconnect platform
   */
  async disconnect(platform) {
    return await axios.post(`${API}/auth/${platform}/disconnect`);
  },

  /**
   * Toggle platform enabled/disabled
   */
  async toggle(platform, enabled) {
    return await axios.post(`${API}/destinations/${platform}/toggle`, {
      enabled
    });
  },

  /**
   * Load platform account info
   */
  async loadAccount(platform) {
    return await axios.get(`${API}/auth/${platform}/account`);
  },

  /**
   * Load all destinations
   */
  async loadDestinations() {
    return await axios.get(`${API}/destinations`);
  },

  /**
   * Load YouTube videos
   */
  async loadYoutubeVideos(page = 1, hideShorts = false) {
    return await axios.get(`${API}/youtube/videos?page=${page}&per_page=50&hide_shorts=${hideShorts}`);
  },
};

