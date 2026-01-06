import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Load destinations (connection status for all platforms)
 * @returns {Promise<object>} Destinations data
 */
export const loadDestinations = async () => {
  const res = await axios.get(`${API}/destinations`);
  return res.data;
};

/**
 * Load platform account info
 * @param {string} platform - Platform name ('youtube', 'tiktok', 'instagram')
 * @returns {Promise<object>} Account data
 */
export const loadPlatformAccount = async (platform) => {
  if (platform === 'tiktok') {
    const res = await axios.get(`${API}/auth/tiktok/account`);
    return res.data;
  }
  const res = await axios.get(`${API}/auth/${platform}/account`);
  return res.data;
};

/**
 * Connect to platform (initiate OAuth)
 * @param {string} platform - Platform name
 * @returns {Promise<string>} OAuth URL
 */
export const connectPlatform = async (platform) => {
  const res = await axios.get(`${API}/auth/${platform}`);
  return res.data.url;
};

/**
 * Disconnect from platform
 * @param {string} platform - Platform name
 * @returns {Promise<void>}
 */
export const disconnectPlatform = async (platform) => {
  await axios.post(`${API}/auth/${platform}/disconnect`);
};

/**
 * Toggle platform enabled status
 * @param {string} platform - Platform name
 * @param {boolean} enabled - New enabled status
 * @returns {Promise<void>}
 */
export const togglePlatform = async (platform, enabled) => {
  await axios.post(`${API}/destinations/${platform}/toggle`, { enabled });
};
