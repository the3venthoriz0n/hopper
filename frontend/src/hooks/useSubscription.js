import { useState, useCallback, useEffect } from 'react';
import * as subscriptionService from '../services/subscriptionService';

/**
 * Hook for managing subscription and token balance state
 * @param {object} user - Current user object
 * @param {function} setMessage - Message setter function
 * @param {function} setNotification - Notification setter function
 * @param {function} setConfirmDialog - Confirm dialog setter function
 * @param {Array} availablePlans - Available plans array (for display)
 * @returns {object} Subscription state and functions
 */
export function useSubscription(user, setMessage, setNotification, setConfirmDialog, availablePlans) {
  const [subscription, setSubscription] = useState(null);
  const [tokenBalance, setTokenBalance] = useState(null);
  const [availablePlansState, setAvailablePlans] = useState([]);
  const [loadingSubscription, setLoadingSubscription] = useState(false);
  const [loadingPlanKey, setLoadingPlanKey] = useState(null);

  const loadSubscription = useCallback(async () => {
    if (!user) return;
    
    try {
      const data = await subscriptionService.loadSubscription();
      setSubscription(data.subscription);
      setTokenBalance(data.tokenBalance);
      setAvailablePlans(data.plans);
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
        const plans = await subscriptionService.loadPlans();
        setAvailablePlans(plans);
      } catch (plansErr) {
        console.error('Error loading plans:', plansErr);
        setAvailablePlans([]);
      }
    }
  }, [user]);

  useEffect(() => {
    if (user) {
      loadSubscription();
    }
  }, [user, loadSubscription]);

  const handleUpgrade = useCallback(async (planKey) => {
    if (subscription && subscription.status === 'active' && subscription.plan_type && subscription.plan_type !== 'free' && subscription.plan_type !== 'unlimited') {
      const planName = availablePlansState.find(p => p.key === planKey)?.name || planKey;
      const currentPlanName = availablePlansState.find(p => p.key === subscription.plan_type)?.name || subscription.plan_type;
      
      const newPlan = availablePlansState.find(p => p.key === planKey);
      const currentPlan = availablePlansState.find(p => p.key === subscription.plan_type);
      
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
      
      setConfirmDialog({
        title: 'Upgrade Subscription?',
        message: `You currently have an active ${currentPlanName} subscription${currentPlanPrice ? ` (${currentPlanPrice})` : ''}. Upgrading to ${planName}${newPlanPrice ? ` (${newPlanPrice})` : ''} will cancel your current subscription and replace it with the new plan. Your current token balance will be preserved.`,
        onConfirm: async () => {
          setConfirmDialog(null);
          await proceedWithUpgrade(planKey);
        },
        onCancel: () => {
          setConfirmDialog(null);
        }
      });
    } else {
      await proceedWithUpgrade(planKey);
    }
  }, [subscription, availablePlansState, setConfirmDialog]);

  const proceedWithUpgrade = useCallback(async (planKey) => {
    setLoadingPlanKey(planKey);
    setLoadingSubscription(true);
    sessionStorage.removeItem('upgrade_canceled_subscription');
    try {
      const data = await subscriptionService.createCheckout(planKey);
      if (data.url) {
        if (data.canceled_subscription) {
          sessionStorage.setItem('upgrade_canceled_subscription', JSON.stringify({
            canceled_plan_type: data.canceled_subscription.plan_type,
            new_plan_key: planKey
          }));
        }
        window.location.href = data.url;
      }
    } catch (err) {
      sessionStorage.removeItem('upgrade_canceled_subscription');
      console.error('Error creating checkout session:', err);
      
      if (err.response?.status === 400 && err.response?.data?.portal_url) {
        setNotification({
          type: 'error',
          title: 'Active Subscription Found',
          message: 'You already have an active subscription. Opening subscription management...'
        });
        setTimeout(() => {
          setNotification(null);
          window.location.href = err.response.data.portal_url;
        }, 2000);
      } else if (err.response?.status === 400 && err.response?.data?.message) {
        setNotification({
          type: 'error',
          title: 'Checkout Error',
          message: err.response.data.message || 'Failed to start checkout. Please try again.'
        });
        setTimeout(() => setNotification(null), 8000);
      } else {
        setNotification({
          type: 'error',
          title: 'Checkout Failed',
          message: err.response?.data?.detail || err.response?.data?.message || 'Failed to start checkout. Please try again.'
        });
        setTimeout(() => setNotification(null), 8000);
      }
    } finally {
      setLoadingPlanKey(null);
      setLoadingSubscription(false);
    }
  }, [setNotification]);

  const handleOpenStripePortal = useCallback(async () => {
    setLoadingSubscription(true);
    try {
      const data = await subscriptionService.getPortalUrl();
      if (data.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error('Error opening Stripe portal:', err);
      if (setMessage) setMessage('❌ Failed to open subscription management. Please try again.');
      setLoadingSubscription(false);
    }
  }, [setMessage]);

  const handleCancelSubscription = useCallback(async () => {
    setLoadingSubscription(true);
    try {
      const data = await subscriptionService.cancelSubscription();
      if (data.status === 'success') {
        if (setMessage) setMessage(`✅ ${data.message || 'Subscription canceled successfully'}`);
        await loadSubscription();
        setNotification({
          type: 'success',
          title: 'Subscription Canceled',
          message: `Your subscription has been canceled and you've been switched to the free plan. Your ${data.tokens_preserved || 0} tokens have been preserved.`
        });
        setTimeout(() => setNotification(null), 5000);
      } else if (data.status === 'error') {
        if (setMessage) setMessage(`❌ ${data.message || 'Failed to cancel subscription'}`);
        setNotification({
          type: 'error',
          title: 'Cancel Failed',
          message: data.message || 'Cannot cancel this subscription.'
        });
        setTimeout(() => setNotification(null), 5000);
      }
    } catch (err) {
      console.error('Error canceling subscription:', err);
      if (setMessage) setMessage('❌ Failed to cancel subscription. Please try again.');
      setNotification({
        type: 'error',
        title: 'Cancel Failed',
        message: err.response?.data?.detail || err.response?.data?.message || 'Failed to cancel subscription. Please try again.'
      });
      setTimeout(() => setNotification(null), 5000);
    } finally {
      setLoadingSubscription(false);
    }
  }, [setMessage, setNotification, loadSubscription]);

  return {
    subscription,
    tokenBalance,
    availablePlans: availablePlansState,
    loadingSubscription,
    loadingPlanKey,
    setSubscription,
    setTokenBalance,
    loadSubscription,
    handleUpgrade,
    handleOpenStripePortal,
    handleCancelSubscription,
  };
}
