"""Stripe API helper functions"""
import stripe
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from models import User, Subscription, StripeEvent
from stripe_config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, PLANS

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
    
    Args:
        user_id: User ID
        price_id: Stripe price ID
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel
        db: Database session
        
    Returns:
        Checkout session dict with URL, or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create checkout session: STRIPE_SECRET_KEY not set")
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
        
        # Create checkout session
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
                'metadata': {'user_id': str(user_id)}
            }
        )
        
        logger.info(f"Created checkout session for user {user_id}: {session.id}")
        return {
            'session_id': session.id,
            'url': session.url
        }
        
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
        for plan_key, plan_config in PLANS.items():
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


