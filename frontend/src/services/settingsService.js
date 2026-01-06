import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Load global settings
 * @returns {Promise<object>} Global settings
 */
export const loadGlobalSettings = async () => {
  const res = await axios.get(`${API}/global/settings`);
  return res.data;
};

/**
 * Update global setting
 * @param {string} key - Setting key
 * @param {any} value - Setting value
 * @returns {Promise<object>} Updated settings
 */
export const updateGlobalSettings = async (key, value) => {
  const res = await axios.post(`${API}/global/settings`, { [key]: value });
  return res.data;
};

/**
 * Load YouTube settings
 * @returns {Promise<object>} YouTube settings
 */
export const loadYoutubeSettings = async () => {
  const res = await axios.get(`${API}/youtube/settings`);
  return res.data;
};

/**
 * Update YouTube setting
 * @param {string} key - Setting key
 * @param {any} value - Setting value
 * @returns {Promise<object>} Updated settings
 */
export const updateYoutubeSettings = async (key, value) => {
  const res = await axios.post(`${API}/youtube/settings`, { [key]: value });
  return res.data;
};

/**
 * Load TikTok settings
 * @returns {Promise<object>} TikTok settings
 */
export const loadTiktokSettings = async () => {
  const res = await axios.get(`${API}/tiktok/settings`);
  return res.data;
};

/**
 * Update TikTok setting
 * @param {string} key - Setting key
 * @param {any} value - Setting value
 * @returns {Promise<object>} Updated settings
 */
export const updateTiktokSettings = async (key, value) => {
  const res = await axios.post(`${API}/tiktok/settings`, { [key]: value });
  return res.data;
};

/**
 * Load Instagram settings
 * @returns {Promise<object>} Instagram settings
 */
export const loadInstagramSettings = async () => {
  const res = await axios.get(`${API}/instagram/settings`);
  return res.data;
};

/**
 * Update Instagram setting
 * @param {string} key - Setting key
 * @param {any} value - Setting value
 * @returns {Promise<object>} Updated settings
 */
export const updateInstagramSettings = async (key, value) => {
  const res = await axios.post(`${API}/instagram/settings`, { [key]: value });
  return res.data;
};

/**
 * Add word to wordbank
 * @param {string} word - Word to add
 * @returns {Promise<object>} Updated wordbank
 */
export const addWordToWordbank = async (word) => {
  const res = await axios.post(`${API}/global/wordbank`, { word });
  return res.data;
};

/**
 * Remove word from wordbank
 * @param {string} word - Word to remove
 * @returns {Promise<void>}
 */
export const removeWordFromWordbank = async (word) => {
  await axios.delete(`${API}/global/wordbank/${encodeURIComponent(word)}`);
};

/**
 * Clear wordbank
 * @returns {Promise<void>}
 */
export const clearWordbank = async () => {
  await axios.delete(`${API}/global/wordbank`);
};
