"""Subscriptions API routes"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.schemas.subscriptions import CheckoutRequest, SwitchPlanRequest
from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.services.stripe_service import (
    create_checkout_session, get_customer_portal_url, get_subscription_info
)
from app.core.config import settings

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


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
        if event_type == "customer.subscription.created":
            # Handle subscription creation
            pass
        elif event_type == "customer.subscription.updated":
            # Handle subscription update
            pass
        elif event_type == "customer.subscription.deleted":
            # Handle subscription deletion
            pass
        
        mark_stripe_event_processed(event["id"], db)
        return {"status": "success"}
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error processing webhook {event['id']}: {e}", exc_info=True)
        mark_stripe_event_processed(event["id"], db, error_message=str(e))
        raise HTTPException(500, "Webhook processing failed")

