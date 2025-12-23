"""Stripe service - Direct Stripe API interactions"""
import stripe
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta

from app.models.user import User
from app.models.subscription import Subscription
from app.models.stripe_event import StripeEvent
from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize Stripe
STRIPE_API_VERSION = getattr(settings, 'STRIPE_API_VERSION', '2024-11-20.acacia')
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = STRIPE_API_VERSION
else:
    logger.warning("STRIPE_SECRET_KEY not set - Stripe functionality will be disabled")


# Token calculation: 1 token = 10MB
TOKEN_CALCULATION_MB_PER_TOKEN = 10
BYTES_PER_MB = 1024 * 1024


def detect_stripe_mode(api_key: str = None) -> str:
    """Detect Stripe mode (test or live) from API key"""
    if api_key is None:
        api_key = settings.STRIPE_SECRET_KEY
    
    if not api_key:
        return 'unknown'
    
    if api_key.startswith('sk_test_'):
        return 'test'
    elif api_key.startswith('sk_live_'):
        return 'live'
    else:
        return 'unknown'


def get_stripe_mode() -> str:
    """Get current Stripe mode (test or live)"""
    return detect_stripe_mode(settings.STRIPE_SECRET_KEY)


def load_plans(mode: str = None) -> Dict[str, Dict[str, Any]]:
    """Load plan configuration from JSON file"""
    if mode is None:
        mode = get_stripe_mode()
        logger.debug(f"Auto-detected Stripe mode: {mode}")
    
    if mode not in ['test', 'live']:
        logger.warning(f"Unknown Stripe mode '{mode}', defaulting to test")
        mode = 'test'
    
    # Read from app/core/assets/ directory
    config_file = Path(__file__).parent.parent / 'core' / 'assets' / f'stripe_plans_{mode}.json'
    
    logger.debug(f"Loading plans from: {config_file}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            plans = json.load(f)
            
            # Validate the loaded plans structure
            if not isinstance(plans, dict):
                logger.error(f"Plans file {config_file} does not contain a JSON object")
                return _get_fallback_plans()
            
            # Validate each plan has required fields
            valid_plans = {}
            for plan_key, plan_data in plans.items():
                if not isinstance(plan_data, dict):
                    logger.warning(f"Skipping invalid plan '{plan_key}': not a dictionary")
                    continue
                
                price_id = plan_data.get('stripe_price_id')
                if not price_id:
                    logger.warning(f"Plan '{plan_key}' has no stripe_price_id - this plan will not work for subscriptions")
                
                valid_plans[plan_key] = plan_data
            
            if len(valid_plans) == 0:
                logger.error(f"No valid plans found in {config_file}")
                return _get_fallback_plans()
            
            logger.info(f"Loaded {len(valid_plans)} plans from {config_file}")
            return valid_plans
    except FileNotFoundError:
        logger.error(f"Plan config file not found: {config_file}")
        logger.warning("Using fallback plans (free plan only)")
        return _get_fallback_plans()
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {config_file}: {e}")
        logger.warning("Using fallback plans (free plan only)")
        return _get_fallback_plans()


def _get_fallback_plans() -> Dict[str, Dict[str, Any]]:
    """Fallback plans if JSON config is missing"""
    return {
        'free': {
            'name': 'Free',
            'monthly_tokens': 10,
            'stripe_price_id': None,
            'stripe_product_id': None,
            'stripe_overage_price_id': None,
        }
    }


# Load plans on module import
_PLANS_CACHE = None

def get_plans() -> Dict[str, Dict[str, Any]]:
    """Get the appropriate PLANS dictionary based on current Stripe mode. Cached after first load"""
    global _PLANS_CACHE
    if _PLANS_CACHE is None:
        _PLANS_CACHE = load_plans()
    return _PLANS_CACHE


def reload_plans():
    """Force reload of plans from JSON (useful after running setup)"""
    global _PLANS_CACHE
    logger.info("Reloading plans from file (clearing cache)")
    _PLANS_CACHE = load_plans()
    logger.info(f"Plans reloaded: {len(_PLANS_CACHE)} plans")
    return _PLANS_CACHE


def calculate_tokens_from_bytes(file_size_bytes: int) -> int:
    """Calculate tokens required for a file upload. Formula: 1 token = 10MB"""
    if file_size_bytes <= 0:
        return 0
    
    size_mb = file_size_bytes / BYTES_PER_MB
    tokens = int(size_mb / TOKEN_CALCULATION_MB_PER_TOKEN)
    
    # Round up: if there's any remainder, add 1 token
    if size_mb % TOKEN_CALCULATION_MB_PER_TOKEN > 0:
        tokens += 1
    
    return max(1, tokens)  # Minimum 1 token for any upload


def get_plan_monthly_tokens(plan_type: str) -> int:
    """Get monthly token allocation for a plan. Returns -1 for unlimited plan, otherwise the monthly token count"""
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan['monthly_tokens']  # -1 for unlimited, otherwise token count
    return plans.get('free', {}).get('monthly_tokens', 10)  # Default to free


def get_plan_price_id(plan_type: str) -> Optional[str]:
    """Get Stripe price ID for a plan type"""
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan.get('stripe_price_id')
    logger.warning(f"Plan type '{plan_type}' not found in plans. Available plans: {list(plans.keys())}")
    return None


def get_plan_overage_price_id(plan_type: str) -> Optional[str]:
    """Get Stripe overage price ID for a plan type (metered usage)"""
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan.get('stripe_overage_price_id')
    logger.warning(f"Plan type '{plan_type}' not found in plans. Available plans: {list(plans.keys())}")
    return None


def get_price_info(price_id: str) -> Optional[Dict[str, Any]]:
    """Get price information from Stripe API
    
    Args:
        price_id: Stripe price ID
        
    Returns:
        Dictionary with price information or None if not found
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot get price info: STRIPE_SECRET_KEY not set")
        return None
    
    if not price_id:
        return None
    
    try:
        price = stripe.Price.retrieve(price_id)
        
        # Extract price information
        amount = price.unit_amount or 0
        currency = price.currency or 'usd'
        amount_dollars = amount / 100.0
        
        # Format price string
        if amount == 0:
            formatted = "Free"
        else:
            formatted = f"${amount_dollars:.2f}"
            if price.recurring:
                interval = price.recurring.interval
                if interval == 'month':
                    formatted += "/month"
                elif interval == 'year':
                    formatted += "/year"
        
        return {
            "amount": amount,
            "amount_dollars": amount_dollars,
            "currency": currency.upper(),
            "formatted": formatted
        }
    except stripe.error.InvalidRequestError as e:
        if 'No such price' in str(e):
            logger.warning(f"Price {price_id} not found in Stripe")
        else:
            logger.error(f"Stripe error retrieving price {price_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving price {price_id}: {e}", exc_info=True)
        return None


def create_stripe_customer(email: str, user_id: int, db: Session) -> Optional[str]:
    """Create a Stripe customer for a user"""
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot create Stripe customer: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
            
        if user.stripe_customer_id:
            existing_customer_id = user.stripe_customer_id
            try:
                stripe.Customer.retrieve(existing_customer_id)
                logger.info(f"User {user_id} already has valid Stripe customer: {existing_customer_id}")
                return existing_customer_id
            except stripe.error.InvalidRequestError as e:
                if 'No such customer' in str(e):
                    logger.warning(f"Customer {existing_customer_id} doesn't exist in Stripe, creating new one")
                    user.stripe_customer_id = None
                    db.commit()
                    db.expire(user)
                    user = db.query(User).filter(User.id == user_id).first()
        
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


def ensure_stripe_customer_exists(user_id: int, db: Session) -> Optional[str]:
    """Ensure user has a valid Stripe customer"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        return None
    
    customer_id = create_stripe_customer(user.email, user_id, db)
    return customer_id


def create_checkout_session(
    user_id: int, 
    price_id: str, 
    success_url: str, 
    cancel_url: str, 
    db: Session,
    cancel_existing: bool = False
) -> Optional[Dict[str, Any]]:
    """Create a Stripe checkout session for subscription"""
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot create checkout session: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has a valid Stripe customer
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            return None
        
        # Validate that the price_id exists in our configuration
        plans = get_plans()
        price_id_found = False
        plan_type = None
        
        for plan_key, plan_config in plans.items():
            if plan_config.get('stripe_price_id') == price_id:
                price_id_found = True
                plan_type = plan_key
                break
        
        if not price_id_found:
            logger.error(f"Price ID {price_id} not found in plans configuration")
            raise ValueError(f"Invalid price ID: {price_id} is not configured in plans")
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id}],
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
    """Get Stripe customer portal URL for managing subscription"""
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot create portal session: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"User {user_id} has no valid Stripe customer")
            return None
        
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
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


def create_free_subscription(user_id: int, db: Session, skip_token_reset: bool = False) -> Optional[Subscription]:
    """Create a free subscription for a user via Stripe"""
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot create free subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
        
        price_id = get_plan_price_id('free')
        if not price_id:
            logger.error("Free plan price ID not configured")
            return None
        
        # Create subscription in Stripe
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
        )
        
        # Create subscription record in database
        from app.services.token_service import reset_tokens_for_subscription
        
        db_subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=subscription.id,
            stripe_customer_id=customer_id,
            plan_type='free',
            status=subscription.status,
            current_period_start=datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc),
            current_period_end=datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc),
            cancel_at_period_end=False,
        )
        db.add(db_subscription)
        db.commit()
        db.refresh(db_subscription)
        
        # Reset tokens for new subscription (unless caller wants to handle it)
        if not skip_token_reset:
            reset_tokens_for_subscription(
                user_id,
                'free',
                db_subscription.current_period_start,
                db_subscription.current_period_end,
                db,
                is_renewal=False
            )
        
        logger.info(f"Created free subscription for user {user_id}: {subscription.id}")
        return db_subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating free subscription for user {user_id}: {e}")
        db.rollback()
        return None
    except Exception as e:
        logger.error(f"Error creating free subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def get_subscription_info(user_id: int, db: Session) -> Optional[Dict[str, Any]]:
    """Get subscription information for a user"""
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not subscription:
        return None
    
    plans = get_plans()
    plan_config = plans.get(subscription.plan_type, {})
    
    return {
        'plan_type': subscription.plan_type,
        'plan_name': plan_config.get('name', subscription.plan_type),
        'status': subscription.status,
        'current_period_start': subscription.current_period_start.isoformat() if subscription.current_period_start else None,
        'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        'cancel_at_period_end': subscription.cancel_at_period_end,
    }


def log_stripe_event(
    stripe_event_id: str, 
    event_type: str, 
    payload: Dict[str, Any], 
    db: Session
) -> StripeEvent:
    """Log a Stripe webhook event for idempotency"""
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
    """Mark a Stripe event as processed"""
    event = db.query(StripeEvent).filter(
        StripeEvent.stripe_event_id == stripe_event_id
    ).first()
    
    if event:
        event.processed = True
        if error_message:
            event.error_message = error_message
        db.commit()


def record_token_usage_to_stripe(
    user_id: int,
    tokens_used: int,
    db: Session
) -> bool:
    """Record token usage to Stripe for metered billing (overage tokens)"""
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot record token usage: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        from app.services.token_service import get_or_create_token_balance
        
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if not subscription:
            logger.warning(f"No subscription found for user {user_id}, skipping Stripe usage recording")
            return False
        
        # Unlimited and free plans don't have metered usage
        if subscription.plan_type in ('unlimited', 'free'):
            return True
        
        customer_id = subscription.stripe_customer_id
        if not customer_id:
            logger.warning(f"Subscription {subscription.stripe_subscription_id} has no customer ID")
            return False
        
        # Get token balance to calculate overage
        balance = get_or_create_token_balance(user_id, db)
        stored_monthly_tokens = balance.monthly_tokens if balance.monthly_tokens > 0 else get_plan_monthly_tokens(subscription.plan_type)
        
        # Calculate overage (tokens used beyond included amount)
        overage_tokens = max(0, balance.tokens_used_this_period - stored_monthly_tokens)
        
        if overage_tokens <= 0:
            # No overage to report
            return True
        
        # Report overage to Stripe using meter events
        # This is a simplified version - the full implementation would track incremental usage
        # For now, we'll report the total overage
        try:
            stripe.MeterEvent.create(
                event_name='hopper_tokens',
                identifier=customer_id,
                value=overage_tokens,
            )
            logger.info(f"Recorded {overage_tokens} overage tokens to Stripe for user {user_id}")
            return True
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error recording token usage for user {user_id}: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Error recording token usage to Stripe for user {user_id}: {e}", exc_info=True)
        return False


def cancel_subscription_with_invoice(stripe_subscription_id: str, invoice_now: bool = True) -> bool:
    """
    Cancel a Stripe subscription, optionally creating a final invoice for overage.
    
    Uses stripe.Subscription.cancel() which supports invoice_now and prorate parameters.
    When invoice_now=True:
    - Creates a final invoice for any pending metered usage (overage)
    - Does NOT prorate the subscription cost (prorate=False - user keeps tokens they paid for)
    - Then cancels the subscription
    
    Args:
        stripe_subscription_id: Stripe subscription ID to cancel
        invoice_now: If True, create final invoice before canceling (default: True)
        
    Returns:
        True if canceled successfully, False otherwise
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot cancel subscription: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        # Use stripe.Subscription.cancel() which supports invoice_now and prorate parameters
        # invoice_now=True: Generates a final invoice for any un-invoiced metered usage
        # prorate=False: Don't prorate subscription cost - user keeps tokens they paid for
        stripe.Subscription.cancel(
            stripe_subscription_id,
            invoice_now=invoice_now,
            prorate=False  # Don't prorate - user paid for full period, keep tokens
        )
        
        if invoice_now:
            logger.info(f"Canceled subscription {stripe_subscription_id} with final invoice (overage invoiced, tokens preserved)")
        else:
            logger.info(f"Canceled subscription {stripe_subscription_id} without final invoice")
        
        return True
        
    except stripe.error.InvalidRequestError as e:
        if 'already been canceled' in str(e).lower():
            logger.info(f"Subscription {stripe_subscription_id} was already canceled")
            return True
        logger.warning(f"Error canceling subscription {stripe_subscription_id}: {e}")
        return False
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error canceling subscription {stripe_subscription_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error canceling subscription {stripe_subscription_id}: {e}", exc_info=True)
        return False


def cancel_all_user_subscriptions(user_id: int, db: Session, verify_cancellation: bool = True, invoice_now: bool = True) -> bool:
    """
    Cancel ALL active subscriptions for a user.
    
    Best practice: Call this BEFORE creating a new subscription when you control creation.
    This ensures only one subscription exists at a time.
    
    Args:
        user_id: User ID
        db: Database session
        verify_cancellation: Whether to verify cancellation (legacy parameter, kept for compatibility)
        invoice_now: If True, create final invoice for overage before canceling (default: True)
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot cancel subscriptions: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return True
        
        customer_id = user.stripe_customer_id
        if not customer_id:
            db_subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
            for sub in db_subscriptions:
                db.delete(sub)
            if db_subscriptions:
                db.commit()
                logger.info(f"Deleted {len(db_subscriptions)} orphaned subscription(s)")
            return True
        
        # Cancel in Stripe first with invoice_now to finalize overage charges
        try:
            stripe_subscriptions = stripe.Subscription.list(customer=customer_id, status='all', limit=100)
            for stripe_sub in stripe_subscriptions.data:
                if stripe_sub.status not in ('canceled', 'incomplete_expired'):
                    cancel_subscription_with_invoice(stripe_sub.id, invoice_now=invoice_now)
        except stripe.error.StripeError as e:
            logger.warning(f"Error listing Stripe subscriptions: {e}")
        
        # Delete from database
        db_subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
        for sub in db_subscriptions:
            db.delete(sub)
        if db_subscriptions:
            db.commit()
            logger.info(f"Canceled and deleted {len(db_subscriptions)} subscription(s) for user {user_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error canceling all subscriptions for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return False


def delete_stripe_customer(customer_id: str, user_id: Optional[int] = None) -> bool:
    """Delete a Stripe customer (admin only)"""
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot delete customer: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        stripe.Customer.delete(customer_id)
        logger.info(f"Deleted Stripe customer {customer_id}" + (f" for user {user_id}" if user_id else ""))
        return True
    except stripe.error.InvalidRequestError as e:
        if 'No such customer' in str(e):
            logger.info(f"Customer {customer_id} already deleted in Stripe")
            return True
        logger.warning(f"Error deleting Stripe customer {customer_id}: {e}")
        return False
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error deleting customer {customer_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error deleting Stripe customer {customer_id}: {e}", exc_info=True)
        return False


def create_unlimited_subscription(user_id: int, preserved_tokens: int, db: Session) -> Optional[Subscription]:
    """
    Create an unlimited subscription for a user via Stripe (admin only).
    
    Args:
        user_id: User ID
        preserved_tokens: Token balance to preserve when creating subscription
        db: Database session
        
    Returns:
        Subscription object or None if creation failed
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot create unlimited subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        # Cancel all existing subscriptions first
        cancel_all_user_subscriptions(user_id, db, verify_cancellation=True)
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
        
        # Get unlimited plan price ID
        price_id = get_plan_price_id('unlimited')
        if not price_id:
            logger.error("Unlimited plan price ID not configured")
            return None
        
        # Create subscription in Stripe
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
        )
        
        # Create subscription record in database
        from app.services.token_service import reset_tokens_for_subscription
        
        db_subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=subscription.id,
            stripe_customer_id=customer_id,
            plan_type='unlimited',
            status=subscription.status,
            current_period_start=datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc),
            current_period_end=datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc),
            cancel_at_period_end=False,
            preserved_tokens_balance=preserved_tokens  # Store preserved tokens
        )
        db.add(db_subscription)
        db.commit()
        db.refresh(db_subscription)
        
        # Reset tokens for unlimited plan (sets to -1 for unlimited)
        reset_tokens_for_subscription(
            user_id,
            'unlimited',
            db_subscription.current_period_start,
            db_subscription.current_period_end,
            db,
            is_renewal=False
        )
        
        # If we have preserved tokens, set them (unlimited plan allows any balance)
        if preserved_tokens > 0:
            from app.services.token_service import get_or_create_token_balance
            token_balance = get_or_create_token_balance(user_id, db)
            token_balance.tokens_remaining = preserved_tokens
            token_balance.monthly_tokens = preserved_tokens
            db.commit()
        
        logger.info(f"Created unlimited subscription for user {user_id}: {subscription.id} (preserved {preserved_tokens} tokens)")
        return db_subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating unlimited subscription for user {user_id}: {e}")
        db.rollback()
        return None
    except Exception as e:
        logger.error(f"Error creating unlimited subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def update_subscription_from_stripe(
    stripe_subscription_id: str,
    db: Session
) -> Optional[Subscription]:
    """Update subscription from Stripe webhook data"""
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot update subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
        
        # Find subscription in database
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription_id
        ).first()
        
        if not subscription:
            logger.warning(f"Subscription {stripe_subscription_id} not found in database")
            return None
        
        # Update subscription fields
        subscription.status = stripe_sub.status
        subscription.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start, tz=timezone.utc)
        subscription.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc)
        subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error updating subscription {stripe_subscription_id}: {e}")
        db.rollback()
        return None
    except Exception as e:
        logger.error(f"Error updating subscription {stripe_subscription_id}: {e}", exc_info=True)
        db.rollback()
        return None

