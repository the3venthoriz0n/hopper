"""Stripe API helper functions"""
import stripe
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from models import User, Subscription, StripeEvent
from stripe_config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, PLANS, get_plans, get_plan_price_id

logger = logging.getLogger(__name__)


def create_stripe_customer(email: str, user_id: int, db: Session) -> Optional[str]:
    """
    Create a Stripe customer for a user.
    
    Args:
        email: User email
        user_id: User ID
        db: Database session
        
    Returns:
        Stripe customer ID or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create Stripe customer: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        # Check if user already has a customer ID
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.stripe_customer_id:
            logger.info(f"User {user_id} already has Stripe customer: {user.stripe_customer_id}")
            return user.stripe_customer_id
        
        # Create customer in Stripe
        customer = stripe.Customer.create(
            email=email,
            metadata={'user_id': str(user_id)}
        )
        
        # Update user with customer ID
        if user:
            user.stripe_customer_id = customer.id
            db.commit()
        
        logger.info(f"Created Stripe customer for user {user_id}: {customer.id}")
        return customer.id
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating customer for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating Stripe customer for user {user_id}: {e}", exc_info=True)
        return None


def create_checkout_session(user_id: int, price_id: str, success_url: str, cancel_url: str, db: Session) -> Optional[Dict[str, Any]]:
    """
    Create a Stripe checkout session for subscription.
    Prevents duplicate subscriptions by checking for existing active subscriptions.
    
    Args:
        user_id: User ID
        price_id: Stripe price ID
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel
        db: Database session
        
    Returns:
        Checkout session dict with URL, or None if creation failed
        Raises ValueError if user already has an active subscription
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create checkout session: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Check for existing active subscription in database
        existing_subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status == 'active'
        ).first()
        
        if existing_subscription:
            # Check if it's a real Stripe subscription (not free/unlimited)
            if existing_subscription.stripe_subscription_id and not existing_subscription.stripe_subscription_id.startswith(('free_', 'unlimited_')):
                # Verify subscription still exists in Stripe
                try:
                    stripe_sub = stripe.Subscription.retrieve(existing_subscription.stripe_subscription_id)
                    if stripe_sub.status in ['active', 'trialing', 'past_due']:
                        logger.warning(f"User {user_id} already has active Stripe subscription {existing_subscription.stripe_subscription_id}")
                        raise ValueError(f"User already has an active subscription. Please manage your subscription through the customer portal.")
                except stripe.error.StripeError:
                    # Subscription doesn't exist in Stripe, but exists in DB - allow new checkout
                    logger.info(f"User {user_id} has subscription in DB but not in Stripe, allowing new checkout")
            else:
                # Free or unlimited subscription - allow upgrade to paid plan
                logger.info(f"User {user_id} has {existing_subscription.plan_type} plan, allowing upgrade to paid plan")
        
        # Ensure user has Stripe customer
        customer_id = user.stripe_customer_id
        if not customer_id:
            customer_id = create_stripe_customer(user.email, user_id, db)
            if not customer_id:
                return None
        
        # Check Stripe directly for active subscriptions (double-check)
        try:
            stripe_subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='active',
                limit=10
            )
            if stripe_subscriptions.data:
                # User has active subscription in Stripe
                logger.warning(f"User {user_id} has {len(stripe_subscriptions.data)} active subscription(s) in Stripe")
                raise ValueError(f"User already has an active subscription. Please manage your subscription through the customer portal.")
        except stripe.error.StripeError as e:
            # If error checking Stripe, log but continue (might be network issue)
            logger.warning(f"Could not check Stripe subscriptions for user {user_id}: {e}")
        
        # Create checkout session with subscription settings to prevent duplicates
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={'user_id': str(user_id)},
            subscription_data={
                'metadata': {'user_id': str(user_id)},
                # Prevent multiple subscriptions by canceling any existing ones
                # Note: This is handled by our webhook, but Stripe can also handle it
            },
            # Allow promotion codes if needed
            allow_promotion_codes=True,
        )
        
        logger.info(f"Created checkout session for user {user_id}: {session.id}")
        return {
            'session_id': session.id,
            'url': session.url
        }
        
    except ValueError as e:
        # Re-raise ValueError (user already has subscription)
        raise
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout session for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating checkout session for user {user_id}: {e}", exc_info=True)
        return None


def get_customer_portal_url(user_id: int, return_url: str, db: Session) -> Optional[str]:
    """
    Get Stripe customer portal URL for managing subscription.
    
    Args:
        user_id: User ID
        return_url: URL to return to after portal session
        db: Database session
        
    Returns:
        Portal URL or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create portal session: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.stripe_customer_id:
            logger.error(f"User {user_id} has no Stripe customer")
            return None
        
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        
        logger.info(f"Created portal session for user {user_id}: {session.id}")
        return session.url
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating portal session for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating portal session for user {user_id}: {e}", exc_info=True)
        return None


def create_free_subscription(user_id: int, db: Session) -> Optional[Subscription]:
    """
    Create a free subscription for a new user.
    This creates a local subscription record without a Stripe subscription
    (since free plan doesn't require payment).
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    try:
        # Check if user already has a subscription
        existing = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if existing:
            logger.info(f"User {user_id} already has a subscription")
            return existing
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has Stripe customer
        if not user.stripe_customer_id:
            customer_id = create_stripe_customer(user.email, user_id, db)
            if not customer_id:
                logger.error(f"Failed to create Stripe customer for user {user_id}")
                return None
        
        # Create free subscription (no Stripe subscription needed for free plan)
        now = datetime.now(timezone.utc)
        period_end = now.replace(day=1) + timedelta(days=32)  # Next month, same day
        period_end = period_end.replace(day=now.day)  # Keep same day of month
        
        subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=f"free_{user_id}_{int(now.timestamp())}",  # Fake subscription ID for free plan
            stripe_customer_id=user.stripe_customer_id,
            plan_type='free',
            status='active',
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=False,
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        # Initialize token balance with free plan tokens
        from token_helpers import reset_tokens_for_subscription
        reset_tokens_for_subscription(user_id, 'free', now, period_end, db)
        
        logger.info(f"Created free subscription for user {user_id}")
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating free subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def get_subscription_info(user_id: int, db: Session) -> Optional[Dict[str, Any]]:
    """Get subscription information for a user"""
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    if not subscription:
        return None
    
    return {
        'subscription_id': subscription.stripe_subscription_id,
        'plan_type': subscription.plan_type,
        'status': subscription.status,
        'current_period_start': subscription.current_period_start.isoformat(),
        'current_period_end': subscription.current_period_end.isoformat(),
        'cancel_at_period_end': subscription.cancel_at_period_end,
    }


def create_unlimited_subscription(user_id: int, preserved_tokens: int, db: Session) -> Optional[Subscription]:
    """
    Create an unlimited subscription directly in the database (no Stripe subscription needed).
    Works like free subscriptions - creates a database record with a fake subscription ID.
    
    Args:
        user_id: User ID
        preserved_tokens: Token balance to preserve (will be restored when unenrolling)
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has Stripe customer (for consistency, but not required for unlimited)
        if not user.stripe_customer_id:
            customer_id = create_stripe_customer(user.email, user_id, db)
            if not customer_id:
                # Create a placeholder customer ID if Stripe is not available
                customer_id = f"unlimited_customer_{user_id}"
        else:
            customer_id = user.stripe_customer_id
        
        # Check if subscription already exists
        existing = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if existing:
            # Update existing subscription to unlimited
            existing.plan_type = 'unlimited'
            existing.status = 'active'
            existing.stripe_customer_id = customer_id
            existing.preserved_tokens_balance = preserved_tokens
            # Use a fake subscription ID for unlimited (not a real Stripe subscription)
            if not existing.stripe_subscription_id.startswith('unlimited_'):
                existing.stripe_subscription_id = f'unlimited_{user_id}_{int(datetime.now(timezone.utc).timestamp())}'
            # Set period dates (unlimited doesn't expire, but we set monthly periods like free)
            now = datetime.now(timezone.utc)
            period_end = now.replace(day=1) + timedelta(days=32)
            period_end = period_end.replace(day=now.day)
            existing.current_period_start = now
            existing.current_period_end = period_end
            existing.cancel_at_period_end = False
            db.commit()
            db.refresh(existing)
            logger.info(f"Updated subscription to unlimited for user {user_id} (preserved {preserved_tokens} tokens)")
            return existing
        
        # Create new unlimited subscription (no Stripe subscription needed, like free plan)
        now = datetime.now(timezone.utc)
        period_end = now.replace(day=1) + timedelta(days=32)  # Next month, same day
        period_end = period_end.replace(day=now.day)  # Keep same day of month
        
        subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=f'unlimited_{user_id}_{int(now.timestamp())}',
            stripe_customer_id=customer_id,
            plan_type='unlimited',
            status='active',
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=False,
            preserved_tokens_balance=preserved_tokens,
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        logger.info(f"Created unlimited subscription for user {user_id} (preserved {preserved_tokens} tokens)")
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating unlimited subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def create_stripe_subscription(user_id: int, price_id: str, db: Session) -> Optional[Subscription]:
    """
    Create a Stripe subscription directly (admin use, no payment required for unlimited plan).
    
    Args:
        user_id: User ID
        price_id: Stripe price ID for the plan
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create Stripe subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has Stripe customer
        customer_id = user.stripe_customer_id
        if not customer_id:
            customer_id = create_stripe_customer(user.email, user_id, db)
            if not customer_id:
                return None
        
        # Create subscription in Stripe
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
            # For admin-granted unlimited plan, we can set trial_end to None and payment_behavior to 'default_incomplete'
            # But since unlimited is free ($0), it should work without payment
        )
        
        # Update database subscription from Stripe subscription
        subscription = update_subscription_from_stripe(stripe_subscription, db)
        
        logger.info(f"Created Stripe subscription for user {user_id}: {stripe_subscription.id}")
        return subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating subscription for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating Stripe subscription for user {user_id}: {e}", exc_info=True)
        return None


def update_subscription_from_stripe(stripe_subscription: stripe.Subscription, db: Session) -> Optional[Subscription]:
    """
    Update or create subscription record from Stripe subscription object.
    
    Args:
        stripe_subscription: Stripe subscription object
        db: Database session
        
    Returns:
        Subscription model instance or None if update failed
    """
    try:
        user_id = int(stripe_subscription.metadata.get('user_id', 0))
        if not user_id:
            logger.error(f"No user_id in subscription metadata: {stripe_subscription.id}")
            return None
        
        # Determine plan type from price ID
        price_id = stripe_subscription.items.data[0].price.id
        plan_type = 'free'  # Default
        for plan_key, plan_config in get_plans().items():
            if plan_config.get('stripe_price_id') == price_id:
                plan_type = plan_key
                break
        
        # Map Stripe status to our status
        status_map = {
            'active': 'active',
            'canceled': 'canceled',
            'past_due': 'past_due',
            'unpaid': 'unpaid',
            'trialing': 'trialing',
            'incomplete': 'past_due',
            'incomplete_expired': 'canceled',
        }
        status = status_map.get(stripe_subscription.status, 'active')
        
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription.id
        ).first()
        
        if subscription:
            # Update existing
            subscription.plan_type = plan_type
            subscription.status = status
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_subscription.current_period_start, tz=timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_subscription.current_period_end, tz=timezone.utc
            )
            subscription.cancel_at_period_end = stripe_subscription.cancel_at_period_end
            subscription.updated_at = datetime.now(timezone.utc)
        else:
            # Create new
            subscription = Subscription(
                user_id=user_id,
                stripe_subscription_id=stripe_subscription.id,
                stripe_customer_id=stripe_subscription.customer,
                plan_type=plan_type,
                status=status,
                current_period_start=datetime.fromtimestamp(
                    stripe_subscription.current_period_start, tz=timezone.utc
                ),
                current_period_end=datetime.fromtimestamp(
                    stripe_subscription.current_period_end, tz=timezone.utc
                ),
                cancel_at_period_end=stripe_subscription.cancel_at_period_end,
            )
            db.add(subscription)
        
        db.commit()
        db.refresh(subscription)
        
        logger.info(f"Updated subscription {subscription.id} for user {user_id}: {plan_type} plan, {status} status")
        return subscription
        
    except Exception as e:
        logger.error(f"Error updating subscription from Stripe: {e}", exc_info=True)
        db.rollback()
        return None


def log_stripe_event(stripe_event_id: str, event_type: str, payload: Dict[str, Any], db: Session) -> StripeEvent:
    """Log a Stripe webhook event for idempotency"""
    event = db.query(StripeEvent).filter(StripeEvent.stripe_event_id == stripe_event_id).first()
    
    if event:
        return event
    
    event = StripeEvent(
        stripe_event_id=stripe_event_id,
        event_type=event_type,
        processed=False,
        payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    
    return event


def mark_stripe_event_processed(stripe_event_id: str, db: Session, error_message: Optional[str] = None):
    """Mark a Stripe event as processed"""
    event = db.query(StripeEvent).filter(StripeEvent.stripe_event_id == stripe_event_id).first()
    if event:
        event.processed = True
        if error_message:
            event.error_message = error_message
        db.commit()


