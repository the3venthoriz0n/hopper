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
        # Always query fresh user object to avoid stale data
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
            
        if user.stripe_customer_id:
            # Verify the customer actually exists in Stripe before returning it
            existing_customer_id = user.stripe_customer_id
            try:
                stripe.Customer.retrieve(existing_customer_id)
                logger.info(f"User {user_id} already has valid Stripe customer: {existing_customer_id}")
                return existing_customer_id
            except stripe.error.InvalidRequestError as e:
                if 'No such customer' in str(e):
                    logger.warning(f"Customer {existing_customer_id} in DB doesn't exist in Stripe for user {user_id}, creating new one")
                    # Clear the invalid customer ID so we create a new one
                    user.stripe_customer_id = None
                    db.commit()
                    # Re-query user to ensure we have fresh state
                    db.expire(user)
                    user = db.query(User).filter(User.id == user_id).first()
                else:
                    # Some other error, log and continue to create new customer
                    logger.warning(f"Error verifying customer {existing_customer_id} for user {user_id}: {e}, creating new one")
                    user.stripe_customer_id = None
                    db.commit()
                    db.expire(user)
                    user = db.query(User).filter(User.id == user_id).first()
            except Exception as e:
                logger.warning(f"Unexpected error verifying customer {existing_customer_id} for user {user_id}: {e}, creating new one")
                user.stripe_customer_id = None
                db.commit()
                db.expire(user)
                user = db.query(User).filter(User.id == user_id).first()
        
        # Double-check that customer_id is None before creating
        if user.stripe_customer_id:
            logger.error(f"Unexpected: user {user_id} still has customer_id {user.stripe_customer_id} after clearing. This should not happen.")
            # Force clear it
            user.stripe_customer_id = None
            db.commit()
            db.expire(user)
            user = db.query(User).filter(User.id == user_id).first()
        
        # At this point, user.stripe_customer_id should definitely be None
        # Create a new customer
        customer = stripe.Customer.create(
            email=email,
            metadata={'user_id': str(user_id)}
        )
        
        # Update user with new customer ID
        user.stripe_customer_id = customer.id
        db.commit()
        
        logger.info(f"Created Stripe customer for user {user_id}: {customer.id} (replaced old invalid customer)")
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
    """
    Ensure user has a valid Stripe customer that exists in Stripe.
    Creates a new customer if the existing one doesn't exist in Stripe.
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Valid Stripe customer ID or None if creation failed
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        return None
    
    # create_stripe_customer now verifies the customer exists in Stripe before returning it
    # If the customer doesn't exist, it will clear the old ID and create a new one
    customer_id = create_stripe_customer(user.email, user_id, db)
    return customer_id


def cancel_all_user_subscriptions(user_id: int, db: Session, verify_cancellation: bool = True) -> bool:
    """
    Cancel all active subscriptions for a user in both Stripe and the database.
    This ensures a user can only have one subscription at a time.
    
    Args:
        user_id: User ID
        db: Database session
        verify_cancellation: If True, verify all subscriptions are canceled before returning
        
    Returns:
        True if all subscriptions were canceled successfully, False otherwise
    """
    if not STRIPE_SECRET_KEY:
        logger.warning("Cannot cancel subscriptions: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return False
        
        customer_id = user.stripe_customer_id
        if not customer_id:
            # No customer ID means no Stripe subscriptions
            # Still check database for any orphaned subscriptions
            db_subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
            for sub in db_subscriptions:
                db.delete(sub)
            if db_subscriptions:
                db.commit()
                logger.info(f"Deleted {len(db_subscriptions)} orphaned subscription(s) from database for user {user_id}")
            return True
        
        # Delete all subscriptions from database first (to prevent race conditions)
        db_subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
        deleted_count = len(db_subscriptions)
        subscription_ids_to_cancel = [sub.stripe_subscription_id for sub in db_subscriptions if sub.stripe_subscription_id]
        
        for sub in db_subscriptions:
            db.delete(sub)
        
        if deleted_count > 0:
            db.commit()
            logger.info(f"Deleted {deleted_count} subscription(s) from database for user {user_id}")
        
        # Cancel all active subscriptions in Stripe
        try:
            stripe_subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status='all',  # Get all subscriptions (active, canceled, etc.)
                limit=100
            )
            
            canceled_count = 0
            subscriptions_to_cancel = []
            
            for stripe_sub in stripe_subscriptions.data:
                # Cancel any subscription that's not already canceled or incomplete_expired
                if stripe_sub.status not in ('canceled', 'incomplete_expired'):
                    subscriptions_to_cancel.append(stripe_sub.id)
            
            # Cancel all subscriptions that need canceling
            for sub_id in subscriptions_to_cancel:
                try:
                    stripe.Subscription.delete(sub_id)
                    canceled_count += 1
                    logger.info(f"Canceled Stripe subscription {sub_id} for user {user_id}")
                except stripe.error.InvalidRequestError as e:
                    error_str = str(e)
                    if 'No such subscription' in error_str or 'already been canceled' in error_str.lower():
                        # Subscription already canceled or doesn't exist - that's fine
                        canceled_count += 1
                        logger.debug(f"Stripe subscription {sub_id} already canceled or doesn't exist")
                    else:
                        logger.warning(f"Failed to cancel Stripe subscription {sub_id}: {e}")
                except Exception as e:
                    logger.warning(f"Error canceling Stripe subscription {sub_id}: {e}")
            
            if canceled_count > 0:
                logger.info(f"Canceled {canceled_count} Stripe subscription(s) for user {user_id}")
            
            # Verify cancellation if requested
            if verify_cancellation and subscriptions_to_cancel:
                import time
                max_retries = 3
                retry_delay = 0.5  # 500ms
                
                for attempt in range(max_retries):
                    # Re-fetch subscriptions to verify they're canceled
                    remaining_active = stripe.Subscription.list(
                        customer=customer_id,
                        status='active',
                        limit=100
                    )
                    
                    if len(remaining_active.data) == 0:
                        logger.info(f"Verified all subscriptions canceled for user {user_id} (attempt {attempt + 1})")
                        break
                    
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"User {user_id} still has {len(remaining_active.data)} active subscription(s) "
                            f"after cancellation (attempt {attempt + 1}/{max_retries}), retrying..."
                        )
                        time.sleep(retry_delay)
                    else:
                        logger.error(
                            f"User {user_id} still has {len(remaining_active.data)} active subscription(s) "
                            f"after {max_retries} attempts. Subscription IDs: "
                            f"{[s.id for s in remaining_active.data]}"
                        )
                        # Force cancel any remaining active subscriptions
                        for remaining_sub in remaining_active.data:
                            try:
                                stripe.Subscription.delete(remaining_sub.id)
                                logger.warning(f"Force canceled remaining subscription {remaining_sub.id} for user {user_id}")
                            except Exception as e:
                                logger.error(f"Failed to force cancel subscription {remaining_sub.id}: {e}")
                        
        except stripe.error.StripeError as e:
            logger.warning(f"Error listing Stripe subscriptions for customer {customer_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error canceling Stripe subscriptions for user {user_id}: {e}", exc_info=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error canceling all subscriptions for user {user_id}: {e}", exc_info=True)
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
    """
    Create a free subscription for a new user via Stripe.
    Cancels all existing subscriptions first to ensure only one subscription exists.
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create free subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        # Cancel all existing subscriptions first to ensure only one subscription exists
        cancel_all_user_subscriptions(user_id, db)
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has Stripe customer
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
        
        # Get free plan price ID
        from stripe_config import get_plan_price_id
        price_id = get_plan_price_id('free')
        if not price_id:
            logger.error("Free plan price ID not configured")
            return None
        
        # Create Stripe subscription for free plan ($0/month)
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
        )
        
        # Update database subscription from Stripe subscription
        subscription = update_subscription_from_stripe(stripe_subscription, db, user_id=user_id)
        
        if subscription:
            # Explicitly initialize tokens for new subscription
            # Use reset_tokens_for_subscription with is_renewal=False to add monthly tokens
            from token_helpers import reset_tokens_for_subscription
            from stripe_config import get_plan_monthly_tokens
            token_initialized = reset_tokens_for_subscription(
                user_id,
                subscription.plan_type,
                subscription.current_period_start,
                subscription.current_period_end,
                db,
                is_renewal=False  # False = new subscription, adds tokens to balance
            )
            if token_initialized:
                monthly_tokens = get_plan_monthly_tokens('free')
                logger.info(f"Created free Stripe subscription for user {user_id}: {stripe_subscription.id} and initialized {monthly_tokens} tokens")
            else:
                logger.warning(f"Created free Stripe subscription for user {user_id}: {stripe_subscription.id} but token initialization failed")
        else:
            logger.error(f"Failed to create subscription record for user {user_id}")
        
        return subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating free subscription for user {user_id}: {e}")
        db.rollback()
        return None
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
    Create an unlimited subscription via Stripe (admin feature).
    Cancels all existing subscriptions first to ensure only one subscription exists.
    
    Args:
        user_id: User ID
        preserved_tokens: Token balance to preserve (stored in subscription metadata)
        db: Database session
        
    Returns:
        Subscription model instance or None if creation failed
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create unlimited subscription: STRIPE_SECRET_KEY not set")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return None
        
        # Ensure user has Stripe customer
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
        
        # Get unlimited plan price ID
        from stripe_config import get_plan_price_id
        price_id = get_plan_price_id('unlimited')
        if not price_id:
            logger.error("Unlimited plan price ID not configured")
            return None
        
        # Cancel all existing subscriptions first to ensure only one subscription exists
        cancel_all_user_subscriptions(user_id, db)
        
        # Create Stripe subscription for unlimited plan
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={
                'user_id': str(user_id),
                'preserved_tokens': str(preserved_tokens)  # Store preserved tokens in metadata
            },
        )
        
        # Update database subscription from Stripe subscription
        subscription = update_subscription_from_stripe(stripe_subscription, db, user_id=user_id)
        
        if subscription:
            # Store preserved tokens in subscription record
            subscription.preserved_tokens_balance = preserved_tokens
            db.commit()
            db.refresh(subscription)
            
            # Unlimited plans don't need token initialization (they bypass token checks)
            # But we should still update the period for consistency
            from token_helpers import get_or_create_token_balance
            token_balance = get_or_create_token_balance(user_id, db)
            token_balance.period_start = subscription.current_period_start
            token_balance.period_end = subscription.current_period_end
            token_balance.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Created unlimited Stripe subscription for user {user_id}: {stripe_subscription.id} (preserved {preserved_tokens} tokens)")
        else:
            logger.error(f"Failed to create subscription record for user {user_id}")
        
        return subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating unlimited subscription for user {user_id}: {e}")
        db.rollback()
        return None
    except Exception as e:
        logger.error(f"Error creating unlimited subscription for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return None


def create_stripe_subscription(user_id: int, price_id: str, db: Session) -> Optional[Subscription]:
    """
    Create a Stripe subscription directly (admin use).
    
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
        
        # Ensure user has a valid Stripe customer that exists in Stripe
        customer_id = ensure_stripe_customer_exists(user_id, db)
        if not customer_id:
            return None
        
        # Create subscription in Stripe
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(user_id)},
        )
        
        # Update database subscription from Stripe subscription
        subscription = update_subscription_from_stripe(stripe_subscription, db, user_id=user_id)
        
        logger.info(f"Created Stripe subscription for user {user_id}: {stripe_subscription.id}")
        return subscription
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating subscription for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating Stripe subscription for user {user_id}: {e}", exc_info=True)
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
        logger.info(f"update_subscription_from_stripe called for subscription {stripe_subscription.id}, user_id={user_id}")
        
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
        
        logger.info(f"Determined user_id={user_id} for subscription {stripe_subscription.id}")
        
        # Extract subscription details
        # Handle both legacy format (subscription.plan) and modern format (subscription.items.data[0].price)
        # Note: Even in legacy format, subscription.plan.id is actually a price ID (starts with price_)
        price_id = None
        
        # First, check for legacy format: subscription.plan.id (this is actually a price ID)
        # Handle both dict and object formats
        if hasattr(stripe_subscription, 'plan') and stripe_subscription.plan:
            plan_id = None
            if isinstance(stripe_subscription.plan, dict):
                plan_id = stripe_subscription.plan.get('id')
            elif hasattr(stripe_subscription.plan, 'id'):
                plan_id = stripe_subscription.plan.id
            
            if plan_id:
                price_id = plan_id
                logger.info(f"Found legacy plan format for subscription {stripe_subscription.id}: {price_id}")
        
        # If not legacy, check modern format: subscription.items.data[0].price
        if not price_id:
            items_data = []
            if hasattr(stripe_subscription, 'items') and stripe_subscription.items:
                items_data = stripe_subscription.items.data if hasattr(stripe_subscription.items, 'data') else []
            
            # Check if we need to expand items
            needs_expansion = (
                not items_data or
                (items_data and len(items_data) > 0 and (
                    not hasattr(items_data[0], 'price') or
                    not items_data[0].price or
                    not hasattr(items_data[0].price, 'id')
                ))
            )
            
            if needs_expansion:
                # Retrieve subscription with expanded items
                logger.debug(f"Retrieving subscription {stripe_subscription.id} with expanded items")
                stripe_subscription = stripe.Subscription.retrieve(
                    stripe_subscription.id,
                    expand=['items.data.price']
                )
                # Re-check legacy format after expansion (in case it wasn't present before)
                if not price_id and hasattr(stripe_subscription, 'plan') and stripe_subscription.plan:
                    plan_id = None
                    if isinstance(stripe_subscription.plan, dict):
                        plan_id = stripe_subscription.plan.get('id')
                    elif hasattr(stripe_subscription.plan, 'id'):
                        plan_id = stripe_subscription.plan.id
                    
                    if plan_id:
                        price_id = plan_id
                        logger.info(f"Found legacy plan format after expansion for subscription {stripe_subscription.id}: {price_id}")
                
                if hasattr(stripe_subscription, 'items') and stripe_subscription.items:
                    items_data = stripe_subscription.items.data if hasattr(stripe_subscription.items, 'data') else []
            
            # Try to get price from items (modern format)
            if not price_id and items_data and len(items_data) > 0:
                first_item = items_data[0]
                if hasattr(first_item, 'price') and first_item.price and hasattr(first_item.price, 'id'):
                    price_id = first_item.price.id
                    logger.info(f"Found modern items format for subscription {stripe_subscription.id}: {price_id}")
        
        if not price_id:
            logger.error(f"Subscription {stripe_subscription.id} has no price/plan data (checked both legacy plan and modern items formats)")
            return None
        
        plan_type = _get_plan_type_from_price(price_id)
        logger.info(f"Determined plan_type={plan_type} for subscription {stripe_subscription.id} (price_id={price_id})")
        
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
        # First, check if subscription with this stripe_subscription_id exists
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription.id
        ).first()
        
        if subscription:
            logger.info(f"Found existing subscription {subscription.id} with stripe_subscription_id {stripe_subscription.id}")
        else:
            logger.info(f"No subscription found with stripe_subscription_id {stripe_subscription.id}, checking for existing user subscription")
        
        # If found but belongs to different user, update user_id
        if subscription and subscription.user_id != user_id:
            logger.warning(
                f"Subscription {stripe_subscription.id} belongs to user {subscription.user_id}, "
                f"updating to user {user_id}"
            )
            subscription.user_id = user_id
        
        # If not found by stripe_subscription_id, check if user has existing subscription
        if not subscription:
            existing_user_sub = db.query(Subscription).filter(
                Subscription.user_id == user_id
            ).first()
            
            if existing_user_sub:
                logger.info(f"User {user_id} has existing subscription {existing_user_sub.id} with different stripe_subscription_id {existing_user_sub.stripe_subscription_id}")
                # User has existing subscription - update it to use new stripe_subscription_id
                # But first, check if new stripe_subscription_id already exists (orphaned)
                conflicting = db.query(Subscription).filter(
                    Subscription.stripe_subscription_id == stripe_subscription.id
                ).first()
                
                if conflicting and conflicting.id != existing_user_sub.id:
                    # Orphaned subscription exists - delete it
                    logger.info(f"Removing orphaned subscription {conflicting.id} with stripe_subscription_id {stripe_subscription.id}")
                    db.delete(conflicting)
                    db.flush()
                
                # Use existing subscription and update it
                subscription = existing_user_sub
                logger.info(f"Updating existing subscription {subscription.id} for user {user_id} to use new Stripe subscription {stripe_subscription.id}")
            else:
                logger.info(f"User {user_id} has no existing subscription, will create new one")
        
        # Update or create subscription
        if subscription:
            # Update existing subscription
            logger.info(f"Updating subscription {subscription.id} for user {user_id}")
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
            # Create new subscription (user has no existing subscription)
            logger.info(f"Creating new subscription for user {user_id} with stripe_subscription_id {stripe_subscription.id}")
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
            logger.info(f"Added subscription to session for user {user_id}")
        
        logger.info(f"Committing subscription for user {user_id}, stripe_subscription_id {stripe_subscription.id}")
        db.commit()
        logger.info(f"Commit successful, refreshing subscription")
        db.refresh(subscription)
        
        # Verify subscription was actually saved
        verification = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_subscription.id
        ).first()
        if not verification:
            logger.error(f"CRITICAL: Subscription {stripe_subscription.id} was not found in database after commit!")
            return None
        
        logger.info(f"Successfully updated/created subscription {subscription.id} for user {user_id}: {plan_type} ({status})")
        return subscription
        
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        logger.error(
            f"Database IntegrityError for subscription {stripe_subscription.id} (user_id: {user_id}): {error_msg}", 
            exc_info=True
        )
        
        # Try to recover: if it's a unique constraint on stripe_subscription_id, 
        # find and update the existing subscription
        if 'stripe_subscription_id' in error_msg.lower() or 'unique' in error_msg.lower():
            existing = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == stripe_subscription.id
            ).first()
            if existing:
                logger.info(f"Found existing subscription {existing.id} with stripe_subscription_id {stripe_subscription.id}, updating it")
                try:
                    existing.user_id = user_id
                    existing.stripe_customer_id = stripe_subscription.customer
                    existing.plan_type = plan_type
                    existing.status = status
                    existing.current_period_start = datetime.fromtimestamp(
                        stripe_subscription.current_period_start, tz=timezone.utc
                    )
                    existing.current_period_end = datetime.fromtimestamp(
                        stripe_subscription.current_period_end, tz=timezone.utc
                    )
                    existing.cancel_at_period_end = stripe_subscription.cancel_at_period_end
                    existing.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(existing)
                    logger.info(f"Recovered subscription {existing.id} for user {user_id}")
                    return existing
                except Exception as recover_error:
                    logger.error(f"Failed to recover subscription: {recover_error}", exc_info=True)
                    db.rollback()
        
        return None
    except Exception as e:
        db.rollback()
        logger.error(
            f"Unexpected error updating subscription {stripe_subscription.id} (user_id: {user_id}): {e}", 
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