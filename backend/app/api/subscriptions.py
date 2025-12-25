"""Subscriptions API routes"""
import logging
import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.schemas.subscriptions import CheckoutRequest, SwitchPlanRequest
from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.services.stripe_service import get_customer_portal_url, get_subscription_info
from app.services.subscription_service import (
    list_available_plans, check_checkout_status, cancel_user_subscription,
    create_subscription_checkout, get_current_subscription_with_auto_repair,
    process_stripe_webhook
)
from app.core.config import settings

router = APIRouter(prefix="/api/subscription", tags=["subscriptions"])
logger = logging.getLogger(__name__)




@router.get("/info")
def get_subscription(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get subscription information"""
    info = get_subscription_info(user_id, db)
    if not info:
        return {"subscription": None}
    return {"subscription": info}


@router.get("/portal")
def get_portal_url(
    request: Request,
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get Stripe customer portal URL"""
    frontend_url = settings.FRONTEND_URL
    return_url = f"{frontend_url}/settings"
    
    portal_url = get_customer_portal_url(user_id, return_url, db)
    if not portal_url:
        raise HTTPException(500, "Failed to create portal session")
    
    return {"url": portal_url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events
    
    Note: This route must be excluded from any global JSON parsing middleware
    to ensure the request body remains as raw bytes for signature verification.
    """
    # Read body as raw bytes (critical for signature verification)
    # Middleware must not parse JSON before this point
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")
    
    try:
        result = process_stripe_webhook(payload, sig_header, db)
        return result
    except ValueError as e:
        # Invalid payload
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(400, str(e))
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        logger.error(f"Invalid webhook signature: {e}")
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        # Unexpected error - log but return 200 to prevent retries
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        return {"status": "error", "message": "Webhook processing failed"}


# Additional subscription routes (legacy endpoints for compatibility)
@router.get("/plans")
def get_subscription_plans():
    """Get available subscription plans (excludes hidden/dev-only plans)"""
    return list_available_plans()


@router.get("/current")
def get_current_subscription(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get user's current subscription.
    
    This is a lightweight GET endpoint that returns current state.
    Subscription syncing is handled by:
    - Webhooks (primary mechanism)
    - Background scheduler (periodic sync for missed webhooks)
    
    Auto-repairs missing subscriptions by creating a free subscription.
    """
    try:
        return get_current_subscription_with_auto_repair(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            # Return 401 instead of 404 to trigger logout in frontend
            # This happens when a user was deleted but their session is still active
            raise HTTPException(401, error_msg)
        else:
            raise HTTPException(500, error_msg)


@router.post("/create-checkout")
def create_subscription_checkout_route(
    checkout_request: CheckoutRequest,
    request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription"""
    # Get frontend URL from environment or request
    frontend_url = settings.FRONTEND_URL or str(request.base_url).rstrip("/")
    
    try:
        result = create_subscription_checkout(
            user_id,
            checkout_request.plan_key,
            frontend_url,
            db
        )
        # Check if result contains error (user already has subscription)
        if isinstance(result, dict) and "error" in result:
            return JSONResponse(
                status_code=400,
                content=result
            )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Error creating checkout session for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create checkout session")


@router.get("/checkout-status")
def check_checkout_status_route(
    session_id: str = Query(..., description="Stripe checkout session ID"),
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """
    Check the status of a Stripe checkout session and verify if subscription was created.
    This endpoint allows the frontend to verify payment completion without polling subscription state.
    """
    try:
        return check_checkout_status(session_id, user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "not configured" in error_msg.lower():
            raise HTTPException(500, error_msg)
        elif "does not belong" in error_msg.lower():
            raise HTTPException(403, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Error checking checkout session {session_id}: {e}", exc_info=True)
        raise HTTPException(500, "Error checking checkout session")


@router.post("/cancel")
def cancel_subscription(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Cancel the user's subscription and switch to free plan.
    Cancels the Stripe subscription immediately and creates a new free Stripe subscription.
    Preserves the user's current token balance.
    """
    try:
        return cancel_user_subscription(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            raise HTTPException(401, error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(500, error_msg)


@router.post("/switch-to-free")
def switch_to_free_plan(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Switch user to free plan (alias for cancel subscription).
    This is the same as canceling the subscription.
    """
    try:
        return cancel_user_subscription(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            raise HTTPException(401, error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(500, error_msg)


# ============================================================================
# STRIPE CONFIG ROUTE (separate router for /api/stripe)
# ============================================================================

stripe_router = APIRouter(prefix="/api/stripe", tags=["stripe"])


@stripe_router.get("/config")
def get_stripe_config():
    """Get Stripe publishable key and pricing table ID for frontend"""
    # Get pricing table ID from environment variable
    pricing_table_id = os.getenv("STRIPE_PRICING_TABLE_ID", "")
    
    publishable_key = settings.STRIPE_PUBLISHABLE_KEY
    if not publishable_key:
        raise HTTPException(500, "Stripe not configured")
    
    # Log warning if pricing table ID is not set (for debugging)
    if not pricing_table_id:
        logger.warning("STRIPE_PRICING_TABLE_ID not set in environment variables")
    
    return {
        "publishable_key": publishable_key,
        "pricing_table_id": pricing_table_id
    }

