import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Auth service - handles authentication API calls
 */
export const authService = {
  /**
   * Logout user
   */
  async logout() {
    return await axios.post(`${API}/auth/logout`);
  },

  /**
   * Delete user account
   */
  async deleteAccount(csrfToken) {
    return await axios.delete(`${API}/auth/account`, {
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
    });
  },

  /**
   * Get current user
   */
  async getCurrentUser() {
    return await axios.get(`${API}/auth/me`);
  },
};

