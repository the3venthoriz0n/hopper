import { useState, useCallback } from 'react';
import axios from '../services/api';
import { getApiUrl } from '../services/api';

/**
 * Hook for managing subscription and token balance state
 */
export function useSubscription(user) {
  const [subscription, setSubscription] = useState(null);
  const [tokenBalance, setTokenBalance] = useState(null);
  const [availablePlans, setAvailablePlans] = useState([]);
  const [loadingSubscription, setLoadingSubscription] = useState(false);
  const [loadingPlanKey, setLoadingPlanKey] = useState(null);

  const API = getApiUrl();

  const loadSubscription = useCallback(async () => {
    if (!user) return;
    
    try {
      const [subscriptionRes, plansRes] = await Promise.all([
        axios.get(`${API}/subscription/current`),
        axios.get(`${API}/subscription/plans`)
      ]);
      
      setSubscription(subscriptionRes.data.subscription);
      if (subscriptionRes.data.token_balance) {
        setTokenBalance(subscriptionRes.data.token_balance);
      } else {
        setTokenBalance({
          tokens_remaining: 0,
          tokens_used_this_period: 0,
          monthly_tokens: 0,
          overage_tokens: 0,
          unlimited: false,
          period_start: null,
          period_end: null
        });
      }
      setAvailablePlans(plansRes.data.plans || []);
    } catch (err) {
      console.error('Error loading subscription:', err);
      setSubscription(null);
      setTokenBalance({
        tokens_remaining: 0,
        tokens_used_this_period: 0,
        monthly_tokens: 0,
        overage_tokens: 0,
        unlimited: false,
        period_start: null,
        period_end: null
      });
      try {
        const plansRes = await axios.get(`${API}/subscription/plans`);
        setAvailablePlans(plansRes.data.plans || []);
      } catch (plansErr) {
        console.error('Error loading plans:', plansErr);
        setAvailablePlans([]);
      }
    }
  }, [API, user]);

  const handleUpgrade = useCallback(async (planKey, subscription, availablePlans, setConfirmDialog, setNotification, setLoadingPlanKey, setLoadingSubscription) => {
    if (subscription && subscription.status === 'active' && subscription.plan_type && subscription.plan_type !== 'free' && subscription.plan_type !== 'unlimited') {
      const planName = availablePlans.find(p => p.key === planKey)?.name || planKey;
      const currentPlanName = availablePlans.find(p => p.key === subscription.plan_type)?.name || subscription.plan_type;
      
      const newPlan = availablePlans.find(p => p.key === planKey);
      const currentPlan = availablePlans.find(p => p.key === subscription.plan_type);
      
      const formatPlanPrice = (plan) => {
        if (!plan?.price) return null;
        if (plan.key === 'free') return 'Free';
        if (plan.tokens === -1) return plan.price.formatted;
        
        const monthlyFee = plan.price.amount_dollars || 0;
        const overagePrice = plan.overage_price?.amount_dollars;
        
        if (overagePrice !== undefined && overagePrice !== null) {
          const overageCents = (overagePrice * 100).toFixed(1);
          return `$${monthlyFee.toFixed(2)}/Month (${overageCents}c / token)`;
        } else {
          return `$${monthlyFee.toFixed(2)}/Month`;
        }
      };
      
      const newPlanPrice = formatPlanPrice(newPlan);
      const currentPlanPrice = formatPlanPrice(currentPlan);
      
      if (setConfirmDialog) {
        setConfirmDialog({
          title: 'Upgrade Subscription?',
          message: `You currently have an active ${currentPlanName} subscription${currentPlanPrice ? ` (${currentPlanPrice})` : ''}. Upgrading to ${planName}${newPlanPrice ? ` (${newPlanPrice})` : ''} will cancel your current subscription and replace it with the new plan. Your current token balance will be preserved.`,
          onConfirm: async () => {
            if (setConfirmDialog) setConfirmDialog(null);
            await proceedWithUpgrade(planKey, setLoadingPlanKey, setLoadingSubscription, setNotification);
          },
          onCancel: () => {
            if (setConfirmDialog) setConfirmDialog(null);
          }
        });
      }
    } else {
      await proceedWithUpgrade(planKey, setLoadingPlanKey, setLoadingSubscription, setNotification);
    }
  }, [API]);

  const proceedWithUpgrade = useCallback(async (planKey, setLoadingPlanKey, setLoadingSubscription, setNotification) => {
    if (setLoadingPlanKey) setLoadingPlanKey(planKey);
    if (setLoadingSubscription) setLoadingSubscription(true);
    sessionStorage.removeItem('upgrade_canceled_subscription');
    try {
      const res = await axios.post(`${API}/subscription/create-checkout`, { plan_key: planKey });
      if (res.data.url) {
        if (res.data.canceled_subscription) {
          sessionStorage.setItem('upgrade_canceled_subscription', JSON.stringify({
            canceled_plan_type: res.data.canceled_subscription.plan_type,
            new_plan_key: planKey
          }));
        }
        window.location.href = res.data.url;
      }
    } catch (err) {
      sessionStorage.removeItem('upgrade_canceled_subscription');
      console.error('Error creating checkout session:', err);
      
      if (err.response?.status === 400 && err.response?.data?.portal_url) {
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Active Subscription Found',
            message: 'You already have an active subscription. Opening subscription management...'
          });
          setTimeout(() => {
            if (setNotification) setNotification(null);
            window.location.href = err.response.data.portal_url;
          }, 2000);
        }
      } else if (err.response?.status === 400 && err.response?.data?.message) {
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Checkout Error',
            message: err.response.data.message || 'Failed to start checkout. Please try again.'
          });
          setTimeout(() => setNotification(null), 8000);
        }
      } else {
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Checkout Failed',
            message: err.response?.data?.detail || err.response?.data?.message || 'Failed to start checkout. Please try again.'
          });
          setTimeout(() => setNotification(null), 8000);
        }
      }
    } finally {
      if (setLoadingPlanKey) setLoadingPlanKey(null);
      if (setLoadingSubscription) setLoadingSubscription(false);
    }
  }, [API]);

  const handleManageSubscription = useCallback(async (setMessage, setLoadingSubscription) => {
    if (setLoadingSubscription) setLoadingSubscription(true);
    try {
      const res = await axios.get(`${API}/subscription/portal`);
      if (res.data.url) {
        if (res.data.action === 'purchase') {
          const plansSection = document.getElementById('subscription-plans');
          if (plansSection) {
            plansSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } else {
            window.location.href = res.data.url;
          }
        } else {
          window.location.href = res.data.url;
        }
      }
    } catch (err) {
      console.error('Error opening subscription portal:', err);
      if (setMessage) {
        setMessage('❌ Failed to open subscription management. Please try again.');
      }
    } finally {
      if (setLoadingSubscription) setLoadingSubscription(false);
    }
  }, [API]);

  const handleOpenStripePortal = useCallback(async (setMessage, setLoadingSubscription) => {
    if (setLoadingSubscription) setLoadingSubscription(true);
    try {
      const res = await axios.get(`${API}/subscription/portal`);
      if (res.data.url) {
        window.location.href = res.data.url;
      }
    } catch (err) {
      console.error('Error opening Stripe portal:', err);
      if (setMessage) {
        setMessage('❌ Failed to open subscription management. Please try again.');
      }
      if (setLoadingSubscription) setLoadingSubscription(false);
    }
  }, [API]);

  const handleCancelSubscription = useCallback(async (setMessage, setNotification, setLoadingSubscription, loadSubscription) => {
    if (setLoadingSubscription) setLoadingSubscription(true);
    try {
      const res = await axios.post(`${API}/subscription/cancel`);
      if (res.data.status === 'success') {
        if (setMessage) {
          setMessage(`✅ ${res.data.message || 'Subscription canceled successfully'}`);
        }
        if (loadSubscription) {
          await loadSubscription();
        }
        if (setNotification) {
          setNotification({
            type: 'info',
            title: 'Subscription Canceled',
            message: res.data.message || 'Your subscription has been canceled. You will retain access until the end of your billing period.',
          });
          setTimeout(() => setNotification(null), 10000);
        }
      }
    } catch (err) {
      console.error('Error canceling subscription:', err);
      if (setMessage) {
        setMessage(`❌ ${err.response?.data?.detail || err.response?.data?.message || 'Failed to cancel subscription'}`);
      }
    } finally {
      if (setLoadingSubscription) setLoadingSubscription(false);
    }
  }, [API]);

  return {
    // State
    subscription,
    tokenBalance,
    availablePlans,
    loadingSubscription,
    loadingPlanKey,
    // Setters
    setSubscription,
    setTokenBalance,
    setAvailablePlans,
    setLoadingSubscription,
    setLoadingPlanKey,
    // Functions
    loadSubscription,
    handleUpgrade,
    handleManageSubscription,
    handleOpenStripePortal,
    handleCancelSubscription,
  };
}

