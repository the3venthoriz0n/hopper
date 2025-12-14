"""Stripe API helper functions"""
import stripe
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta

from models import User, Subscription, StripeEvent
from stripe_config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, get_plans

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
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
            
        if user.stripe_customer_id:
            logger.info(f"User {user_id} already has Stripe customer: {user.stripe_customer_id}")
            return user.stripe_customer_id
        
        customer = stripe.Customer.create(
            email=email,
            metadata={'user_id': str(user_id)}
        )
        
        user.stripe_customer_id = customer.id
        db.commit()
        
        logger.info(f"Created Stripe customer for user {user_id}: {customer.id}")
        return customer.id
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating customer for user {user_id}: {e}")
        db.rollback()
        return None
    except Exception as e:
        logger.error(f"Error creating Stripe customer for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def _has_active_paid_subscription(customer_id: str, exclude_subscription_id: Optional[str] = None) -> bool:
    """
    Check if customer has any active paid subscriptions in Stripe.
    
    Args:
        customer_id: Stripe customer ID
        exclude_subscription_id: Subscription ID to exclude from check
        
    Returns:
        True if customer has active paid subscription, False otherwise
    """
    try:
        subscriptions = stripe.Subscription.list(
            customer=customer_id,
            status='active',
            limit=10
        )
        
        for sub in subscriptions.data:
            # Skip excluded subscription
            if exclude_subscription_id and sub.id == exclude_subscription_id:
                continue
                
            # Check if subscription has paid items
            full_sub = stripe.Subscription.retrieve(sub.id)
            if (hasattr(full_sub, 'items') and 
                full_sub.items and 
                hasattr(full_sub.items, 'data') and 
                full_sub.items.data):
                
                for item in full_sub.items.data:
                    price = item.price
                    if (price and 
                        hasattr(price, 'unit_amount') and 
                        price.unit_amount and 
                        price.unit_amount > 0):
                        return True
        
        return False
        
    except stripe.error.StripeError as e:
        logger.warning(f"Error checking Stripe subscriptions for customer {customer_id}: {e}")
        return False


def create_checkout_session(
    user_id: int, 
    price_id: str, 
    success_url: str, 
    cancel_url: str, 
    db: Session
) -> Optional[Dict[str, Any]]:
    """
    Create a Stripe checkout session for subscription.
    Prevents duplicate paid subscriptions.
    
    Args:
        user_id: User ID
        price_id: Stripe price ID
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel
        db: Database session
        
    Returns:
        Checkout session dict with URL, or None if creation failed
        
    Raises:
        ValueError: If user already has an active paid subscription
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
        
        # Check for existing active paid subscriptions
        existing_subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status == 'active'
        ).first()
        
        if existing_subscription:
            # Check if it's a real paid Stripe subscription
            if (existing_subscription.stripe_subscription_id and 
                not existing_subscription.stripe_subscription_id.startswith(('free_', 'unlimited_'))):
                
                try:
                    stripe_sub = stripe.Subscription.retrieve(existing_subscription.stripe_subscription_id)
                    if stripe_sub.status in ['active', 'trialing', 'past_due']:
                        logger.warning(f"User {user_id} already has active Stripe subscription")
                        raise ValueError(
                            "You already have an active subscription. "
                            "Please manage your subscription through the customer portal."
                        )
                except stripe.error.InvalidRequestError:
                    logger.info(f"Subscription {existing_subscription.stripe_subscription_id} not found in Stripe")
        
        # Double-check Stripe for any active paid subscriptions
        if _has_active_paid_subscription(customer_id):
            logger.warning(f"User {user_id} has active paid subscription in Stripe")
            raise ValueError(
                "You already have an active subscription. "
                "Please manage your subscription through the customer portal."
            )
        
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
                'metadata': {'user_id': str(user_id)},
            },
            allow_promotion_codes=True,
        )
        
        logger.info(f"Created checkout session for user {user_id}: {session.id}")
        return {
            'session_id': session.id,
            'url': session.url
        }
        
    except ValueError:
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
        
        logger.info(f"Created portal session for user {user_id}")
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
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    try:
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
        
        # Create free subscription
        now = datetime.now(timezone.utc)
        period_end = (now.replace(day=1) + timedelta(days=32)).replace(day=now.day)
        
        subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=f"free_{user_id}_{int(now.timestamp())}",
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
        
        # Initialize token balance
        from token_helpers import reset_tokens_for_subscription
        reset_tokens_for_subscription(user_id, 'free', now, period_end, db)
        
        logger.info(f"Created free subscription for user {user_id}")
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating free subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def create_unlimited_subscription(
    user_id: int, 
    preserved_tokens: int, 
    db: Session
) -> Optional[Subscription]:
    """
    Create an unlimited subscription (admin feature, no Stripe subscription).
    
    Args:
        user_id: User ID
        preserved_tokens: Token balance to preserve
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
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
                customer_id = f"unlimited_customer_{user_id}"
                user.stripe_customer_id = customer_id
                db.commit()
        
        now = datetime.now(timezone.utc)
        period_end = (now.replace(day=1) + timedelta(days=32)).replace(day=now.day)
        
        existing = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        
        if existing:
            # Update existing subscription
            existing.plan_type = 'unlimited'
            existing.status = 'active'
            existing.stripe_customer_id = customer_id
            existing.preserved_tokens_balance = preserved_tokens
            
            if not existing.stripe_subscription_id.startswith('unlimited_'):
                existing.stripe_subscription_id = f'unlimited_{user_id}_{int(now.timestamp())}'
            
            existing.current_period_start = now
            existing.current_period_end = period_end
            existing.cancel_at_period_end = False
            
            db.commit()
            db.refresh(existing)
            logger.info(f"Updated subscription to unlimited for user {user_id}")
            return existing
        
        # Create new unlimited subscription
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
        
        logger.info(f"Created unlimited subscription for user {user_id}")
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating unlimited subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def get_subscription_info(user_id: int, db: Session) -> Optional[Dict[str, Any]]:
    """Get subscription information for a user."""
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


def _get_plan_type_from_price(price_id: str) -> str:
    """Get plan type from Stripe price ID."""
    for plan_key, plan_config in get_plans().items():
        if plan_config.get('stripe_price_id') == price_id:
            return plan_key
    return 'free'


def update_subscription_from_stripe(
    stripe_subscription: stripe.Subscription, 
    db: Session, 
    user_id: Optional[int] = None
) -> Optional[Subscription]:
    """
    Update or create subscription record from Stripe subscription object.
    
    Args:
        stripe_subscription: Stripe subscription object
        db: Database session
        user_id: User ID (required if not in subscription metadata)
        
    Returns:
        Subscription model instance or None if update failed
    """
    try:
        # Determine user_id
        if not user_id and stripe_subscription.metadata:
            user_id = stripe_subscription.metadata.get('user_id')
            if user_id:
                user_id = int(user_id)
        
        if not user_id:
            # Fallback: look up by customer
            customer_id = stripe_subscription.customer
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user_id = user.id
        
        if not user_id:
            logger.error(f"Cannot determine user_id for subscription {stripe_subscription.id}")
            return None
        
        # Extract subscription details
        if not hasattr(stripe_subscription, 'items') or not stripe_subscription.items:
            logger.error(f"Subscription {stripe_subscription.id} has no items")
            return None
        
        items_data = stripe_subscription.items.data if hasattr(stripe_subscription.items, 'data') else []
        if not items_data:
            logger.error(f"Subscription {stripe_subscription.id} has no items data")
            return None
        
        price = items_data[0].price
        if not price or not hasattr(price, 'id'):
            logger.error(f"Subscription {stripe_subscription.id} has no price")
            return None
        
        plan_type = _get_plan_type_from_price(price.id)
        
        # Map Stripe status
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
        
        # Find or create subscription
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription.id
        ).first()
        
        if subscription and subscription.user_id != user_id:
            logger.warning(
                f"Subscription {stripe_subscription.id} belongs to user {subscription.user_id}, "
                f"updating to user {user_id}"
            )
            subscription.user_id = user_id
        
        if not subscription:
            subscription = db.query(Subscription).filter(
                Subscription.user_id == user_id
            ).first()
            
            if subscription:
                # Remove conflicting subscription if it exists
                conflicting = db.query(Subscription).filter(
                    Subscription.stripe_subscription_id == stripe_subscription.id
                ).first()
                
                if conflicting:
                    logger.info(f"Removing conflicting subscription {conflicting.id}")
                    db.delete(conflicting)
                    db.flush()
        
        # Update or create subscription
        if subscription:
            subscription.user_id = user_id
            subscription.stripe_subscription_id = stripe_subscription.id
            subscription.stripe_customer_id = stripe_subscription.customer
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
        
        logger.info(f"Updated subscription for user {user_id}: {plan_type} ({status})")
        return subscription
        
    except IntegrityError as e:
        db.rollback()
        logger.error(
            f"Database constraint violation for subscription {stripe_subscription.id}: {e}", 
            exc_info=True
        )
        return None
    except Exception as e:
        db.rollback()
        logger.error(
            f"Error updating subscription {stripe_subscription.id}: {e}", 
            exc_info=True
        )
        return None


def log_stripe_event(
    stripe_event_id: str, 
    event_type: str, 
    payload: Dict[str, Any], 
    db: Session
) -> StripeEvent:
    """Log a Stripe webhook event for idempotency."""
    event = db.query(StripeEvent).filter(
        StripeEvent.stripe_event_id == stripe_event_id
    ).first()
    
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


def mark_stripe_event_processed(
    stripe_event_id: str, 
    db: Session, 
    error_message: Optional[str] = None
):
    """Mark a Stripe event as processed."""
    event = db.query(StripeEvent).filter(
        StripeEvent.stripe_event_id == stripe_event_id
    ).first()
    
    if event:
        event.processed = True
        if error_message:
            event.error_message = error_message
        db.commit()