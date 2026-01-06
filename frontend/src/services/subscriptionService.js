import axios from './api';
import { getApiUrl } from './api';

const API = getApiUrl();

/**
 * Load current subscription and token balance
 * @returns {Promise<object>} Subscription and token balance data
 */
export const loadSubscription = async () => {
  const [subscriptionRes, plansRes] = await Promise.all([
    axios.get(`${API}/subscription/current`),
    axios.get(`${API}/subscription/plans`)
  ]);
  
  return {
    subscription: subscriptionRes.data.subscription,
    tokenBalance: subscriptionRes.data.token_balance || {
      tokens_remaining: 0,
      tokens_used_this_period: 0,
      monthly_tokens: 0,
      overage_tokens: 0,
      unlimited: false,
      period_start: null,
      period_end: null
    },
    plans: plansRes.data.plans || []
  };
};

/**
 * Load available plans
 * @returns {Promise<Array>} Available plans
 */
export const loadPlans = async () => {
  const res = await axios.get(`${API}/subscription/plans`);
  return res.data.plans || [];
};

/**
 * Create checkout session for plan upgrade
 * @param {string} planKey - Plan key
 * @returns {Promise<object>} Checkout session data
 */
export const createCheckout = async (planKey) => {
  const res = await axios.post(`${API}/subscription/create-checkout`, { plan_key: planKey });
  return res.data;
};

/**
 * Get checkout status
 * @param {string} sessionId - Stripe session ID
 * @returns {Promise<object>} Checkout status
 */
export const getCheckoutStatus = async (sessionId) => {
  const res = await axios.get(`${API}/subscription/checkout-status`, {
    params: { session_id: sessionId }
  });
  return res.data;
};

/**
 * Get Stripe customer portal URL
 * @returns {Promise<object>} Portal URL and action
 */
export const getPortalUrl = async () => {
  const res = await axios.get(`${API}/subscription/portal`);
  return res.data;
};

/**
 * Cancel subscription
 * @returns {Promise<object>} Cancel result
 */
export const cancelSubscription = async () => {
  const res = await axios.post(`${API}/subscription/cancel`);
  return res.data;
};
