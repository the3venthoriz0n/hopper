import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Logout user
 * @returns {Promise<void>}
 */
export const logout = async () => {
  await axios.post(`${API}/auth/logout`);
  window.location.href = '/login';
};

/**
 * Delete user account
 * @returns {Promise<void>}
 */
export const deleteAccount = async () => {
  await axios.delete(`${API}/auth/account`, {
    headers: {
      'Content-Type': 'application/json'
    }
  });
  window.location.href = '/login';
};

/**
 * Send password reset email
 * @param {string} email - User email
 * @returns {Promise<void>}
 */
export const forgotPassword = async (email) => {
  await axios.post(`${API}/auth/forgot-password`, { email });
};
