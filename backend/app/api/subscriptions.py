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
    """Get subscription information."""
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
    """Get Stripe customer portal URL."""
    frontend_url = settings.FRONTEND_URL
    return_url = f"{frontend_url}/settings"
    
    portal_url = get_customer_portal_url(user_id, return_url, db)
    if not portal_url:
        raise HTTPException(status_code=500, detail="Failed to create portal session")
    
    return {"url": portal_url}


@router.get("/plans")
def get_subscription_plans():
    """Get available subscription plans dynamically from the Stripe Registry."""
    return list_available_plans()


@router.get("/current")
def get_current_subscription(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get user's current subscription with auto-repair logic."""
    try:
        return get_current_subscription_with_auto_repair(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            # Return 401 instead of 404 to trigger logout in frontend
            raise HTTPException(status_code=401, detail=error_msg)
        else:
            raise HTTPException(status_code=500, detail=error_msg)


@router.post("/create-checkout")
def create_subscription_checkout_route(
    checkout_request: CheckoutRequest,
    request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription using lookup keys."""
    frontend_url = settings.FRONTEND_URL or str(request.base_url).rstrip("/")
    
    try:
        result = create_subscription_checkout(
            user_id,
            checkout_request.plan_key,
            frontend_url,
            db
        )
        # Handle 400 cases (e.g., user already has a subscription)
        if isinstance(result, dict) and "error" in result:
            return JSONResponse(
                status_code=400,
                content=result
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating checkout session for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.get("/checkout-status")
async def check_checkout_status_route(
    session_id: str = Query(..., description="Stripe checkout session ID"),
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Check the status of a Stripe checkout session."""
    try:
        return await check_checkout_status(session_id, user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "not configured" in error_msg.lower():
            raise HTTPException(status_code=500, detail=error_msg)
        elif "does not belong" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Error checking checkout session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error checking checkout session")


@router.post("/cancel")
def cancel_subscription(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Cancel subscription and switch to free plan while preserving tokens."""
    try:
        return cancel_user_subscription(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            raise HTTPException(status_code=401, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            raise HTTPException(status_code=500, detail=error_msg)


@router.post("/switch-to-free")
def switch_to_free_plan(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Alias for cancel subscription."""
    try:
        return cancel_user_subscription(user_id, db)
    except ValueError as e:
        error_msg = str(e)
        if "no longer exists" in error_msg.lower():
            raise HTTPException(status_code=401, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            raise HTTPException(status_code=500, detail=error_msg)


# ============================================================================
# STRIPE WEBHOOK & CONFIG ROUTER
# ============================================================================

stripe_router = APIRouter(prefix="/api/stripe", tags=["stripe"])


@stripe_router.post("/webhook")
async def stripe_webhook_endpoint(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events. Must receive raw bytes for signature."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
    
    try:
        return await process_stripe_webhook(payload, sig_header, db)
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        # Return 200/success to prevent Stripe from retrying infinitely
        return {"status": "error", "message": "Webhook processing failed"}


@stripe_router.get("/config")
def get_stripe_config():
    """Get Stripe publishable key and pricing table ID."""
    pricing_table_id = os.getenv("STRIPE_PRICING_TABLE_ID", "")
    publishable_key = settings.STRIPE_PUBLISHABLE_KEY
    
    if not publishable_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    return {
        "publishable_key": publishable_key,
        "pricing_table_id": pricing_table_id
    }