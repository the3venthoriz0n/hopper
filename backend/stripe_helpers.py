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
    """Create a Stripe customer for a user."""
    if not STRIPE_SECRET_KEY:
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
    """Ensure user has a valid Stripe customer."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        return None
    
    customer_id = create_stripe_customer(user.email, user_id, db)
    return customer_id


def cancel_all_user_subscriptions(user_id: int, db: Session, verify_cancellation: bool = True) -> bool:
    """Cancel all active subscriptions for a user."""
    if not STRIPE_SECRET_KEY:
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
        
        # Cancel in Stripe first
        try:
            stripe_subscriptions = stripe.Subscription.list(customer=customer_id, status='all', limit=100)
            for stripe_sub in stripe_subscriptions.data:
                if stripe_sub.status not in ('canceled', 'incomplete_expired'):
                    try:
                        stripe.Subscription.delete(stripe_sub.id)
                        logger.info(f"Canceled Stripe subscription {stripe_sub.id}")
                    except stripe.error.InvalidRequestError as e:
                        if 'already been canceled' not in str(e).lower():
                            logger.warning(f"Error canceling {stripe_sub.id}: {e}")
        except stripe.error.StripeError as e:
            logger.warning(f"Error listing Stripe subscriptions: {e}")
        
        # Delete from database
        db_subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
        for sub in db_subscriptions:
            db.delete(sub)
        
        if db_subscriptions:
            db.commit()
            logger.info(f"Deleted {len(db_subscriptions)} subscription(s) from database")
        
        return True
        
    except Exception as e:
        logger.error(f"Error canceling subscriptions for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return False

def delete_stripe_customer(customer_id: str, user_id: Optional[int] = None) -> bool:
    """
    Delete a Stripe customer. This automatically cancels all subscriptions.
    
    Args:
        customer_id: Stripe customer ID to delete
        user_id: Optional user ID for logging purposes
        
    Returns:
        True if customer was deleted successfully or didn't exist, False on error
    """
    if not STRIPE_SECRET_KEY:
        logger.warning("Cannot delete Stripe customer: STRIPE_SECRET_KEY not set")
        return False
    
    if not customer_id:
        return True  # No customer ID to delete
    
    # Verify it's a valid Stripe customer ID (starts with 'cus_')
    if not customer_id.startswith('cus_'):
        logger.warning(
            f"Customer ID {customer_id} for user {user_id or 'unknown'} "
            f"doesn't appear to be a Stripe customer (doesn't start with 'cus_'). "
            f"Skipping Stripe customer deletion."
        )
        return True  # Not a valid customer ID, but not an error
    
    try:
        # Delete the customer in Stripe
        # This automatically cancels all subscriptions for this customer
        stripe.Customer.delete(customer_id)
        user_info = f" for user {user_id}" if user_id else ""
        logger.info(
            f"✅ Deleted Stripe customer {customer_id}{user_info} "
            f"(subscriptions automatically canceled by Stripe)"
        )
        return True
    except stripe.error.InvalidRequestError as e:
        # Customer might already be deleted or not exist in Stripe
        error_str = str(e)
        if 'No such customer' in error_str:
            user_info = f" for user {user_id}" if user_id else ""
            logger.info(
                f"ℹ️  Customer {customer_id}{user_info} not found in Stripe "
                f"(may already be deleted). Continuing."
            )
            return True  # Customer doesn't exist, which is fine
        else:
            user_info = f" for user {user_id}" if user_id else ""
            logger.warning(
                f"⚠️  Failed to delete Stripe customer {customer_id}{user_info}: {e}. "
                f"Continuing."
            )
            return False  # Some other error
    except stripe.error.StripeError as e:
        user_info = f" for user {user_id}" if user_id else ""
        logger.warning(
            f"⚠️  Stripe error deleting customer {customer_id}{user_info}: {e}. "
            f"Continuing."
        )
        return False
    except Exception as e:
        user_info = f" for user {user_id}" if user_id else ""
        logger.error(
            f"❌ Unexpected error deleting Stripe customer {customer_id}{user_info}: {e}",
            exc_info=True
        )
        return False
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
    db: Session,
    cancel_existing: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Create a Stripe checkout session for subscription.
    Can cancel existing subscriptions if cancel_existing is True.
    
    Args:
        user_id: User ID
        price_id: Stripe price ID
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel
        db: Database session
        cancel_existing: If True, cancel existing subscriptions before creating checkout
        
    Returns:
        Checkout session dict with URL and canceled_subscription info, or None if creation failed
        
    Raises:
        ValueError: If user already has an active paid subscription and cancel_existing is False
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create checkout session: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has a valid Stripe customer that exists in Stripe
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            return None
        
        # Check for existing active paid subscriptions
        existing_subscription = db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status == 'active'
        ).first()
        
        canceled_subscription_info = None
        
        if existing_subscription:
            # Check if it's a real Stripe subscription (all subscriptions are now Stripe subscriptions)
            if existing_subscription.stripe_subscription_id:
                try:
                    stripe_sub = stripe.Subscription.retrieve(existing_subscription.stripe_subscription_id)
                    if stripe_sub.status in ['active', 'trialing', 'past_due']:
                        if cancel_existing:
                            # Cancel the existing subscription
                            logger.info(f"User {user_id} has active subscription {existing_subscription.stripe_subscription_id}, canceling it for upgrade")
                            stripe.Subscription.delete(existing_subscription.stripe_subscription_id)
                            existing_subscription.status = 'canceled'
                            db.commit()
                            canceled_subscription_info = {
                                'plan_type': existing_subscription.plan_type,
                                'subscription_id': existing_subscription.stripe_subscription_id
                            }
                            logger.info(f"Canceled existing subscription {existing_subscription.stripe_subscription_id} for user {user_id}")
                        else:
                            logger.warning(f"User {user_id} already has active Stripe subscription")
                            raise ValueError(
                                "You already have an active subscription. "
                                "Please manage your subscription through the customer portal."
                            )
                except stripe.error.InvalidRequestError:
                    logger.info(f"Subscription {existing_subscription.stripe_subscription_id} not found in Stripe")
        
        # Double-check Stripe for any active paid subscriptions
        if _has_active_paid_subscription(customer_id):
            if cancel_existing:
                # Try to find and cancel any remaining active subscriptions
                try:
                    stripe_subs = stripe.Subscription.list(customer=customer_id, status='active', limit=10)
                    for sub in stripe_subs.data:
                        try:
                            stripe.Subscription.delete(sub.id)
                            logger.info(f"Canceled active Stripe subscription {sub.id} for user {user_id}")
                        except Exception as e:
                            logger.warning(f"Failed to cancel subscription {sub.id}: {e}")
                except Exception as e:
                    logger.warning(f"Error checking/canceling Stripe subscriptions: {e}")
            else:
                logger.warning(f"User {user_id} has active paid subscription in Stripe")
                raise ValueError(
                    "You already have an active subscription. "
                    "Please manage your subscription through the customer portal."
                )
        
        # Validate that the price_id exists in our configuration
        from stripe_config import get_plans
        plans = get_plans()
        price_id_found = False
        plan_type = None
        
        # Check if price_id is in our plans configuration
        for plan_key, plan_config in plans.items():
            if plan_config.get('stripe_price_id') == price_id:
                price_id_found = True
                plan_type = plan_key
                logger.info(f"Validated price_id {price_id} belongs to plan '{plan_type}'")
                break
        
        if not price_id_found:
            logger.error(
                f"Price ID {price_id} not found in plans configuration. "
                f"Available price IDs: {[p.get('stripe_price_id') for p in plans.values() if p.get('stripe_price_id')]}"
            )
            raise ValueError(f"Invalid price ID: {price_id} is not configured in plans")
        
        # Build line items - ONLY include the base price in checkout session
        # Metered overage prices should be added AFTER subscription creation (in webhook handler)
        # This is the correct pattern for metered billing that tracks usage and bills at end of period
        line_items = [{'price': price_id, 'quantity': 1}]
        
        logger.info(f"Creating checkout session with base price for plan {plan_type} (metered overage will be added after subscription creation)")
        logger.debug(f"Line items: {line_items}")
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=line_items,
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={'user_id': str(user_id)},
            subscription_data={
                'metadata': {'user_id': str(user_id)},
            },
            allow_promotion_codes=True,
        )
        
        # Verify the session was created with items
        if hasattr(session, 'line_items'):
            # Retrieve full session to verify items
            full_session = stripe.checkout.Session.retrieve(session.id, expand=['line_items.data.price'])
            if hasattr(full_session, 'line_items') and full_session.line_items:
                items_count = len(full_session.line_items.data) if hasattr(full_session.line_items, 'data') else 0
                logger.info(f"Created checkout session {session.id} for user {user_id} with {items_count} line item(s)")
                if items_count == 0:
                    logger.error(f"CRITICAL: Checkout session {session.id} was created with 0 line items! This will cause subscription creation to fail.")
                    raise ValueError(f"Checkout session created without line items - this is a critical error")
            else:
                logger.warning(f"Checkout session {session.id} has no line_items attribute")
        else:
            logger.warning(f"Checkout session {session.id} has no line_items attribute")
        
        logger.info(f"Created checkout session for user {user_id}: {session.id}")
        result = {
            'session_id': session.id,
            'url': session.url
        }
        if canceled_subscription_info:
            result['canceled_subscription'] = canceled_subscription_info
        return result
        
    except ValueError:
        raise
    except stripe.error.InvalidRequestError as e:
        # Handle case where customer doesn't exist (shouldn't happen after our check, but safety net)
        if 'No such customer' in str(e):
            old_customer_id = customer_id  # Store the old ID for logging
            logger.warning(f"Customer {old_customer_id} not found when creating checkout session for user {user_id}, attempting to recreate")
            
            # Expire and refresh user object to ensure we get latest state from DB
            db.expire(user)
            db.refresh(user)
            
            # Force clear the customer_id in the database if it still exists
            if user.stripe_customer_id:
                logger.info(f"Clearing stale customer_id {user.stripe_customer_id} from database for user {user_id}")
                user.stripe_customer_id = None
                db.commit()
                db.refresh(user)
            
            # Try to recreate customer and retry
            new_customer_id = ensure_stripe_customer_exists(user_id, db)
            if new_customer_id and new_customer_id != old_customer_id:
                logger.info(f"Recreated customer for user {user_id}: {old_customer_id} -> {new_customer_id}")
                try:
                    session = stripe.checkout.Session.create(
                        customer=new_customer_id,  # Use the new customer ID
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
                    logger.info(f"Created checkout session for user {user_id} after recreating customer: {session.id}")
                    return {
                        'session_id': session.id,
                        'url': session.url
                    }
                except stripe.error.InvalidRequestError as retry_e:
                    if 'No such customer' in str(retry_e):
                        logger.error(f"Still getting 'No such customer' error after recreating customer for user {user_id}. Customer ID used: {new_customer_id}. Error: {retry_e}")
                    else:
                        logger.error(f"Stripe error creating checkout session after recreating customer for user {user_id}: {retry_e}")
                except Exception as retry_e:
                    logger.error(f"Failed to create checkout session after recreating customer for user {user_id}: {retry_e}")
            else:
                if new_customer_id == old_customer_id:
                    logger.error(f"ensure_stripe_customer_exists returned the same invalid customer_id {old_customer_id} for user {user_id}")
                else:
                    logger.error(f"Failed to recreate customer for user {user_id}")
            return None
        else:
            logger.error(f"Stripe error creating checkout session for user {user_id}: {e}")
            return None
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
        # Ensure user has a valid Stripe customer that exists in Stripe
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



def create_free_subscription(user_id: int, db: Session) -> Optional[Subscription]:
    """Create a free subscription for a new user via Stripe."""
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create free subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        cancel_all_user_subscriptions(user_id, db, verify_cancellation=True)
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
        
        from stripe_config import get_plan_price_id
        price_id = get_plan_price_id('free')
        if not price_id:
            logger.error("Free plan price ID not configured")
            return None
        
        logger.info(f"Creating free subscription for user {user_id} with price {price_id}")
        
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
            expand=['items.data.price']
        )
        
        subscription = update_subscription_from_stripe(
            stripe_subscription, 
            db, 
            user_id=user_id,
            skip_retrieve=True
        )
        
        if subscription:
            from token_helpers import reset_tokens_for_subscription
            from stripe_config import get_plan_monthly_tokens
            token_initialized = reset_tokens_for_subscription(
                user_id,
                subscription.plan_type,
                subscription.current_period_start,
                subscription.current_period_end,
                db,
                is_renewal=False
            )
            if token_initialized:
                monthly_tokens = get_plan_monthly_tokens('free')
                logger.info(f"Created free subscription for user {user_id}: {stripe_subscription.id} with {monthly_tokens} tokens")
            else:
                logger.warning(f"Created subscription but token initialization failed")
        else:
            logger.error(f"Failed to create subscription record for user {user_id}")
        
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating free subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def create_unlimited_subscription(user_id: int, preserved_tokens: int, db: Session) -> Optional[Subscription]:
    """Create an unlimited subscription via Stripe (admin feature)."""
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create unlimited subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer")
            return None
        
        from stripe_config import get_plan_price_id
        price_id = get_plan_price_id('unlimited')
        if not price_id:
            logger.error("Unlimited plan price ID not configured")
            return None
        
        cancel_all_user_subscriptions(user_id, db, verify_cancellation=True)
        
        logger.info(f"Creating unlimited subscription for user {user_id}")
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id), 'preserved_tokens': str(preserved_tokens)},
            expand=['items.data.price']
        )
        
        subscription = update_subscription_from_stripe(
            stripe_subscription, 
            db, 
            user_id=user_id,
            skip_retrieve=True
        )
        
        if subscription:
            subscription.preserved_tokens_balance = preserved_tokens
            db.commit()
            db.refresh(subscription)
            
            from token_helpers import get_or_create_token_balance
            token_balance = get_or_create_token_balance(user_id, db)
            token_balance.period_start = subscription.current_period_start
            token_balance.period_end = subscription.current_period_end
            token_balance.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Created unlimited subscription for user {user_id}: {stripe_subscription.id}")
        
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating unlimited subscription: {e}", exc_info=True)
        db.rollback()
        return None


def create_stripe_subscription(user_id: int, price_id: str, db: Session) -> Optional[Subscription]:
    """Create a Stripe subscription directly (admin use)."""
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create Stripe subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            return None
        
        # Cancel any existing subscriptions before creating new one
        cancel_all_user_subscriptions(user_id, db, verify_cancellation=True)
        
        logger.info(f"Creating subscription for user {user_id} with price {price_id}")
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
            expand=['items.data.price']
        )
        
        subscription = update_subscription_from_stripe(
            stripe_subscription, 
            db, 
            user_id=user_id,
            skip_retrieve=True
        )
        
        logger.info(f"Created subscription for user {user_id}: {stripe_subscription.id}")
        return subscription
        
    except Exception as e:
        logger.error(f"Error creating subscription: {e}", exc_info=True)
        return None


def update_subscription_from_stripe(
    stripe_subscription: stripe.Subscription, 
    db: Session, 
    user_id: Optional[int] = None,
    skip_retrieve: bool = False
) -> Optional[Subscription]:
    """Update or create subscription record from Stripe subscription object."""
    try:
        logger.info(f"update_subscription_from_stripe: {stripe_subscription.id}, user_id={user_id}, skip_retrieve={skip_retrieve}")
        
        # Determine user_id
        if not user_id and stripe_subscription.metadata:
            user_id = stripe_subscription.metadata.get('user_id')
            if user_id:
                user_id = int(user_id)
        
        if not user_id:
            customer_id = stripe_subscription.customer
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user_id = user.id
        
        if not user_id:
            logger.error(f"Cannot determine user_id for subscription {stripe_subscription.id}")
            return None
        
        # Only retrieve fresh if not skipped
        if not skip_retrieve:
            logger.debug(f"Retrieving subscription {stripe_subscription.id} fresh from Stripe")
            try:
                stripe_subscription = stripe.Subscription.retrieve(
                    stripe_subscription.id,
                    expand=['items.data.price']
                )
            except stripe.error.StripeError as e:
                logger.error(f"Failed to retrieve subscription: {e}")
                return None
        else:
            logger.info(f"Using provided subscription data for {stripe_subscription.id}")
        
        # Extract price_id - check both legacy and modern formats
        price_id = None
        
        # Legacy format: subscription.plan.id
        if hasattr(stripe_subscription, 'plan') and stripe_subscription.plan:
            plan_id = (stripe_subscription.plan.get('id') if isinstance(stripe_subscription.plan, dict) 
                      else getattr(stripe_subscription.plan, 'id', None))
            if plan_id:
                price_id = plan_id
                logger.info(f"Found price from legacy plan: {price_id}")
        
        # Modern format: subscription.items.data[].price.id
        if not price_id and hasattr(stripe_subscription, 'items') and stripe_subscription.items:
            items_data = (stripe_subscription.items.data if hasattr(stripe_subscription.items, 'data') else [])
            
            if items_data:
                for item in items_data:
                    if hasattr(item, 'price') and item.price:
                        item_price_id = (item.price.get('id') if isinstance(item.price, dict) 
                                        else getattr(item.price, 'id', None))
                        
                        if item_price_id:
                            # Skip overage prices
                            from stripe_config import get_plans
                            is_overage = any(
                                p.get('stripe_overage_price_id') == item_price_id 
                                for p in get_plans().values()
                            )
                            
                            if not is_overage:
                                price_id = item_price_id
                                logger.info(f"Found price from items: {price_id}")
                                break
        
        if not price_id:
            logger.error(f"Subscription {stripe_subscription.id} has no price data")
            return None
        
        plan_type = _get_plan_type_from_price(price_id)
        logger.info(f"Determined plan_type={plan_type}")
        
        # Extract metered item ID
        metered_item_id = None
        from stripe_config import get_plan_overage_price_id
        overage_price_id = get_plan_overage_price_id(plan_type)
        
        if overage_price_id and hasattr(stripe_subscription, 'items') and stripe_subscription.items:
            items_data = (stripe_subscription.items.data if hasattr(stripe_subscription.items, 'data') else [])
            for item in items_data:
                if hasattr(item, 'price') and item.price:
                    item_price_id = (item.price.get('id') if isinstance(item.price, dict) 
                                    else getattr(item.price, 'id', None))
                    if item_price_id == overage_price_id:
                        metered_item_id = item.id
                        break
        
        # Map status
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
        
        if subscription:
            logger.info(f"Updating existing subscription {subscription.id}")
            subscription.user_id = user_id
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
            if metered_item_id:
                subscription.stripe_metered_item_id = metered_item_id
            subscription.updated_at = datetime.now(timezone.utc)
        else:
            # Check if user has existing subscription
            existing_user_sub = db.query(Subscription).filter(
                Subscription.user_id == user_id
            ).first()
            
            if existing_user_sub:
                logger.info(f"Updating user {user_id}'s existing subscription")
                subscription = existing_user_sub
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
                if metered_item_id:
                    subscription.stripe_metered_item_id = metered_item_id
                subscription.updated_at = datetime.now(timezone.utc)
            else:
                logger.info(f"Creating new subscription for user {user_id}")
                
                # Delete any other subscriptions for this user to prevent duplicates
                other_subscriptions = db.query(Subscription).filter(
                    Subscription.user_id == user_id,
                    Subscription.stripe_subscription_id != stripe_subscription.id
                ).all()
                
                if other_subscriptions:
                    logger.warning(f"Deleting {len(other_subscriptions)} other subscription(s) for user {user_id} before creating new one")
                    for other_sub in other_subscriptions:
                        db.delete(other_sub)
                    db.flush()  # Ensure deletes happen before insert
                
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
                    stripe_metered_item_id=metered_item_id,
                )
                db.add(subscription)
        
        db.commit()
        db.refresh(subscription)
        
        logger.info(f"Successfully saved subscription {subscription.id}: {plan_type} ({status})")
        return subscription
        
    except IntegrityError as e:
        db.rollback()
        logger.error(f"IntegrityError: {e}", exc_info=True)
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating subscription: {e}", exc_info=True)
        return None


def _get_plan_type_from_price(price_id: str) -> str:
    """Get plan type from Stripe price ID."""
    plans = get_plans()
    for plan_key, plan_config in plans.items():
        if plan_config.get('stripe_price_id') == price_id:
            return plan_key
    
    logger.warning(f"Price ID {price_id} not found in configuration")
    return 'free'


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


def normalize_plan_type(plan_type: str) -> str:
    """
    Normalize plan type to new key names for backward compatibility.
    Maps old plan keys to new ones.
    
    Args:
        plan_type: Plan type (may be old or new key)
        
    Returns:
        Normalized plan type (new key)
    """
    # Map old keys to new keys for backward compatibility
    plan_type_map = {
        'medium': 'starter',
        'pro': 'creator',
        # New keys map to themselves
        'free': 'free',
        'starter': 'starter',
        'creator': 'creator',
        'unlimited': 'unlimited',
    }
    return plan_type_map.get(plan_type, plan_type)




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


def record_token_usage_to_stripe(
    user_id: int,
    tokens_used: int,
    db: Session
) -> bool:
    """
    Record token usage to Stripe for metered billing (overage tokens).
    
    This function calculates how many tokens are overage (beyond included tokens)
    and reports only the NEW overage tokens to Stripe. It uses 'increment' action
    to add to existing usage for the billing period.
    
    Args:
        user_id: User ID
        tokens_used: Number of tokens just consumed
        db: Database session
        
    Returns:
        True if usage was recorded successfully, False otherwise
    """
    if not STRIPE_SECRET_KEY:
        logger.warning("Cannot record token usage: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        from token_helpers import get_or_create_token_balance
        from stripe_config import get_plan_monthly_tokens
        
        # Get user's subscription
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if not subscription:
            logger.debug(f"No subscription found for user {user_id}, skipping Stripe usage recording")
            return False
        
        # Unlimited and free plans don't have metered usage
        if subscription.plan_type in ('unlimited', 'free'):
            return True
        
        # Check if subscription has metered item ID
        if not subscription.stripe_metered_item_id:
            logger.debug(f"Subscription {subscription.stripe_subscription_id} has no metered item ID, skipping usage recording")
            return False
        
        # Get token balance to calculate overage
        balance = get_or_create_token_balance(user_id, db)
        included_tokens = get_plan_monthly_tokens(subscription.plan_type)
        
        # Calculate overage - we ONLY track tokens beyond the included amount
        # Example: Starter plan gives 100 tokens included
        #   - If user uses 50 tokens: overage = 0 (all within included)
        #   - If user uses 150 tokens: overage = 50 (only tokens 101-150 are billed)
        # tokens_used_this_period includes the tokens just consumed
        total_used = balance.tokens_used_this_period
        current_overage = max(0, total_used - included_tokens)
        
        # Calculate previous overage (before this consumption)
        # This allows us to report only the NEW overage tokens incrementally
        previous_total_used = total_used - tokens_used
        previous_overage = max(0, previous_total_used - included_tokens)
        
        # Only report NEW overage tokens (incremental)
        # This ensures we only report tokens beyond the included amount, not the included tokens
        # Example: User had used 100 tokens (0 overage), now uses 5 more (105 total)
        #   - current_overage = 105 - 100 = 5
        #   - previous_overage = 100 - 100 = 0
        #   - new_overage = 5 - 0 = 5 (only report the 5 overage tokens to Stripe)
        new_overage = current_overage - previous_overage
        
        if new_overage > 0:
            try:
                # Report usage to Stripe using 'increment' action
                stripe.SubscriptionItem.create_usage_record(
                    subscription.stripe_metered_item_id,
                    quantity=new_overage,
                    action='increment',
                    timestamp=int(datetime.now(timezone.utc).timestamp())
                )
                logger.info(
                    f"Recorded {new_overage} overage tokens to Stripe for user {user_id} "
                    f"(total used: {total_used}, included: {included_tokens}, overage: {current_overage})"
                )
                return True
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error recording usage for user {user_id}: {e}")
                return False
        else:
            # No new overage to report (all tokens were from included allocation)
            logger.debug(
                f"No new overage for user {user_id} "
                f"(total used: {total_used}, included: {included_tokens}, overage: {current_overage})"
            )
            return True
            
    except Exception as e:
        logger.error(f"Error recording token usage to Stripe for user {user_id}: {e}", exc_info=True)
        return False