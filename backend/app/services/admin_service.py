"""Admin service - Admin operations and user management"""
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_transaction import TokenTransaction
from app.models.video import Video
from app.services.token_service import get_token_balance
from app.services.video.helpers import cleanup_video_file

logger = logging.getLogger(__name__)
cleanup_logger = logging.getLogger("cleanup")


def list_users_with_subscriptions(
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    db: Session = None
) -> Dict:
    """List users with basic info and subscription aggregation
    
    Args:
        page: Page number (1-indexed)
        limit: Users per page
        search: Optional search term for email
        db: Database session
    
    Returns:
        Dict with 'users', 'total', 'page', 'limit'
    """
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        query = db.query(User)
        if search:
            query = query.filter(User.email.ilike(f"%{search}%"))
        
        total = query.count()
        users = query.order_by(User.created_at.desc()).offset((page-1)*limit).limit(limit).all()
        
        # Get subscriptions for all users in one query
        user_ids = [u.id for u in users]
        subscriptions = {s.user_id: s for s in db.query(Subscription).filter(Subscription.user_id.in_(user_ids)).all()}
        
        return {
            "users": [{
                "id": u.id,
                "email": u.email,
                "created_at": u.created_at.isoformat(),
                "plan_type": subscriptions.get(u.id).plan_type if subscriptions.get(u.id) else None,
                "is_admin": u.is_admin
            } for u in users],
            "total": total,
            "page": page,
            "limit": limit
        }
    finally:
        if should_close:
            db.close()


def get_user_details_with_balance(
    user_id: int,
    db: Session
) -> Dict:
    """Get detailed user information with token balance and usage
    
    Args:
        user_id: User ID to get details for
        db: Database session
    
    Returns:
        Dict with user, token_balance, token_usage, and subscription info
    
    Raises:
        ValueError: If user not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    
    # Get token balance
    balance = get_token_balance(user_id, db)
    
    # Get subscription info
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    # Calculate total tokens used (sum of all negative token transactions, which are deductions)
    total_tokens_used = db.query(func.sum(func.abs(TokenTransaction.tokens))).filter(
        TokenTransaction.user_id == user_id,
        TokenTransaction.tokens < 0  # Negative tokens represent usage/deductions
    ).scalar() or 0
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "plan_type": subscription.plan_type if subscription else None,
            "is_admin": user.is_admin,
            "stripe_customer_id": user.stripe_customer_id
        },
        "token_balance": balance,
        "token_usage": {
            "tokens_used_this_period": balance.get("tokens_used_this_period", 0) if balance else 0,
            "total_tokens_used": int(total_tokens_used)
        },
        "subscription": {
            "plan_type": subscription.plan_type if subscription else None,
            "status": subscription.status if subscription else None
        } if subscription else None
    }


def trigger_manual_cleanup(
    user_id: int,
    db: Session
) -> Dict:
    """Manually trigger cleanup of old and orphaned files
    
    This function allows users to clean up their own old uploaded videos.
    Removes video files for videos uploaded more than 24 hours ago.
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with cleanup results
    """
    cleanup_logger.info(f"Manual cleanup triggered by user {user_id}")
    
    # Clean up user's old uploaded videos (older than 24 hours)
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
    old_uploaded_videos = db.query(Video).filter(
        Video.user_id == user_id,
        Video.status == "uploaded",
        Video.created_at < cutoff_time
    ).all()
    
    cleaned_count = 0
    for video in old_uploaded_videos:
        if cleanup_video_file(video):
            cleaned_count += 1
    
    cleanup_logger.info(f"Manual cleanup by user {user_id}: cleaned {cleaned_count} files")
    
    return {
        "success": True,
        "cleaned_files": cleaned_count,
        "message": f"Cleaned up {cleaned_count} old uploaded video files"
    }


def create_user_with_admin_flag(
    email: str,
    password: str,
    is_admin: bool,
    db: Session
) -> Dict[str, Any]:
    """Create a new user and optionally set admin flag
    
    Uses shared helper to ensure user has subscription and verification (DRY).
    
    Args:
        email: User email
        password: User password
        is_admin: Whether to set admin flag
        db: Database session
    
    Returns:
        Dict with created user info
    
    Raises:
        ValueError: If user creation fails
    """
    from app.services.auth_service import create_user_with_stripe_setup, hash_password
    
    # Create user with Stripe setup using shared helper (DRY)
    password_hash = hash_password(password)
    user = create_user_with_stripe_setup(
        email=email,
        password_hash=password_hash,
        is_email_verified=True,  # Admin-created users are verified
        db=db
    )
    
    # Set admin flag if requested
    if is_admin:
        user.is_admin = True
        db.commit()
    
    return {"user": {"id": user.id, "email": user.email}}


def reset_user_password_admin(
    target_user_id: int,
    password: str,
    admin_id: int,
    db: Session
) -> Dict[str, Any]:
    """Reset a user's password (admin operation)
    
    Args:
        target_user_id: Target user ID
        password: New password
        admin_id: Admin user ID performing the action
        db: Database session
    
    Returns:
        Dict with success message
    
    Raises:
        ValueError: If user not found
    """
    from app.services.auth_service import set_user_password
    
    success = set_user_password(target_user_id, password, db=db)
    if not success:
        raise ValueError("User not found")
    
    logger.info(f"Admin {admin_id} reset password for user {target_user_id}")
    return {"message": "Password reset successfully"}


def enroll_user_unlimited_plan(
    target_user_id: int,
    admin_id: int,
    db: Session
) -> Dict[str, Any]:
    """Enroll a user in the unlimited plan via Stripe (admin operation)
    
    Cancels all existing subscriptions first to ensure only one subscription exists.
    
    Args:
        target_user_id: Target user ID
        admin_id: Admin user ID performing the action
        db: Database session
    
    Returns:
        Dict with success message
    
    Raises:
        ValueError: If user not found or enrollment fails
    """
    from app.services.stripe_service import cancel_all_user_subscriptions, create_stripe_subscription
    from app.services.token_service import get_or_create_token_balance
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise ValueError("User not found")
    
    # Check if user already has unlimited plan
    existing_subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    if existing_subscription and existing_subscription.plan_type == 'unlimited':
        return {"message": f"User {target_user_id} already has unlimited plan"}
    
    # Preserve current plan type and token balance before canceling subscriptions and enrolling in unlimited
    preserved_plan_type = existing_subscription.plan_type if existing_subscription else None
    token_balance = get_or_create_token_balance(target_user_id, db)
    preserved_tokens = token_balance.tokens_remaining
    
    # Cancel all existing subscriptions first to ensure only one subscription exists
    cancel_all_user_subscriptions(target_user_id, db)
    
    # Create unlimited subscription via Stripe
    subscription = create_stripe_subscription(target_user_id, "unlimited", db, preserved_tokens=preserved_tokens, preserved_plan_type=preserved_plan_type)
    
    if not subscription:
        raise ValueError("Failed to create unlimited subscription")
    
    logger.info(f"Admin {admin_id} enrolled user {target_user_id} in unlimited plan (preserved {preserved_tokens} tokens, previous plan: {preserved_plan_type})")
    
    return {"message": f"User {target_user_id} enrolled in unlimited plan"}


def unenroll_user_unlimited_plan(
    target_user_id: int,
    admin_id: int,
    db: Session
) -> Dict[str, Any]:
    """Unenroll a user from the unlimited plan by canceling Stripe subscription (admin operation)
    
    Args:
        target_user_id: Target user ID
        admin_id: Admin user ID performing the action
        db: Database session
    
    Returns:
        Dict with success message
    
    Raises:
        ValueError: If user not found, has no subscription, or is not on unlimited plan
    """
    import stripe
    from app.services.stripe_service import create_stripe_subscription
    from app.services.token_service import get_or_create_token_balance, get_plan_tokens
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise ValueError("User not found")
    
    subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    if not subscription:
        raise ValueError("User has no subscription")
    
    if subscription.plan_type != 'unlimited':
        raise ValueError(f"User is not on unlimited plan (current: {subscription.plan_type})")
    
    # Get preserved token balance and plan type before canceling subscriptions
    preserved_tokens = subscription.preserved_tokens_balance if subscription.preserved_tokens_balance is not None else 0
    preserved_plan_type = subscription.preserved_plan_type or "free_daily"  # Default to free_daily for existing unlimited subscriptions
    
    # Set balance to preserved_tokens before creating subscription
    # This ensures that when create_stripe_subscription adds plan tokens,
    # we can then set it back to just preserved_tokens (without the plan tokens)
    token_balance = get_or_create_token_balance(target_user_id, db)
    token_balance.tokens_remaining = preserved_tokens
    db.commit()
    
    # Cancel Stripe subscription if it exists
    if subscription.stripe_subscription_id:
        try:
            from app.services.stripe_service import cancel_subscription_with_invoice
            cancel_subscription_with_invoice(subscription.stripe_subscription_id, invoice_now=True)
            logger.info(f"Canceled Stripe subscription {subscription.stripe_subscription_id} for user {target_user_id}")
        except Exception as e:
            logger.warning(f"Failed to cancel Stripe subscription {subscription.stripe_subscription_id}: {e}")
            # Continue anyway - we'll delete the DB record and create new subscription
    
    # Delete existing subscription record from database to avoid unique constraint violation
    # This must happen BEFORE create_stripe_subscription tries to insert a new record
    db.delete(subscription)
    db.commit()
    logger.info(f"Deleted existing subscription record for user {target_user_id} before creating {preserved_plan_type} subscription")
    
    # Now create subscription with restored plan type (database is clean, no existing record)
    try:
        restored_subscription = create_stripe_subscription(target_user_id, preserved_plan_type, db, skip_token_reset=True)
        if not restored_subscription:
            # Check if there are still active subscriptions preventing creation
            if target_user.stripe_customer_id:
                try:
                    remaining_active = stripe.Subscription.list(
                        customer=target_user.stripe_customer_id,
                        status='active',
                        limit=100
                    )
                    if len(remaining_active.data) > 0:
                        raise ValueError(
                            f"Cannot unenroll: User still has {len(remaining_active.data)} active subscription(s) "
                            f"that could not be canceled. Subscription IDs: {[s.id for s in remaining_active.data]}. "
                            f"Please try again or contact support."
                        )
                except Exception as e:
                    logger.error(f"Error checking remaining subscriptions: {e}")
            
            raise ValueError(f"Failed to create {preserved_plan_type} subscription. Please try again or contact support.")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error unenrolling user {target_user_id} from unlimited plan: {e}", exc_info=True)
        raise ValueError(f"Failed to unenroll from unlimited plan: {str(e)}") from e
    
    # After create_stripe_subscription, we need to set tokens correctly
    # Since we used skip_token_reset=True, tokens weren't modified by create_stripe_subscription
    # We want the final balance to be just preserved_tokens (not preserved_tokens + plan tokens)
    token_balance = get_or_create_token_balance(target_user_id, db)
    restored_plan_tokens = get_plan_tokens(preserved_plan_type)
    
    # Set tokens_remaining to preserved_tokens
    token_balance.tokens_remaining = preserved_tokens
    
    # Set monthly_tokens to preserved_tokens (or restored plan tokens if preserved is less)
    # This ensures the counter shows the correct starting balance
    token_balance.monthly_tokens = max(preserved_tokens, restored_plan_tokens) if restored_plan_tokens > 0 else preserved_tokens
    
    # Ensure tokens_used_this_period is 0 (fresh start on restored plan)
    token_balance.tokens_used_this_period = 0
    
    # Update period to match new subscription
    token_balance.period_start = restored_subscription.current_period_start
    token_balance.period_end = restored_subscription.current_period_end
    token_balance.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    logger.info(
        f"Set token balance after unenroll: tokens_remaining={token_balance.tokens_remaining}, "
        f"monthly_tokens={token_balance.monthly_tokens}, preserved_tokens={preserved_tokens}"
    )
    
    logger.info(
        f"Admin {admin_id} unenrolled user {target_user_id} from unlimited plan "
        f"(restored {preserved_tokens} preserved tokens, moved to {preserved_plan_type} plan without adding plan tokens)"
    )
    
    return {"message": f"User {target_user_id} unenrolled from unlimited plan"}


def switch_user_plan(
    target_user_id: int,
    plan_key: str,
    admin_id: int,
    db: Session
) -> Dict[str, Any]:
    """Switch a user to a different plan (admin operation)
    
    Cancels existing subscription with final invoice for overage, then creates new subscription.
    Preserves tokens (user paid for full period, no prorating).
    
    Args:
        target_user_id: Target user ID
        plan_key: Plan key to switch to
        admin_id: Admin user ID performing the action
        db: Database session
    
    Returns:
        Dict with success message
    
    Raises:
        ValueError: If user not found, invalid plan, or switch fails
    """
    from app.services.stripe_service import (
        cancel_all_user_subscriptions, create_stripe_subscription,
        get_plans, cancel_subscription_with_invoice
    )
    from app.services.token_service import get_or_create_token_balance, get_plan_tokens
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise ValueError("User not found")
    
    plan_key = plan_key.lower()
    plans = get_plans()
    
    # Validate plan key
    if plan_key not in plans:
        raise ValueError(f"Invalid plan: {plan_key}. Valid plans: {', '.join(plans.keys())}")
    
    # Get current subscription
    existing_subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    current_plan = existing_subscription.plan_type if existing_subscription else None
    
    # Check if already on target plan
    if current_plan == plan_key:
        return {"message": f"User {target_user_id} is already on {plan_key} plan"}
    
    # Preserve current token balance (user paid for full period)
    token_balance = get_or_create_token_balance(target_user_id, db)
    preserved_tokens = token_balance.tokens_remaining
    
    # Cancel existing subscription with final invoice for overage
    if existing_subscription and existing_subscription.stripe_subscription_id:
        try:
            cancel_subscription_with_invoice(existing_subscription.stripe_subscription_id, invoice_now=True)
            logger.info(f"Canceled existing subscription {existing_subscription.stripe_subscription_id} for user {target_user_id} (switching to {plan_key})")
        except Exception as e:
            logger.warning(f"Failed to cancel existing subscription for user {target_user_id}: {e}")
            # Continue anyway - we'll create the new subscription
    
    # Cancel all subscriptions to ensure clean state
    cancel_all_user_subscriptions(target_user_id, db, invoice_now=True)
    
    # Create new subscription based on plan type
    new_subscription = None
    if plan_key == 'free' or plan_key == 'free_daily':
        # Create free_daily subscription (skip token reset - we'll preserve tokens)
        new_subscription = create_stripe_subscription(target_user_id, "free_daily", db, skip_token_reset=True)
        if new_subscription:
            # Preserve tokens and set monthly_tokens correctly
            free_plan_tokens = get_plan_tokens('free_daily')
            token_balance = get_or_create_token_balance(target_user_id, db)
            token_balance.tokens_remaining = preserved_tokens
            token_balance.monthly_tokens = max(preserved_tokens, free_plan_tokens)
            token_balance.tokens_used_this_period = 0
            token_balance.period_start = new_subscription.current_period_start
            token_balance.period_end = new_subscription.current_period_end
            token_balance.updated_at = datetime.now(timezone.utc)
            db.commit()
    elif plan_key == 'unlimited':
        # Create unlimited subscription
        new_subscription = create_stripe_subscription(target_user_id, "unlimited", db, preserved_tokens=preserved_tokens)
    else:
        # Create paid subscription via Stripe using create_stripe_subscription
        new_subscription = create_stripe_subscription(target_user_id, plan_key, db, skip_token_reset=True)
        if not new_subscription:
            raise ValueError(f"Failed to create subscription for plan {plan_key}")
        
        # Preserve tokens and set monthly_tokens correctly
        plan_tokens = get_plan_tokens(plan_key)
        token_balance = get_or_create_token_balance(target_user_id, db)
        token_balance.tokens_remaining = preserved_tokens
        token_balance.monthly_tokens = max(preserved_tokens, plan_tokens)
        token_balance.tokens_used_this_period = 0
        token_balance.period_start = new_subscription.current_period_start
        token_balance.period_end = new_subscription.current_period_end
        token_balance.updated_at = datetime.now(timezone.utc)
        db.commit()
    
    if not new_subscription:
        raise ValueError(f"Failed to create {plan_key} subscription")
    
    logger.info(f"Admin {admin_id} switched user {target_user_id} from {current_plan} to {plan_key} plan (preserved {preserved_tokens} tokens)")
    
    return {"message": f"User {target_user_id} switched to {plan_key} plan"}


def test_meter_event_for_user(
    user_id: int,
    value: int,
    admin_id: int,
    db: Session
) -> Dict[str, Any]:
    """Test endpoint to manually send a meter event to Stripe (admin operation)
    
    Args:
        user_id: Target user ID
        value: Number of tokens to report to meter
        admin_id: Admin user ID performing the action
        db: Database session
    
    Returns:
        Dict with test results
    
    Raises:
        ValueError: If user not found, has no subscription, wrong plan type, or no Stripe customer ID
    """
    from app.services.stripe_service import record_token_usage_to_stripe
    from app.services.token_service import get_or_create_token_balance, get_plan_tokens
    
    # Get user's subscription to verify they have a paid plan
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not subscription:
        raise ValueError(f"User {user_id} has no subscription")
    
    if subscription.plan_type in ('free', 'unlimited'):
        raise ValueError(f"User {user_id} is on {subscription.plan_type} plan (meter events only for paid plans)")
    
    if not subscription.stripe_customer_id:
        raise ValueError(f"User {user_id} has no Stripe customer ID")
    
    # Temporarily increase tokens_used_this_period to simulate overage
    # This will make record_token_usage_to_stripe report the value
    balance = get_or_create_token_balance(user_id, db)
    original_used = balance.tokens_used_this_period
    
    # Set tokens_used_this_period to create overage
    included_tokens = get_plan_tokens(subscription.plan_type)
    balance.tokens_used_this_period = included_tokens + value
    db.commit()
    
    # Record the meter event
    success = record_token_usage_to_stripe(user_id, value, db)
    
    # Restore original value
    balance.tokens_used_this_period = original_used
    db.commit()
    
    if not success:
        raise ValueError("Failed to send meter event (check logs for details)")
    
    logger.info(f"Admin {admin_id} sent test meter event for user {user_id}: {value} tokens")
    
    return {
        "success": True,
        "message": f"Sent meter event: {value} tokens for customer {subscription.stripe_customer_id}",
        "customer_id": subscription.stripe_customer_id,
        "value": value,
        "event_name": "hopper_tokens"
    }


def get_webhook_events_list(
    limit: int,
    event_type: Optional[str],
    db: Session
) -> Dict[str, Any]:
    """Get recent Stripe webhook events for debugging
    
    Args:
        limit: Maximum number of events to return
        event_type: Optional event type filter
        db: Database session
    
    Returns:
        Dict with events list and total count
    """
    from sqlalchemy import desc
    from app.models.stripe_event import StripeEvent
    
    query = db.query(StripeEvent)
    
    if event_type:
        query = query.filter(StripeEvent.event_type == event_type)
    
    events = query.order_by(desc(StripeEvent.id)).limit(limit).all()
    
    return {
        "events": [
            {
                "id": e.id,
                "stripe_event_id": e.stripe_event_id,
                "event_type": e.event_type,
                "processed": e.processed,
                "error_message": e.error_message,
            }
            for e in events
        ],
        "total": len(events)
    }


def get_user_token_transactions(
    user_id: int,
    limit: int,
    db: Session
) -> Dict[str, Any]:
    """Get token transaction history for a user (admin operation)
    
    Args:
        user_id: Target user ID
        limit: Maximum number of transactions to return
        db: Database session
    
    Returns:
        Dict with transactions list
    
    Raises:
        ValueError: If user not found
    """
    from app.services.token_service import get_token_transactions
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    
    transactions = get_token_transactions(user_id, limit, db)
    return {"transactions": transactions}

