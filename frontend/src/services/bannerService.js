import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Get banner message (requires authentication)
 * @returns {Promise<object>} Banner object with message and enabled
 */
export const getBanner = async () => {
  const res = await axios.get(`${API}/banner`);
  return res.data;
};

/**
 * Update banner message (admin only)
 * @param {string} message - Banner message text
 * @param {boolean} enabled - Whether banner is enabled
 * @returns {Promise<object>} Updated banner
 */
export const updateBanner = async (message, enabled) => {
  const res = await axios.post(`${API}/admin/banner`, { message, enabled });
  return res.data;
};
