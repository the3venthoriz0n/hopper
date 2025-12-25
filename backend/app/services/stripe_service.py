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
from app.models.token_transaction import TokenTransaction
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
                
                # Support both old format (stripe_price_id) and new format (stripe_price_id_monthly)
                price_id = plan_data.get('stripe_price_id')
                if not price_id:
                    # Try new format: stripe_price_id_monthly (default to monthly for subscriptions)
                    price_id = plan_data.get('stripe_price_id_monthly')
                    if price_id:
                        # Add stripe_price_id for backward compatibility with existing code
                        plan_data['stripe_price_id'] = price_id
                
                # Only warn if no price_id found AND it's not the free plan (free plan doesn't need a price_id)
                if not price_id and plan_key != 'free':
                    logger.warning(f"Plan '{plan_key}' has no stripe_price_id or stripe_price_id_monthly - this plan will not work for subscriptions")
                
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
        plan_config = None
        
        for plan_key, config in plans.items():
            if config.get('stripe_price_id') == price_id:
                price_id_found = True
                plan_config = config
                break
        
        if not price_id_found:
            logger.error(f"Price ID {price_id} not found in plans configuration")
            raise ValueError(f"Invalid price ID: {price_id} is not configured in plans")
        
        # Get monthly_tokens from plan config, use 1 for unlimited (-1) or if not found
        monthly_tokens = plan_config.get('monthly_tokens', 1)
        quantity = monthly_tokens if monthly_tokens > 0 else 1
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': quantity}],
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
    subscription_or_id,
    db: Session,
    user_id: Optional[int] = None
) -> Optional[Subscription]:
    """Update subscription from Stripe webhook data
    
    Args:
        subscription_or_id: Either a Stripe Subscription object or subscription ID string
        db: Database session
        user_id: Optional user ID (used when creating new subscription)
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.error("Cannot update subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        # Handle both Stripe Subscription object and subscription ID string
        if isinstance(subscription_or_id, str):
            stripe_subscription_id = subscription_or_id
            stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
        else:
            # It's a Stripe Subscription object
            stripe_sub = subscription_or_id
            stripe_subscription_id = stripe_sub.id
        
        # Find subscription in database
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription_id
        ).first()
        
        # Get plan type from Stripe subscription
        plan_type = None
        if hasattr(stripe_sub, 'items') and stripe_sub.items:
            items_data = stripe_sub.items.data if hasattr(stripe_sub.items, 'data') else []
            if items_data and len(items_data) > 0:
                first_item = items_data[0]
                if hasattr(first_item, 'price') and first_item.price:
                    price_id = first_item.price.id if hasattr(first_item.price, 'id') else None
                    plan_type = _get_plan_type_from_price(price_id) if price_id else None
        
        if not subscription:
            # Create new subscription if it doesn't exist
            if not user_id:
                logger.warning(f"Subscription {stripe_subscription_id} not found in database and no user_id provided")
                return None
            
            subscription = Subscription(
                user_id=user_id,
                stripe_subscription_id=stripe_subscription_id,
                plan_type=plan_type or 'free',
                status=stripe_sub.status,
                current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start, tz=timezone.utc),
                current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc),
                cancel_at_period_end=stripe_sub.cancel_at_period_end
            )
            db.add(subscription)
        else:
            # Update existing subscription fields
            subscription.status = stripe_sub.status
            subscription.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start, tz=timezone.utc)
            subscription.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc)
            subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
            if plan_type:
                subscription.plan_type = plan_type
        
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


def _get_plan_type_from_price(price_id: Optional[str]) -> Optional[str]:
    """Get plan type from Stripe price ID"""
    plans = get_plans()
    for plan_key, plan_data in plans.items():
        if plan_data.get('stripe_price_id') == price_id:
            return plan_key
    return None


def _get_user_id_from_session(session_data: Dict[str, Any], db: Session) -> Optional[int]:
    """Extract user_id from checkout session."""
    # Try metadata first
    if session_data.get("metadata") and session_data["metadata"].get("user_id"):
        return int(session_data["metadata"]["user_id"])
    
    # Fallback to customer lookup
    customer_id = session_data.get("customer")
    if customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user.id
    
    return None


def _get_user_id_from_subscription(subscription, db: Session) -> Optional[int]:
    """Extract user_id from Stripe subscription."""
    # Try metadata first
    if hasattr(subscription, 'metadata') and subscription.metadata and subscription.metadata.get("user_id"):
        return int(subscription.metadata["user_id"])
    
    # Fallback to customer lookup
    customer_id = subscription.customer if hasattr(subscription, 'customer') else None
    if customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user.id
    
    return None


def _cancel_existing_subscriptions(user_id: int, new_subscription_id: str, db: Session):
    """Cancel any existing Stripe subscriptions for a user."""
    existing_subs = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active',
        Subscription.stripe_subscription_id != new_subscription_id
    ).all()
    
    for sub in existing_subs:
        # Cancel all Stripe subscriptions with final invoice for overage
        if sub.stripe_subscription_id:
            try:
                cancel_subscription_with_invoice(sub.stripe_subscription_id, invoice_now=True)
                sub.status = 'canceled'
                db.commit()
                logger.info(f"Canceled old subscription {sub.stripe_subscription_id} (overage invoiced)")
            except Exception as e:
                logger.warning(
                    f"Failed to cancel subscription {sub.stripe_subscription_id}: {e}"
                )


def cancel_other_user_subscriptions(user_id: int, keep_subscription_id: str, db: Session):
    """Cancel all user subscriptions except the one specified"""
    existing_subs = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active',
        Subscription.stripe_subscription_id != keep_subscription_id
    ).all()
    
    for sub in existing_subs:
        if sub.stripe_subscription_id:
            try:
                cancel_subscription_with_invoice(sub.stripe_subscription_id, invoice_now=True)
                sub.status = 'canceled'
                db.commit()
                logger.info(f"Canceled other subscription {sub.stripe_subscription_id} (keeping {keep_subscription_id})")
            except Exception as e:
                logger.warning(f"Failed to cancel subscription {sub.stripe_subscription_id}: {e}")


def handle_checkout_completed(session_data: Dict[str, Any], db: Session):
    """Handle checkout.session.completed event.
    
    Fixes rare issue where Stripe creates subscription with 0 items.
    This can happen due to Stripe API glitches or timing issues.
    """
    if session_data["mode"] != "subscription":
        return
    
    subscription_id = session_data.get("subscription")
    if not subscription_id:
        logger.warning("Checkout session has no subscription ID")
        return
    
    # Get user_id
    user_id = _get_user_id_from_session(session_data, db)
    if not user_id:
        logger.error(f"Could not determine user_id for checkout session {session_data['id']}")
        return
    
    # Cancel any existing paid subscriptions (prevent duplicates)
    _cancel_existing_subscriptions(user_id, subscription_id, db)
    
    # Check if subscription has items using SubscriptionItem.list() (most reliable method)
    # Don't rely on expand as it may not work reliably
    try:
        # Use SubscriptionItem.list() as the primary method to check for items
        # This is more reliable than relying on expand
        sub_items = stripe.SubscriptionItem.list(
            subscription=subscription_id,
            limit=100
        )
        
        has_items = sub_items.data and len(sub_items.data) > 0
        items_count = len(sub_items.data) if sub_items.data else 0
        
        if has_items:
            logger.info(f"✅ Subscription {subscription_id} has {items_count} item(s) - no fix needed")
        else:
            # Subscription truly has no items - try to fix from checkout session
            logger.error(f"⚠️  Subscription {subscription_id} has 0 items, attempting to fix from checkout session {session_data['id']}")
            logger.error(f"⚠️  Subscription {subscription_id} has 0 items, attempting to fix from checkout session {session_data['id']}")
            
            # Get line items from checkout session
            try:
                line_items = stripe.checkout.Session.list_line_items(session_data['id'], limit=100)
                
                # Get existing price IDs from subscription to avoid duplicates
                # Re-check items in case they were added between our check and now
                existing_price_ids = set()
                try:
                    current_items = stripe.SubscriptionItem.list(subscription=subscription_id, limit=100)
                    if current_items.data:
                        for existing_item in current_items.data:
                            if hasattr(existing_item, 'price') and existing_item.price:
                                existing_price_id = existing_item.price.id if hasattr(existing_item.price, 'id') else None
                                if existing_price_id:
                                    existing_price_ids.add(existing_price_id)
                except Exception as e:
                    logger.warning(f"Could not re-check subscription items: {e}")
                
                items_added = 0
                items_skipped = 0
                for item in line_items.data:
                    price_id = item.price.id if (hasattr(item, 'price') and item.price and hasattr(item.price, 'id')) else None
                    quantity = item.quantity if hasattr(item, 'quantity') else 1
                    
                    if price_id:
                        # Check if this price already exists in the subscription
                        if price_id in existing_price_ids:
                            items_skipped += 1
                            logger.info(f"ℹ️  Item with price {price_id} already exists in subscription {subscription_id}, skipping")
                            continue
                        
                        try:
                            # Skip overage prices (they should be added later in subscription.created handler)
                            is_overage = any(
                                p.get('stripe_overage_price_id') == price_id 
                                for p in get_plans().values()
                            )
                            
                            if not is_overage:
                                stripe.SubscriptionItem.create(
                                    subscription=subscription_id,
                                    price=price_id,
                                    quantity=quantity
                                )
                                items_added += 1
                                # Add to existing set to avoid duplicates if we need to retry
                                existing_price_ids.add(price_id)
                                logger.info(f"✅ Added item {price_id} (quantity: {quantity}) to subscription {subscription_id}")
                        except stripe.error.StripeError as e:
                            error_str = str(e)
                            # Check if error is because item already exists (race condition)
                            if 'already using that Price' in error_str or 'already exists' in error_str:
                                items_skipped += 1
                                logger.info(f"ℹ️  Item with price {price_id} already exists in subscription {subscription_id} (race condition), skipping")
                                existing_price_ids.add(price_id)
                            else:
                                logger.error(f"❌ Failed to add item {price_id} to subscription {subscription_id}: {e}")
                
                if items_added > 0:
                    # Re-retrieve subscription with updated items
                    subscription = stripe.Subscription.retrieve(
                        subscription_id,
                        expand=['items.data.price']
                    )
                    logger.info(f"✅ Fixed subscription {subscription_id} - added {items_added} item(s), skipped {items_skipped} duplicate(s)")
                elif items_skipped > 0:
                    # Items were skipped because they already exist - subscription is actually fine
                    logger.info(f"✅ Subscription {subscription_id} already has all required items ({items_skipped} item(s) found) - no fix needed")
                else:
                    logger.error(f"❌ Could not fix subscription {subscription_id} - no valid items found in checkout session")
            except stripe.error.StripeError as e:
                logger.error(f"❌ Failed to retrieve line items from checkout session {session_data['id']}: {e}")
            
    except stripe.error.StripeError as e:
        logger.error(f"❌ Failed to retrieve subscription {subscription_id} in checkout handler: {e}")
    
    # Note: Subscription creation/update is handled by customer.subscription.created event
    # We don't sync tokens here because subscription may not exist in DB yet
    # Tokens will be synced by customer.subscription.created handler
    
    logger.info(f"Checkout completed for user {user_id}, subscription {subscription_id}")


def handle_subscription_created(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.created event.
    
    This fires when a NEW subscription is created. However, during upgrades,
    Stripe may fire both .created and .updated events. We need to ensure
    tokens are only added once.
    """
    from app.services.token_service import ensure_tokens_synced_for_subscription, get_or_create_token_balance, reset_tokens_for_subscription
    
    subscription_id = subscription_data.get("id")
    logger.info(f"Processing customer.subscription.created event for subscription {subscription_id}")
    
    # Retrieve full subscription with expanded items
    subscription = stripe.Subscription.retrieve(
        subscription_id, 
        expand=['items.data.price']
    )
    
    # Verify subscription has items using SubscriptionItem.list() (more reliable than expand)
    # Don't rely on expand as it may not work reliably
    try:
        sub_items = stripe.SubscriptionItem.list(
            subscription=subscription_id,
            limit=100
        )
        items_count = len(sub_items.data) if sub_items.data else 0
        
        if items_count == 0:
            logger.error(
                f"CRITICAL: Subscription {subscription_id} was created with NO ITEMS! "
                f"This indicates the checkout session did not properly transfer items to the subscription. "
                f"Subscription status: {subscription.status}, Customer: {subscription.customer}"
            )
            
            # Try to find the checkout session that created this subscription
            try:
                customer_id = subscription.customer
                sessions = stripe.checkout.Session.list(customer=customer_id, limit=10)
                for session in sessions.data:
                    if session.get('subscription') == subscription_id:
                        logger.error(f"Found checkout session {session.id} that created subscription {subscription_id}")
                        # Check what line items were in the session
                        line_items = stripe.checkout.Session.list_line_items(session.id, limit=100)
                        if line_items and len(line_items.data) > 0:
                            logger.error(
                                f"Checkout session {session.id} had {len(line_items.data)} line item(s) but subscription has 0 items! "
                                f"This is a Stripe API issue or configuration problem."
                            )
                            # Log the line items that should have been transferred
                            for item in line_items.data:
                                price_id = item.price.id if hasattr(item, 'price') and item.price else 'unknown'
                                logger.error(f"  Line item that should be in subscription: price_id={price_id}")
                        else:
                            logger.error(f"Checkout session {session.id} also has no line items - this is the root cause!")
                        break
            except Exception as e:
                logger.error(f"Error investigating checkout session for subscription {subscription_id}: {e}")
            
            # Don't process this subscription - it's invalid
            return
        else:
            logger.info(f"✅ Subscription {subscription_id} has {items_count} item(s) - proceeding with processing")
    except Exception as e:
        logger.error(f"Error checking subscription items for {subscription_id}: {e}")
        # Continue anyway - subscription might still be valid
    
    user_id = _get_user_id_from_subscription(subscription, db)
    if not user_id:
        logger.error(
            f"Could not determine user_id for subscription {subscription.id}"
        )
        return
    
    # Cancel OTHER subscriptions (not the current one) to prevent duplicates
    # Best practice: In webhook handlers, cancel other subscriptions since the current one already exists in Stripe
    cancel_other_user_subscriptions(user_id, subscription.id, db)
    
    # Check if subscription already exists in DB (might have been created by .updated event first)
    existing_sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription.id
    ).first()
    
    # Create or update subscription in database
    updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
    if not updated_sub:
        logger.error(
            f"Failed to create/update subscription {subscription.id} for user {user_id}"
        )
        return
    
    # Add metered overage item if plan requires it (for pay-as-you-go overage billing)
    # Best practice: Add at subscription creation to ensure complete structure from the start
    # This ensures meter events can properly aggregate to the subscription item
    overage_price_id = get_plan_overage_price_id(updated_sub.plan_type)
    
    if overage_price_id:
        # Verify subscription still exists in Stripe before trying to add metered item
        try:
            # Re-retrieve subscription to ensure it still exists and get latest status
            current_subscription = stripe.Subscription.retrieve(
                subscription.id,
                expand=['items.data.price']
            )
            
            # Only add metered item if subscription is active
            if current_subscription.status not in ('active', 'trialing'):
                logger.warning(
                    f"⚠️  Subscription {subscription.id} is not active (status: {current_subscription.status}), "
                    f"skipping metered item addition. Meter events will not be tracked until subscription is active."
                )
            else:
                # Check if metered item already exists
                items_data = current_subscription.items.data if (hasattr(current_subscription, 'items') and current_subscription.items and hasattr(current_subscription.items, 'data')) else []
                has_metered_item = False
                metered_item_id = None
                
                for item in items_data:
                    if hasattr(item, 'price') and item.price:
                        item_price_id = item.price.id if hasattr(item.price, 'id') else None
                        if item_price_id == overage_price_id:
                            has_metered_item = True
                            metered_item_id = item.id
                            logger.info(f"✅ Subscription {subscription.id} already has metered overage item {item.id}")
                            break
                
                if not has_metered_item:
                    # Verify meter is attached to the overage price before adding
                    try:
                        overage_price = stripe.Price.retrieve(overage_price_id)
                        has_meter = (
                            hasattr(overage_price, 'recurring') and
                            overage_price.recurring and
                            hasattr(overage_price.recurring, 'meter') and
                            overage_price.recurring.meter is not None
                        )
                        
                        if not has_meter:
                            logger.error(
                                f"❌ CRITICAL: Overage price {overage_price_id} for plan {updated_sub.plan_type} "
                                f"does not have meter attached. Meter events will NOT be tracked. "
                                f"Please run setup_stripe.py to fix this."
                            )
                            # Still try to add it - might work in legacy mode
                        
                        # Add metered item to subscription for overage tracking
                        metered_item = stripe.SubscriptionItem.create(
                            subscription=subscription.id,
                            price=overage_price_id
                        )
                        metered_item_id = metered_item.id
                        
                        logger.info(
                            f"✅ Added metered overage item {metered_item_id} to subscription {subscription.id} "
                            f"for plan {updated_sub.plan_type} "
                            f"(meter {'attached' if has_meter else 'NOT attached - will not track usage'})"
                        )
                        
                        # Update subscription record with metered item ID if the field exists
                        if hasattr(updated_sub, 'stripe_metered_item_id'):
                            updated_sub.stripe_metered_item_id = metered_item_id
                            db.commit()
                            db.refresh(updated_sub)
                        
                    except stripe.error.StripeError as e:
                        error_str = str(e)
                        error_code = getattr(e, 'code', None)
                        user_message = getattr(e, 'user_message', None)
                        
                        if 'No such subscription' in error_str:
                            logger.warning(f"⚠️  Subscription {subscription.id} no longer exists in Stripe, cannot add metered item")
                        elif 'already using that Price' in error_str:
                            # Item might have been added by another process - check again
                            logger.warning(f"⚠️  Metered item might already exist for subscription {subscription.id}, checking...")
                            try:
                                items_list = stripe.SubscriptionItem.list(subscription=subscription.id, limit=100)
                                for item in items_list.data:
                                    if hasattr(item, 'price') and item.price and item.price.id == overage_price_id:
                                        metered_item_id = item.id
                                        if hasattr(updated_sub, 'stripe_metered_item_id'):
                                            updated_sub.stripe_metered_item_id = metered_item_id
                                            db.commit()
                                        logger.info(f"✅ Found existing metered item {metered_item_id} for subscription {subscription.id}")
                                        break
                            except Exception as check_error:
                                logger.error(f"Error checking for existing metered item: {check_error}")
                        else:
                            logger.error(
                                f"❌ Failed to add metered item to subscription {subscription.id}: "
                                f"{error_str} (code: {error_code}, message: {user_message})"
                            )
                            logger.error(f"Full Stripe error: {repr(e)}")
                else:
                    # Metered item exists - update database record
                    if metered_item_id and hasattr(updated_sub, 'stripe_metered_item_id') and not updated_sub.stripe_metered_item_id:
                        updated_sub.stripe_metered_item_id = metered_item_id
                        db.commit()
                        logger.info(f"Updated subscription record with metered item ID {metered_item_id}")
                        
        except stripe.error.StripeError as e:
            error_str = str(e)
            error_code = getattr(e, 'code', None)
            if 'No such subscription' in error_str:
                logger.warning(f"⚠️  Subscription {subscription.id} no longer exists in Stripe, skipping metered item addition")
            else:
                logger.error(
                    f"❌ Failed to retrieve subscription {subscription.id} to add metered item: "
                    f"{error_str} (code: {error_code})"
                )
            # Don't fail the whole process - subscription can work without metered item (just no overage billing)
        except Exception as e:
            logger.error(
                f"❌ Unexpected error adding metered item to subscription {subscription.id}: {e}",
                exc_info=True
            )
    else:
        logger.debug(f"Plan {updated_sub.plan_type} does not have overage pricing configured")
    
    # Grant tokens for NEW subscriptions (didn't exist before)
    # If it already existed, it means .updated event already processed it, so don't add tokens again
    if not existing_sub:
        # Check if tokens were already reset for this period (e.g., by create_free_subscription with skip_token_reset=False)
        # This prevents duplicate token grants when webhook fires after manual subscription creation
        balance = get_or_create_token_balance(user_id, db)
        
        # Check if tokens were recently reset (within last 5 minutes) for the same period
        tokens_already_reset = False
        if hasattr(balance, 'last_reset_at') and balance.last_reset_at and hasattr(balance, 'period_start') and balance.period_start and hasattr(balance, 'period_end') and balance.period_end:
            time_since_reset = datetime.now(timezone.utc) - balance.last_reset_at
            period_matches = (
                abs((balance.period_start - updated_sub.current_period_start).total_seconds()) < 60 and
                abs((balance.period_end - updated_sub.current_period_end).total_seconds()) < 60
            )
            
            # If reset was recent (within 5 minutes) and period matches, tokens were already handled
            if time_since_reset < timedelta(minutes=5) and period_matches:
                tokens_already_reset = True
                logger.info(
                    f"Tokens were already reset for user {user_id} subscription {subscription.id} "
                    f"(reset {time_since_reset.total_seconds():.0f}s ago, period matches) - skipping webhook token grant"
                )
        
        # Also check if there's a recent transaction indicating tokens were preserved (e.g., from cancel_subscription)
        if not tokens_already_reset:
            # Query recent reset transactions and filter in Python (matches existing codebase pattern)
            recent_reset_transactions = db.query(TokenTransaction).filter(
                TokenTransaction.user_id == user_id,
                TokenTransaction.transaction_type == 'reset',
                TokenTransaction.created_at > datetime.now(timezone.utc) - timedelta(minutes=5)
            ).all()
            
            recent_preserve_transaction = None
            for transaction in recent_reset_transactions:
                metadata = transaction.transaction_metadata or {}
                if metadata.get('tokens_preserved') == True:
                    recent_preserve_transaction = transaction
                    break
            
            if recent_preserve_transaction:
                tokens_already_reset = True
                logger.info(
                    f"Tokens were preserved for user {user_id} subscription {subscription.id} "
                    f"(preserve transaction {recent_preserve_transaction.id} found) - skipping webhook token grant"
                )
        
        if not tokens_already_reset:
            logger.info(f"New subscription created for user {user_id}: {updated_sub.plan_type} - granting initial tokens")
            
            monthly_tokens = get_plan_monthly_tokens(updated_sub.plan_type)
            logger.info(f"Granting {monthly_tokens} tokens to user {user_id} for new {updated_sub.plan_type} subscription")
            
            # Explicitly grant tokens for new subscription (is_renewal=False adds tokens to current balance)
            token_granted = reset_tokens_for_subscription(
                user_id,
                updated_sub.plan_type,
                updated_sub.current_period_start,
                updated_sub.current_period_end,
                db,
                is_renewal=False  # New subscription - adds monthly tokens
            )
            
            if token_granted:
                logger.info(f"✅ Successfully granted {monthly_tokens} tokens to user {user_id} for {updated_sub.plan_type} subscription")
            else:
                logger.error(f"❌ Failed to grant tokens to user {user_id} for {updated_sub.plan_type} subscription")
                # Fallback: try ensure_tokens_synced_for_subscription as safety net
                ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
        else:
            logger.info(f"Skipping token grant for subscription {subscription.id} - tokens already handled")
    else:
        logger.info(f"Subscription {subscription.id} already existed in DB (likely processed by .updated event first) - skipping token grant to avoid double-adding")
    
    logger.info(f"Subscription created for user {user_id}: {updated_sub.plan_type}")


def handle_subscription_updated(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.updated event.
    
    This is the PRIMARY event for subscription state changes, including renewals.
    Stripe fires this event when:
    - Subscription renews (period advances)
    - Plan changes
    - Status changes
    - Other subscription property changes
    
    For renewals, the current_period_start and current_period_end advance.
    """
    from app.services.token_service import handle_subscription_renewal, ensure_tokens_synced_for_subscription, get_token_balance, get_or_create_token_balance
    
    try:
        subscription_id = subscription_data.get("id")
        if not subscription_id:
            logger.error("customer.subscription.updated event missing subscription ID")
            return
        
        logger.info(f"Processing customer.subscription.updated event for subscription {subscription_id}")
        
        # Retrieve full subscription with expanded items
        subscription = stripe.Subscription.retrieve(
            subscription_id, 
            expand=['items.data.price']
        )
        
        user_id = _get_user_id_from_subscription(subscription, db)
        if not user_id:
            logger.error(
                f"Could not determine user_id for subscription {subscription.id} in customer.subscription.updated"
            )
            return
        
        logger.info(f"Found user_id={user_id} for subscription {subscription.id}")
        
        # Get the old subscription data BEFORE update (critical for renewal detection)
        old_sub = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription.id
        ).first()
        
        # Also get user's current subscription (might be different if this is a new subscription during upgrade)
        user_current_sub = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()
        
        old_period_end = old_sub.current_period_end if old_sub else None
        old_period_start = old_sub.current_period_start if old_sub else None
        old_plan_type = old_sub.plan_type if old_sub else None
        
        # If this is a new subscription (old_sub is None) but user has an existing subscription,
        # check if it's a plan switch (upgrade/downgrade)
        is_new_subscription = old_sub is None
        is_plan_switch = False
        
        # Get plan type from Stripe subscription (before updating DB)
        price_id = None
        items_data = []
        if hasattr(subscription, 'items') and subscription.items:
            items_data = subscription.items.data if hasattr(subscription.items, 'data') else []
        if items_data and len(items_data) > 0:
            first_item = items_data[0]
            if hasattr(first_item, 'price') and first_item.price:
                price_id = first_item.price.id if hasattr(first_item.price, 'id') else None
        new_plan_type = _get_plan_type_from_price(price_id) if price_id else None
        
        if is_new_subscription and user_current_sub and user_current_sub.stripe_subscription_id != subscription.id:
            # New subscription created, but user had a different subscription - this is an upgrade/downgrade
            is_plan_switch = user_current_sub.plan_type != new_plan_type if new_plan_type else True
            old_plan_type = user_current_sub.plan_type
            logger.info(
                f"New subscription {subscription.id} created for user {user_id} who had subscription {user_current_sub.stripe_subscription_id} "
                f"(plan: {user_current_sub.plan_type} -> {new_plan_type}). This is likely an upgrade/downgrade."
            )
        
        if old_sub:
            logger.info(
                f"Subscription update for user {user_id} (subscription {subscription.id}): "
                f"old_period_end={old_period_end}, old_period_start={old_period_start}, "
                f"old_plan={old_sub.plan_type}, old_status={old_sub.status}"
            )
        else:
            logger.info(
                f"Subscription update for user {user_id} (subscription {subscription.id}): "
                f"No existing subscription found in DB (new subscription or first webhook)"
            )
        
        # Update subscription in database (this updates period_end if it changed)
        updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
        if not updated_sub:
            logger.error(
                f"Failed to update subscription {subscription.id} for user {user_id}"
            )
            return
        
        logger.info(
            f"Subscription updated in DB for user {user_id}: "
            f"new_period_start={updated_sub.current_period_start}, "
            f"new_period_end={updated_sub.current_period_end}, "
            f"plan={updated_sub.plan_type}, status={updated_sub.status}"
        )
        
        # Handle renewal if detected (single source of truth for renewal logic)
        renewal_handled = handle_subscription_renewal(user_id, updated_sub, old_period_end, db)
        
        if renewal_handled:
            logger.info(f"✅ Renewal was handled for user {user_id}, subscription {subscription.id}")
        else:
            # Not a renewal - check what type of change this is
            if is_new_subscription and not is_plan_switch:
                # Truly new subscription (first time) - .created event should handle tokens
                # But if .updated fires first, handle it here
                logger.info(f"ℹ️  New subscription for user {user_id} (subscription {subscription.id}) - syncing tokens")
                ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
            elif is_plan_switch or (old_sub and old_sub.plan_type != updated_sub.plan_type):
                # Plan switch detected (plan changed) - preserve tokens, only update period
                # This handles upgrades/downgrades where tokens should be preserved
                token_balance = get_token_balance(user_id, db)
                current_tokens = token_balance.get('tokens_remaining', 0) if token_balance else 0
                logger.info(
                    f"🔄 Plan switch detected for user {user_id}: {old_plan_type} -> {updated_sub.plan_type}. "
                    f"Preserving tokens (current: {current_tokens}), updating period only."
                )
                # Just update the period, preserve tokens
                balance = get_or_create_token_balance(user_id, db)
                balance.period_start = updated_sub.current_period_start
                balance.period_end = updated_sub.current_period_end
                balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"✅ Plan switch completed - tokens preserved: {balance.tokens_remaining}")
            elif old_period_end and updated_sub.current_period_end == old_period_end:
                # Period didn't change and plan didn't change - status change or other update
                logger.info(f"ℹ️  Status/other change for user {user_id}, subscription {subscription.id} - syncing tokens")
                ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
            else:
                # Period changed but wasn't detected as renewal and plan didn't change
                period_diff = (updated_sub.current_period_end - old_period_end).total_seconds() / 86400 if old_period_end else 0
                
                # If period advanced significantly (more than a day), it's likely a renewal that wasn't caught
                if period_diff > 1:
                    logger.warning(
                        f"⚠️  Period changed for user {user_id} (diff: {period_diff:.1f} days) but renewal not detected. "
                        f"Attempting to handle as renewal anyway (period advanced significantly)."
                    )
                    if period_diff >= 1:
                        logger.info(f"🔄 Treating period change as renewal (safety net) for user {user_id}")
                        handle_subscription_renewal(user_id, updated_sub, old_period_end, db)
                else:
                    logger.info(
                        f"ℹ️  Period changed slightly for user {user_id} (diff: {period_diff:.1f} days) - likely status change, not renewal"
                    )
        
        logger.info(f"✅ customer.subscription.updated processing completed for user {user_id}, subscription {subscription.id}")
        
    except Exception as e:
        logger.error(
            f"❌ ERROR in handle_subscription_updated for subscription {subscription_data.get('id', 'unknown')}: {e}",
            exc_info=True
        )
        # Don't re-raise - let webhook handler mark as processed with error
        # This prevents infinite retries but logs the error for debugging


def handle_subscription_deleted(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.deleted event."""
    subscription = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_data["id"]
    ).first()
    
    if subscription:
        subscription.status = "canceled"
        db.commit()
        logger.info(f"Marked subscription {subscription_data['id']} as canceled")


def handle_invoice_payment_succeeded(invoice_data: Dict[str, Any], db: Session):
    """Handle invoice.payment_succeeded event.
    
    This event fires when an invoice payment succeeds. It can be for:
    - New subscription (billing_reason: 'subscription_create')
    - Renewal (billing_reason: 'subscription_cycle')
    - Plan change (billing_reason: 'subscription_update')
    - Manual invoice (billing_reason: 'manual')
    
    IMPORTANT: Token renewal is handled by customer.subscription.updated, not here.
    This handler only ensures the subscription state is updated. If the subscription
    period has advanced, customer.subscription.updated will have already fired and
    handled the renewal. This is a safety net to ensure subscription state is current.
    
    For metered billing: This is where we reset the token usage counter for the new
    billing cycle, so overage tracking starts fresh.
    """
    from app.services.token_service import ensure_tokens_synced_for_subscription, get_or_create_token_balance
    
    subscription_id = invoice_data.get("subscription")
    if not subscription_id:
        # Not a subscription invoice, skip
        return
    
    # Update subscription state from Stripe (ensures we have latest period info)
    subscription = stripe.Subscription.retrieve(
        subscription_id,
        expand=['items.data.price']
    )
    user_id = _get_user_id_from_subscription(subscription, db)
    
    if not user_id:
        logger.error(f"Could not determine user_id for subscription {subscription_id} in invoice.payment_succeeded")
        return
    
    # Update subscription in database (this may trigger customer.subscription.updated if period changed)
    updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
    if not updated_sub:
        logger.error(f"Failed to update subscription {subscription_id} for user {user_id}")
        return
    
    # Reset token usage counter for new billing cycle (for metered billing)
    # This ensures overage tracking starts fresh each billing period
    billing_reason = invoice_data.get("billing_reason", "unknown")
    if billing_reason == 'subscription_cycle':
        # This is a renewal - reset tokens_used_this_period to 0 for new billing cycle
        # The token balance itself is reset by customer.subscription.updated handler
        # We just need to reset the usage counter for overage tracking
        balance = get_or_create_token_balance(user_id, db)
        if hasattr(balance, 'tokens_used_this_period') and balance.tokens_used_this_period > 0:
            logger.info(
                f"Resetting token usage counter for user {user_id} on billing cycle renewal "
                f"(previous period usage: {balance.tokens_used_this_period})"
            )
            balance.tokens_used_this_period = 0
            balance.updated_at = datetime.now(timezone.utc)
            db.commit()
    
    # Note: We don't handle token renewal here because:
    # 1. customer.subscription.updated is the canonical event for subscription state changes
    # 2. It fires when the period advances, which is the definitive signal for renewal
    # 3. invoice.payment_succeeded can fire before the period advances in some edge cases
    # 4. This separation ensures single responsibility and prevents duplicate processing
    
    # Only sync tokens as a safety net (handles edge cases where subscription.updated didn't fire)
    # This is idempotent and won't double-process renewals
    ensure_tokens_synced_for_subscription(user_id, subscription_id, db)
    
    logger.info(f"Invoice payment succeeded for subscription {subscription_id} (billing_reason: {billing_reason}), subscription state updated for user {user_id}")


def handle_invoice_payment_failed(invoice_data: Dict[str, Any], db: Session):
    """Handle invoice.payment_failed event."""
    subscription_id = invoice_data.get("subscription")
    if not subscription_id:
        return
    
    # Update subscription status with expanded items
    subscription = stripe.Subscription.retrieve(
        subscription_id,
        expand=['items.data.price']
    )
    user_id = _get_user_id_from_subscription(subscription, db)
    
    if user_id:
        update_subscription_from_stripe(subscription, db, user_id=user_id)
        logger.warning(f"Payment failed for subscription {subscription_id}")

