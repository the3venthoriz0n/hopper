import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Subscription service - handles subscription and token API calls
 */
export const subscriptionService = {
  /**
   * Load current subscription
   */
  async loadCurrentSubscription() {
    return await axios.get(`${API}/subscription/current`);
  },

  /**
   * Load available plans
   */
  async loadPlans() {
    return await axios.get(`${API}/subscription/plans`);
  },

  /**
   * Create checkout session for plan upgrade
   */
  async createCheckout(planKey) {
    return await axios.post(`${API}/subscription/create-checkout`, { plan_key: planKey });
  },

  /**
   * Get Stripe customer portal URL
   */
  async getPortalUrl() {
    return await axios.get(`${API}/subscription/portal`);
  },

  /**
   * Cancel subscription
   */
  async cancelSubscription() {
    return await axios.post(`${API}/subscription/cancel`);
  },
};

