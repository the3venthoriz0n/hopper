"""Admin API routes"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.schemas.auth import CreateUserRequest, SetPasswordRequest
from app.schemas.subscriptions import GrantTokensRequest, DeductTokensRequest, SwitchPlanRequest
from app.core.security import require_auth
from app.db.session import get_db
from app.models.user import User
from app.services.token_service import (
    grant_tokens_admin, deduct_tokens_with_overage_calculation
)
from app.services.admin_service import (
    list_users_with_subscriptions, get_user_details_with_balance, trigger_manual_cleanup,
    create_user_with_admin_flag, reset_user_password_admin,
    enroll_user_unlimited_plan, unenroll_user_unlimited_plan, switch_user_plan,
    test_meter_event_for_user, get_webhook_events_list, get_user_token_transactions
)
from app.services.auth_service import delete_user_account

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
        return create_user_with_admin_flag(request_data.email, request_data.password, request_data.is_admin, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/users/{user_id}/grant-tokens")
async def grant_tokens_endpoint(
    user_id: int,
    request_data: GrantTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Grant tokens to a user (admin only)"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    
    try:
        return await grant_tokens_admin(user_id, request_data.amount, request_data.reason, admin_user.id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/users/{user_id}/deduct-tokens")
async def deduct_tokens_endpoint(
    user_id: int,
    request_data: DeductTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deduct tokens from a user (admin only) - for testing overage pricing"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Token amount must be positive")
    
    try:
        return await deduct_tokens_with_overage_calculation(user_id, request_data.amount, request_data.reason, admin_user.id, db)
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        elif "Could not retrieve" in error_msg:
            raise HTTPException(500, error_msg)
        else:
            raise HTTPException(500, error_msg)


@router.post("/users/{target_user_id}/unlimited-plan")
def enroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Enroll a user in the unlimited plan via Stripe (admin only).
    Cancels all existing subscriptions first to ensure only one subscription exists."""
    try:
        return enroll_user_unlimited_plan(target_user_id, admin_user.id, db)
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(500, error_msg)


@router.delete("/users/{target_user_id}/unlimited-plan")
def unenroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Unenroll a user from the unlimited plan by canceling Stripe subscription (admin only)"""
    try:
        return unenroll_user_unlimited_plan(target_user_id, admin_user.id, db)
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg or "has no subscription" in error_msg:
            raise HTTPException(404, error_msg)
        elif "not on unlimited plan" in error_msg:
            raise HTTPException(400, error_msg)
        else:
            raise HTTPException(500, error_msg)


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
    try:
        return switch_user_plan(target_user_id, request_data.plan_key, admin_user.id, db)
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        elif "Invalid plan" in error_msg:
            raise HTTPException(400, error_msg)
        else:
            raise HTTPException(500, error_msg)


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

    try:
        return reset_user_password_admin(target_user_id, request_data.password, admin_user.id, db)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/test-meter-event/{user_id}")
def test_meter_event(
    user_id: int,
    value: int = Query(1, ge=1, description="Number of tokens to report to meter"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Test endpoint to manually send a meter event to Stripe (admin only)"""
    try:
        return test_meter_event_for_user(user_id, value, admin_user.id, db)
    except ValueError as e:
        error_msg = str(e)
        if "has no subscription" in error_msg:
            raise HTTPException(404, error_msg)
        elif "is on" in error_msg and "plan" in error_msg:
            raise HTTPException(400, error_msg)
        elif "has no Stripe customer ID" in error_msg:
            raise HTTPException(400, error_msg)
        else:
            raise HTTPException(500, error_msg)
    except Exception as e:
        logger.error(f"Error sending test meter event for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Error: {str(e)}")


@router.delete("/users/{target_user_id}")
def delete_user_admin(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a user (admin only). Performs complete account deletion including Stripe subscriptions, files, and all data."""
    # Prevent admin from deleting themselves
    if target_user_id == admin_user.id:
        raise HTTPException(400, "Cannot delete your own account")
    
    try:
        result = delete_user_account(target_user_id, db)
        logger.info(f"Admin {admin_user.id} deleted user: {target_user_id}")
        return result
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(500, error_msg)
    except Exception as e:
        logger.error(f"Error deleting user {target_user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to delete user: {str(e)}")


@router.get("/webhooks/events")
def get_webhook_events(
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = None,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get recent Stripe webhook events for debugging"""
    return get_webhook_events_list(limit, event_type, db)


@router.get("/users/{user_id}/transactions")
def get_user_transactions_admin(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get token transaction history for a user (admin only)"""
    try:
        return get_user_token_transactions(user_id, limit, db)
    except ValueError as e:
        raise HTTPException(404, str(e))


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

