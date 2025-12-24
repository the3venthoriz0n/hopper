"""Subscriptions API routes"""
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.schemas.subscriptions import CheckoutRequest, SwitchPlanRequest
from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.services.stripe_service import (
    create_checkout_session, get_customer_portal_url, get_subscription_info,
    get_plans, get_price_info, get_plan_price_id, get_plan_overage_price_id,
    get_plan_monthly_tokens, create_free_subscription,
    handle_checkout_completed, handle_subscription_created, handle_subscription_updated,
    handle_subscription_deleted, handle_invoice_payment_succeeded, handle_invoice_payment_failed
)
from app.services.subscription_service import (
    list_available_plans, check_checkout_status, cancel_user_subscription
)
from app.services.token_service import (
    get_token_balance, get_or_create_token_balance, ensure_tokens_synced_for_subscription
)
from app.core.config import settings

router = APIRouter(prefix="/api/subscription", tags=["subscriptions"])
logger = logging.getLogger(__name__)


@router.post("/checkout")
def create_checkout(
    request_data: CheckoutRequest,
    request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session"""
    from app.services.stripe_service import get_plan_price_id
    
    price_id = get_plan_price_id(request_data.plan_key)
    if not price_id:
        raise HTTPException(400, f"Invalid plan: {request_data.plan_key}")
    
    frontend_url = settings.FRONTEND_URL
    success_url = f"{frontend_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_url}/subscription/cancel"
    
    result = create_checkout_session(user_id, price_id, success_url, cancel_url, db)
    if not result:
        raise HTTPException(500, "Failed to create checkout session")
    
    return result


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
    """Handle Stripe webhook events"""
    import json
    from app.services.stripe_service import log_stripe_event, mark_stripe_event_processed
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Webhook secret not configured")
    
    try:
        import stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(400, "Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    
    # Log event for idempotency
    stripe_event = log_stripe_event(
        event["id"],
        event["type"],
        event,
        db
    )
    
    if stripe_event.processed:
        return {"status": "already_processed"}
    
    # Handle different event types
    event_type = event["type"]
    data = event["data"]["object"]
    
    try:
        if event_type == "checkout.session.completed":
            handle_checkout_completed(data, db)
        elif event_type == "customer.subscription.created":
            handle_subscription_created(data, db)
        elif event_type == "customer.subscription.updated":
            handle_subscription_updated(data, db)
        elif event_type == "customer.subscription.deleted":
            handle_subscription_deleted(data, db)
        elif event_type == "invoice.payment_succeeded":
            handle_invoice_payment_succeeded(data, db)
        elif event_type == "invoice.payment_failed":
            handle_invoice_payment_failed(data, db)
        
        mark_stripe_event_processed(event["id"], db)
        return {"status": "success"}
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error processing webhook {event['id']}: {e}", exc_info=True)
        mark_stripe_event_processed(event["id"], db, error_message=str(e))
        raise HTTPException(500, "Webhook processing failed")


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
    """
    # Verify user still exists (may have been deleted after authentication)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"Subscription request for deleted user {user_id}")
        # Return 401 instead of 404 to trigger logout in frontend
        # This happens when a user was deleted but their session is still active
        raise HTTPException(401, "User account no longer exists")
    
    subscription_info = get_subscription_info(user_id, db)
    
    # If user doesn't have a subscription, create a free one
    if not subscription_info:
        logger.info(f"User {user_id} has no subscription, creating free subscription")
        free_sub = create_free_subscription(user_id, db)
        if free_sub:
            subscription_info = get_subscription_info(user_id, db)
        else:
            # If creation fails, return a default response
            # Note: create_free_subscription already logs the error, including if user doesn't exist
            logger.error(f"Failed to create free subscription for user {user_id}")
            return {
                "subscription": None,
                "token_balance": {
                    "tokens_remaining": 0,
                    "tokens_used_this_period": 0,
                    "monthly_tokens": 10,  # Default to free plan
                    "overage_tokens": 0,
                    "unlimited": False,
                    "period_start": None,
                    "period_end": None,
                }
            }
    
    token_balance = get_token_balance(user_id, db)
    
    return {
        "subscription": subscription_info,
        "token_balance": token_balance,
    }


@router.post("/create-checkout")
def create_subscription_checkout(
    checkout_request: CheckoutRequest,
    request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription"""
    plan_key = checkout_request.plan_key
    plans = get_plans()
    if plan_key not in plans:
        raise HTTPException(400, f"Invalid plan: {plan_key}")
    
    plan = plans[plan_key]
    if not plan.get("stripe_price_id"):
        raise HTTPException(400, f"Plan {plan_key} is not configured with a Stripe price")
    
    # Check if user already has an active paid subscription
    existing_subscription = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active'
    ).first()
    
    # Determine if we should cancel existing subscription (upgrade/change scenario)
    cancel_existing = False
    if existing_subscription:
        # If user has a paid subscription (not free/unlimited), allow upgrade/change by canceling existing
        if existing_subscription.stripe_subscription_id and not existing_subscription.stripe_subscription_id.startswith(('free_', 'unlimited_')):
            # Always allow changing plans - cancel existing and create new
            cancel_existing = True
            current_plan = plans.get(existing_subscription.plan_type, {})
            new_plan = plan
            current_tokens = current_plan.get('monthly_tokens', 0)
            new_tokens = new_plan.get('monthly_tokens', 0)
            logger.info(f"User {user_id} changing from {existing_subscription.plan_type} ({current_tokens} tokens) to {plan_key} ({new_tokens} tokens)")
    
    # Get frontend URL from environment or request
    frontend_url = settings.FRONTEND_URL or str(request.base_url).rstrip("/")
    success_url = f"{frontend_url}/app/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_url}/app/subscription"
    
    try:
        session_data = create_checkout_session(user_id, plan["stripe_price_id"], success_url, cancel_url, db, cancel_existing=cancel_existing)
        
        if not session_data:
            raise HTTPException(500, "Failed to create checkout session")
        
        return session_data
    except ValueError as e:
        # User already has subscription (caught by create_checkout_session)
        frontend_url = settings.FRONTEND_URL or str(request.base_url).rstrip("/")
        portal_url = get_customer_portal_url(user_id, f"{frontend_url}/app/subscription", db)
        if portal_url:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "User already has an active subscription",
                    "message": str(e),
                    "portal_url": portal_url
                }
            )
        else:
            raise HTTPException(400, str(e))


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

