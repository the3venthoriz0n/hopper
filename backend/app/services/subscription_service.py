import logging
import json
from typing import Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import stripe

from app.core.config import settings
from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_transaction import TokenTransaction
from app.services.auth_service import get_user_by_id
from app.services.stripe_service import (
    StripeRegistry,
    get_price_info, 
    create_stripe_subscription, 
    cancel_subscription_with_invoice,
    create_checkout_session, 
    get_customer_portal_url, 
    get_subscription_info,
    handle_checkout_completed, 
    handle_subscription_created, 
    handle_subscription_updated,
    handle_subscription_deleted, 
    handle_invoice_payment_succeeded, 
    handle_invoice_payment_failed,
    log_stripe_event, 
    mark_stripe_event_processed
)
from app.services.token_service import (
    get_token_balance, 
    get_or_create_token_balance, 
    ensure_tokens_synced_for_subscription
)

logger = logging.getLogger(__name__)

def list_available_plans() -> Dict:
    """
    List available subscription plans using the StripeRegistry.
    Replaces the previous JSON-based get_plans() call.
    """
    plans_list = []
    # Get all primary plans (those with a '{plan}_price' lookup key)
    base_plans = StripeRegistry.get_all_base_plans()
    
    # Collect and filter plans
    filtered_plans = []
    for plan_key, config in base_plans.items():
        # Skip unlimited plans and hidden plans
        if plan_key == 'unlimited' or config.get('hidden', False):
            continue
            
        # Build plan data using Registry info
        plan_data = {
            "key": plan_key,
            "name": config["name"],
            "description": config.get("description", ""),
            "tokens": config["tokens"],
            "recurring_interval": config.get("recurring_interval", "month"),
            "max_accrual": config.get("max_accrual"),
            "stripe_price_id": config["price_id"],
            "price": {
                "amount": int(config["amount_dollars"] * 100),
                "amount_dollars": config["amount_dollars"],
                "currency": config["currency"],
                "formatted": config["formatted"]
            }
        }
        
        # Check for associated overage price (e.g., 'starter_overage_price')
        overage_config = StripeRegistry.get(f"{plan_key}_overage_price")
        if overage_config:
            plan_data["overage_price"] = {
                "amount": int(overage_config["amount_dollars"] * 100),
                "amount_dollars": overage_config["amount_dollars"],
                "currency": overage_config["currency"],
                "formatted": f"${overage_config['amount_dollars']:.2f}/token"
            }
        else:
            plan_data["overage_price"] = None
            
        filtered_plans.append(plan_data)
    
    # Sort plans by price (cheapest to most expensive)
    plans_list = sorted(filtered_plans, key=lambda x: x["price"]["amount_dollars"])
    
    return {"plans": plans_list}

def check_checkout_status(session_id: str, user_id: int, db: Session) -> Dict:
    """Check the status of a Stripe checkout session and verify if subscription was created."""
    if not settings.STRIPE_SECRET_KEY:
        raise ValueError("Stripe not configured")
    
    session = stripe.checkout.Session.retrieve(session_id)
    
    # Verify ownership
    session_user_id = None
    if session.metadata and session.metadata.get("user_id"):
        session_user_id = int(session.metadata["user_id"])
    
    if session_user_id != user_id:
        raise ValueError("Checkout session does not belong to current user")
    
    if session.payment_status != "paid":
        return {
            "status": "pending",
            "payment_status": session.payment_status,
            "subscription_created": False
        }
    
    subscription_created = False
    subscription_id = None
    if session.mode == "subscription" and session.subscription:
        subscription_id = session.subscription
        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == subscription_id).first()
        if sub:
            subscription_created = True
            ensure_tokens_synced_for_subscription(user_id, subscription_id, db)

    return {
        "status": "completed" if session.payment_status == "paid" else "pending",
        "payment_status": session.payment_status,
        "subscription_created": subscription_created,
        "subscription_id": subscription_id,
        "mode": session.mode
    }

def cancel_user_subscription(user_id: int, db: Session) -> Dict:
    """Cancel the user's subscription and switch to free_daily plan while preserving tokens."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User account no longer exists")
    
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    # Prevent canceling free plans (both 'free' and 'free_daily')
    if not subscription:
        raise ValueError("No active subscription found")
    
    if subscription.plan_type in ('free', 'free_daily'):
        return {
            "status": "error",
            "message": "Cannot cancel free plan. Free plans cannot be canceled.",
            "plan_type": subscription.plan_type
        }
    
    # Capture balance before cancellation
    token_balance = get_or_create_token_balance(user_id, db)
    current_tokens = token_balance.tokens_remaining
    
    # Cancel Stripe side
    if subscription.stripe_subscription_id:
        try:
            cancel_subscription_with_invoice(subscription.stripe_subscription_id, invoice_now=True)
        except Exception as e:
            logger.warning(f"Failed to cancel Stripe sub {subscription.stripe_subscription_id}: {e}")
    
    # Database logic
    db.delete(subscription)
    reset_time = datetime.now(timezone.utc)
    token_balance.last_reset_at = reset_time
    
    # Log preservation transaction
    preserve_transaction = TokenTransaction(
        user_id=user_id,
        transaction_type='reset',
        tokens=0,
        balance_before=current_tokens,
        balance_after=current_tokens,
        transaction_metadata={
            'plan_type': 'free_daily',
            'tokens_preserved': True,
            'preserved_amount': current_tokens,
            'cancel_subscription': True
        }
    )
    db.add(preserve_transaction)
    db.commit()
    
    # Create new free_daily plan
    free_sub = create_stripe_subscription(user_id, "free_daily", db, skip_token_reset=True)
    
    # Restore balance to the new free_daily record
    token_balance = get_or_create_token_balance(user_id, db)
    token_balance.tokens_remaining = current_tokens
    free_daily_config = StripeRegistry.get("free_daily_price")
    token_balance.tokens = max(current_tokens, free_daily_config["tokens"] if free_daily_config else 100)
    token_balance.tokens_used_this_period = 0
    token_balance.period_start = free_sub.current_period_start
    token_balance.period_end = free_sub.current_period_end
    
    db.commit()
    return {
        "status": "success",
        "plan_type": "free_daily",
        "tokens_preserved": current_tokens
    }

def create_subscription_checkout(user_id: int, plan_key: str, frontend_url: str, db: Session) -> Dict[str, Any]:
    """Create Stripe checkout session for subscription using Registry lookup keys."""
    plan_config = StripeRegistry.get(f"{plan_key}_price")
    if not plan_config:
        raise ValueError(f"Invalid plan: {plan_key}")
    
    # Check if user is trying to upgrade to the same plan they already have
    existing_subscription = db.query(Subscription).filter(
        Subscription.user_id == user_id, 
        Subscription.status == 'active'
    ).first()
    
    if existing_subscription and existing_subscription.plan_type == plan_key:
        # User already has this plan, return error
        portal_url = get_customer_portal_url(user_id, f"{frontend_url}/app/subscription", db)
        return {
            "error": f"You already have an active {plan_key} subscription",
            "portal_url": portal_url
        }
    
    # Allow upgrade/downgrade - create_stripe_subscription will handle canceling existing subscriptions
    success_url = f"{frontend_url}/app/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_url}/app/subscription"
    
    return create_checkout_session(
        user_id=user_id,
        plan_type=plan_key,
        success_url=success_url,
        cancel_url=cancel_url,
        db=db
    )

def get_current_subscription_with_auto_repair(user_id: int, db: Session) -> Dict[str, Any]:
    """Get subscription with auto-repair logic."""
    user = get_user_by_id(user_id, db)
    if not user:
        raise ValueError("User account no longer exists")
    
    subscription_info = get_subscription_info(user_id, db)
    if not subscription_info:
        create_stripe_subscription(user_id, "free_daily", db)
        subscription_info = get_subscription_info(user_id, db)
    
    token_balance = get_token_balance(user_id, db)
    return {
        "subscription": subscription_info,
        "token_balance": token_balance,
    }

def process_stripe_webhook(payload: bytes, sig_header: str, db: Session) -> Dict[str, Any]:
    """Process Stripe webhook event with idempotency logging."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ValueError("Webhook secret not configured")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise
    
    stripe_event = log_stripe_event(event["id"], event["type"], event, db)
    if stripe_event.processed:
        return {"status": "already_processed"}
    
    data = event["data"]["object"]
    event_type = event["type"]
    
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
        logger.error(f"Error processing webhook {event['id']}: {e}", exc_info=True)
        mark_stripe_event_processed(event["id"], db, error_message=str(e))
        return {"status": "error_logged", "error": str(e)}