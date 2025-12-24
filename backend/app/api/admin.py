"""Admin API routes"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.schemas.auth import CreateUserRequest, SetPasswordRequest
from app.schemas.subscriptions import GrantTokensRequest, DeductTokensRequest, SwitchPlanRequest
from app.core.security import require_auth
from app.db.session import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.models.stripe_event import StripeEvent
from app.models.token_transaction import TokenTransaction
from app.services.auth_service import create_user, set_user_password
from app.services.token_service import (
    add_tokens, deduct_tokens, get_token_balance, get_token_transactions,
    get_or_create_token_balance
)
from app.services.stripe_service import (
    create_free_subscription, create_stripe_customer, record_token_usage_to_stripe,
    get_plans, get_plan_monthly_tokens, get_plan_price_id, cancel_subscription_with_invoice
)
from app.services.video_service import cleanup_video_file
from app.services.admin_service import (
    list_users_with_subscriptions, get_user_details_with_balance, trigger_manual_cleanup
)
from app.models.video import Video
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def require_admin(user_id: int = Depends(require_auth), db: Session = Depends(get_db)) -> User:
    """Dependency: Require admin role"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


def require_admin_get(request: Request, user_id: int = Depends(require_auth), db: Session = Depends(get_db)) -> User:
    """Dependency: Require admin role (for GET requests - no CSRF required)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


@router.post("/users")
def create_user_endpoint(
    request_data: CreateUserRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)"""
    try:
        user = create_user(request_data.email, request_data.password, db=db)
        if request_data.is_admin:
            user.is_admin = True
            db.commit()
        return {"user": {"id": user.id, "email": user.email}}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/users/{user_id}/grant-tokens")
def grant_tokens_endpoint(
    user_id: int,
    request_data: GrantTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Grant tokens to a user (admin only)"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    
    if not add_tokens(user_id, request_data.amount, transaction_type='grant', metadata={'reason': request_data.reason}, db=db):
        raise HTTPException(404, "User not found")
    
    return {"message": f"Granted {request_data.amount} tokens to user {user_id}"}


@router.post("/users/{user_id}/deduct-tokens")
def deduct_tokens_endpoint(
    user_id: int,
    request_data: DeductTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deduct tokens from a user (admin only) - for testing overage pricing"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Token amount must be positive")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    # Get balance before deduction
    balance_before = get_token_balance(user_id, db)
    if not balance_before:
        raise HTTPException(500, "Could not retrieve user token balance")
    
    # Get subscription info to determine included tokens
    # Use monthly_tokens from balance (actual starting balance) not base plan amount
    # This accounts for preserved/granted tokens when user upgrades
    balance = get_or_create_token_balance(user_id, db)
    included_tokens = balance.monthly_tokens if balance.monthly_tokens > 0 else 0
    
    # Fallback to plan amount if monthly_tokens not set
    if included_tokens == 0:
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        included_tokens = get_plan_monthly_tokens(subscription.plan_type) if subscription else 0
    
    # Calculate if this will trigger overage
    tokens_used_before = balance_before.get('tokens_used_this_period', 0)
    tokens_used_after = tokens_used_before + request_data.amount
    overage_before = max(0, tokens_used_before - included_tokens)
    overage_after = max(0, tokens_used_after - included_tokens)
    new_overage = overage_after - overage_before
    
    # Deduct tokens using the standard function (this will trigger meter events if overage)
    success = deduct_tokens(
        user_id=user_id,
        tokens=request_data.amount,
        transaction_type='admin_test',
        metadata={
            'admin_id': admin_user.id,
            'reason': request_data.reason or 'admin_test',
            'test_overage': new_overage > 0
        },
        db=db
    )
    
    if not success:
        raise HTTPException(500, "Failed to deduct tokens")
    
    # Get balance after deduction
    balance_after = get_token_balance(user_id, db)
    
    logger.info(f"Admin {admin_user.id} deducted {request_data.amount} tokens from user {user_id} (overage: {new_overage})")
    return {
        "message": f"Deducted {request_data.amount} tokens from user {user_id}",
        "balance_before": balance_before,
        "balance_after": balance_after,
        "overage_triggered": new_overage > 0,
        "new_overage": new_overage
    }


@router.post("/users/{target_user_id}/unlimited-plan")
def enroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Enroll a user in the unlimited plan via Stripe (admin only).
    Cancels all existing subscriptions first to ensure only one subscription exists."""
    from app.services.stripe_service import cancel_all_user_subscriptions, create_unlimited_subscription
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    # Check if user already has unlimited plan
    existing_subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    if existing_subscription and existing_subscription.plan_type == 'unlimited':
        return {"message": f"User {target_user_id} already has unlimited plan"}
    
    # Preserve current token balance before canceling subscriptions and enrolling in unlimited
    token_balance = get_or_create_token_balance(target_user_id, db)
    preserved_tokens = token_balance.tokens_remaining
    
    # Cancel all existing subscriptions first to ensure only one subscription exists
    cancel_all_user_subscriptions(target_user_id, db)
    
    # Create unlimited subscription via Stripe
    subscription = create_unlimited_subscription(target_user_id, preserved_tokens, db)
    
    if not subscription:
        raise HTTPException(500, "Failed to create unlimited subscription")
    
    logger.info(f"Admin {admin_user.id} enrolled user {target_user_id} in unlimited plan (preserved {preserved_tokens} tokens)")
    
    return {"message": f"User {target_user_id} enrolled in unlimited plan"}


@router.delete("/users/{target_user_id}/unlimited-plan")
def unenroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Unenroll a user from the unlimited plan by canceling Stripe subscription (admin only)"""
    import stripe
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    if not subscription:
        raise HTTPException(404, "User has no subscription")
    
    if subscription.plan_type != 'unlimited':
        raise HTTPException(400, f"User is not on unlimited plan (current: {subscription.plan_type})")
    
    # Get preserved token balance before canceling subscriptions
    preserved_tokens = subscription.preserved_tokens_balance if subscription.preserved_tokens_balance is not None else 0
    
    # Set balance to preserved_tokens before creating free subscription
    # This ensures that when create_free_subscription adds free plan tokens,
    # we can then set it back to just preserved_tokens (without the free plan tokens)
    token_balance = get_or_create_token_balance(target_user_id, db)
    token_balance.tokens_remaining = preserved_tokens
    db.commit()
    
    # Cancel all existing subscriptions and create free subscription
    # create_free_subscription will handle canceling all subscriptions (including this one)
    # and ensure only one subscription exists
    try:
        free_subscription = create_free_subscription(target_user_id, db)
        if not free_subscription:
            # Check if there are still active subscriptions preventing creation
            if target_user.stripe_customer_id:
                try:
                    remaining_active = stripe.Subscription.list(
                        customer=target_user.stripe_customer_id,
                        status='active',
                        limit=100
                    )
                    if len(remaining_active.data) > 0:
                        raise HTTPException(
                            400, 
                            f"Cannot unenroll: User still has {len(remaining_active.data)} active subscription(s) "
                            f"that could not be canceled. Subscription IDs: {[s.id for s in remaining_active.data]}. "
                            f"Please try again or contact support."
                        )
                except Exception as e:
                    logger.error(f"Error checking remaining subscriptions: {e}")
            
            raise HTTPException(500, "Failed to create free subscription. Please try again or contact support.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unenrolling user {target_user_id} from unlimited plan: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to unenroll from unlimited plan: {str(e)}")
    
    # After create_free_subscription, reset_tokens_for_subscription was called which:
    # - Added free plan tokens to preserved_tokens (10 + 10 = 20)
    # - Set monthly_tokens to the new total (20)
    # We want the final balance to be just preserved_tokens (not preserved_tokens + free_plan_tokens)
    # So we set both tokens_remaining and monthly_tokens to preserved_tokens
    token_balance = get_or_create_token_balance(target_user_id, db)
    free_plan_tokens = get_plan_monthly_tokens('free')
    
    # Set tokens_remaining to preserved_tokens
    token_balance.tokens_remaining = preserved_tokens
    
    # Set monthly_tokens to preserved_tokens (or free plan tokens if preserved is less)
    # This ensures the counter shows the correct starting balance
    token_balance.monthly_tokens = max(preserved_tokens, free_plan_tokens)
    
    # Ensure tokens_used_this_period is 0 (fresh start on free plan)
    token_balance.tokens_used_this_period = 0
    
    db.commit()
    
    logger.info(
        f"Set token balance after unenroll: tokens_remaining={token_balance.tokens_remaining}, "
        f"monthly_tokens={token_balance.monthly_tokens}, preserved_tokens={preserved_tokens}"
    )
    
    logger.info(
        f"Admin {admin_user.id} unenrolled user {target_user_id} from unlimited plan "
        f"(restored {preserved_tokens} preserved tokens, moved to free plan without adding free plan tokens)"
    )
    
    return {"message": f"User {target_user_id} unenrolled from unlimited plan"}


@router.post("/users/{target_user_id}/switch-plan")
def admin_switch_user_plan(
    target_user_id: int,
    request_data: SwitchPlanRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Switch a user to a different plan (admin only).
    
    Cancels existing subscription with final invoice for overage, then creates new subscription.
    Preserves tokens (user paid for full period, no prorating).
    """
    import stripe
    from app.services.stripe_service import (
        cancel_all_user_subscriptions, create_free_subscription, create_unlimited_subscription
    )
    from app.services.token_service import reset_tokens_for_subscription
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    plan_key = request_data.plan_key.lower()
    plans = get_plans()
    
    # Validate plan key
    if plan_key not in plans:
        raise HTTPException(400, f"Invalid plan: {plan_key}. Valid plans: {', '.join(plans.keys())}")
    
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
    if plan_key == 'free':
        # Create free subscription (skip token reset - we'll preserve tokens)
        new_subscription = create_free_subscription(target_user_id, db, skip_token_reset=True)
        if new_subscription:
            # Preserve tokens and set monthly_tokens correctly
            free_plan_tokens = get_plan_monthly_tokens('free')
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
        new_subscription = create_unlimited_subscription(target_user_id, preserved_tokens, db)
    else:
        # Create paid subscription via Stripe
        price_id = get_plan_price_id(plan_key)
        if not price_id:
            raise HTTPException(400, f"Plan {plan_key} is not configured with a Stripe price")
        
        # Create subscription in Stripe
        customer_id = target_user.stripe_customer_id
        if not customer_id:
            customer_id = create_stripe_customer(target_user.email, target_user_id, db)
            if not customer_id:
                raise HTTPException(500, "Failed to create Stripe customer")
        
        stripe_subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            metadata={'user_id': str(target_user_id)},
        )
        
        # Create subscription record in database
        new_subscription = Subscription(
            user_id=target_user_id,
            stripe_subscription_id=stripe_subscription.id,
            stripe_customer_id=customer_id,
            plan_type=plan_key,
            status=stripe_subscription.status,
            current_period_start=datetime.fromtimestamp(stripe_subscription.current_period_start, tz=timezone.utc),
            current_period_end=datetime.fromtimestamp(stripe_subscription.current_period_end, tz=timezone.utc),
            cancel_at_period_end=False,
        )
        db.add(new_subscription)
        db.commit()
        db.refresh(new_subscription)
        
        # Reset tokens for new subscription (preserve existing tokens)
        reset_tokens_for_subscription(
            target_user_id,
            plan_key,
            new_subscription.current_period_start,
            new_subscription.current_period_end,
            db,
            is_renewal=False
        )
        
        # Preserve tokens
        token_balance = get_or_create_token_balance(target_user_id, db)
        plan_tokens = get_plan_monthly_tokens(plan_key)
        token_balance.tokens_remaining = preserved_tokens
        token_balance.monthly_tokens = max(preserved_tokens, plan_tokens)
        token_balance.tokens_used_this_period = 0
        db.commit()
    
    if not new_subscription:
        raise HTTPException(500, f"Failed to create {plan_key} subscription")
    
    logger.info(f"Admin {admin_user.id} switched user {target_user_id} from {current_plan} to {plan_key} plan (preserved {preserved_tokens} tokens)")
    
    return {"message": f"User {target_user_id} switched to {plan_key} plan"}


@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """List users with basic info (admin only)"""
    return list_users_with_subscriptions(page, limit, search, db)


@router.get("/users/{user_id}")
def get_user_details(
    user_id: int,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get detailed user information (admin only)"""
    try:
        return get_user_details_with_balance(user_id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/users/{target_user_id}/reset-password")
def admin_reset_user_password(
    target_user_id: int,
    request_data: SetPasswordRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Reset a user's password (admin only).

    This uses the same password validation as the self-service set-password endpoint
    and allows admins (including resetting their own password) to help users regain access
    without exposing existing hashes.
    """
    # Basic password validation
    if len(request_data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")

    success = set_user_password(target_user_id, request_data.password, db=db)
    if not success:
        raise HTTPException(404, "User not found")

    logger.info(f"Admin {admin_user.id} reset password for user {target_user_id}")
    return {"message": "Password reset successfully"}


@router.post("/test-meter-event/{user_id}")
def test_meter_event(
    user_id: int,
    value: int = Query(1, ge=1, description="Number of tokens to report to meter"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Test endpoint to manually send a meter event to Stripe (admin only)"""
    try:
        # Get user's subscription to verify they have a paid plan
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if not subscription:
            raise HTTPException(404, f"User {user_id} has no subscription")
        
        if subscription.plan_type in ('free', 'unlimited'):
            raise HTTPException(400, f"User {user_id} is on {subscription.plan_type} plan (meter events only for paid plans)")
        
        if not subscription.stripe_customer_id:
            raise HTTPException(400, f"User {user_id} has no Stripe customer ID")
        
        # Temporarily increase tokens_used_this_period to simulate overage
        # This will make record_token_usage_to_stripe report the value
        balance = get_or_create_token_balance(user_id, db)
        original_used = balance.tokens_used_this_period
        
        # Set tokens_used_this_period to create overage
        included_tokens = get_plan_monthly_tokens(subscription.plan_type)
        balance.tokens_used_this_period = included_tokens + value
        db.commit()
        
        # Record the meter event
        success = record_token_usage_to_stripe(user_id, value, db)
        
        # Restore original value
        balance.tokens_used_this_period = original_used
        db.commit()
        
        if success:
            logger.info(f"Admin {admin_user.id} sent test meter event for user {user_id}: {value} tokens")
            return {
                "success": True,
                "message": f"Sent meter event: {value} tokens for customer {subscription.stripe_customer_id}",
                "customer_id": subscription.stripe_customer_id,
                "value": value,
                "event_name": "hopper_tokens"
            }
        else:
            raise HTTPException(500, "Failed to send meter event (check logs for details)")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test meter event for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Error: {str(e)}")


@router.delete("/users/{target_user_id}")
def delete_user_admin(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a user (admin only). Deletes Stripe customer (which automatically cancels all subscriptions) before deletion."""
    from app.services.stripe_service import delete_stripe_customer
    
    # Prevent admin from deleting themselves
    if target_user_id == admin_user.id:
        raise HTTPException(400, "Cannot delete your own account")
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    user_email = target_user.email
    
    try:
        # Delete Stripe customer if it exists
        # Note: Deleting a Stripe customer automatically cancels all their subscriptions
        if target_user.stripe_customer_id:
            delete_stripe_customer(target_user.stripe_customer_id, user_id=target_user_id)
        
        # Delete user (cascade will handle related records including subscription)
        db.delete(target_user)
        db.commit()
        
        logger.info(f"Admin {admin_user.id} deleted user: {user_email} (ID: {target_user_id})")
        
        return {"message": f"User {user_email} deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting user {target_user_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(500, "Failed to delete user")


@router.get("/webhooks/events")
def get_webhook_events(
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = None,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get recent Stripe webhook events for debugging"""
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


@router.get("/users/{user_id}/transactions")
def get_user_transactions_admin(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get token transaction history for a user (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    transactions = get_token_transactions(user_id, limit, db)
    return {"transactions": transactions}


@router.post("/cleanup")
async def manual_cleanup(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Manually trigger cleanup of old and orphaned files
    
    This endpoint allows users to clean up their own old uploaded videos.
    Removes video files for videos uploaded more than 24 hours ago.
    """
    try:
        return trigger_manual_cleanup(user_id, db)
    except Exception as e:
        cleanup_logger = logging.getLogger("cleanup")
        cleanup_logger.error(f"Error in manual cleanup for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Cleanup failed: {str(e)}")

