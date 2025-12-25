"""Subscription service - Subscription management and business logic"""
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
    get_plans, get_price_info, get_plan_monthly_tokens, get_plan_price_id,
    create_free_subscription, cancel_subscription_with_invoice,
    create_checkout_session, get_customer_portal_url, get_subscription_info,
    handle_checkout_completed, handle_subscription_created, handle_subscription_updated,
    handle_subscription_deleted, handle_invoice_payment_succeeded, handle_invoice_payment_failed,
    log_stripe_event, mark_stripe_event_processed
)
from app.services.token_service import (
    get_token_balance, get_or_create_token_balance, ensure_tokens_synced_for_subscription
)

logger = logging.getLogger(__name__)


def list_available_plans() -> Dict:
    """List available subscription plans with price formatting
    
    Returns:
        Dict with 'plans' list containing plan data with prices
    """
    plans_list = []
    PLANS = get_plans()  # Get plans from JSON config
    for plan_key, plan_config in PLANS.items():
        if plan_config.get("hidden", False):
            continue
        
        plan_data = {
            "key": plan_key,
            "name": plan_config["name"],
            "monthly_tokens": plan_config["monthly_tokens"],
            "stripe_price_id": plan_config.get("stripe_price_id"),
        }
        
        # Get price information from Stripe if price_id exists
        price_id = plan_config.get("stripe_price_id")
        if price_id:
            price_info = get_price_info(price_id)
            if price_info:
                plan_data["price"] = price_info
            else:
                # If we can't get price info, set to free for free plan, or None for others
                if plan_key == 'free':
                    plan_data["price"] = {
                        "amount": 0,
                        "amount_dollars": 0,
                        "currency": "USD",
                        "formatted": "Free"
                    }
                else:
                    plan_data["price"] = None
        elif plan_key == 'free':
            # Free plan doesn't have a Stripe price
            plan_data["price"] = {
                "amount": 0,
                "amount_dollars": 0,
                "currency": "USD",
                "formatted": "Free"
            }
        else:
            plan_data["price"] = None
        
        # Get overage price information if overage_price_id exists
        overage_price_id = plan_config.get("stripe_overage_price_id")
        if overage_price_id:
            overage_price_info = get_price_info(overage_price_id)
            if overage_price_info:
                # Format as per-token price (remove /month suffix, add /token)
                overage_amount_dollars = overage_price_info["amount_dollars"]
                plan_data["overage_price"] = {
                    "amount": overage_price_info["amount"],
                    "amount_dollars": overage_amount_dollars,
                    "currency": overage_price_info["currency"],
                    "formatted": f"${overage_amount_dollars:.2f}/token"
                }
            else:
                plan_data["overage_price"] = None
        else:
            plan_data["overage_price"] = None
        
        plans_list.append(plan_data)
    
    return {"plans": plans_list}


def check_checkout_status(
    session_id: str,
    user_id: int,
    db: Session
) -> Dict:
    """Check the status of a Stripe checkout session and verify if subscription was created
    
    Args:
        session_id: Stripe checkout session ID
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with checkout status information
    
    Raises:
        ValueError: If Stripe not configured or session doesn't belong to user
        Exception: For Stripe API errors
    """
    if not settings.STRIPE_SECRET_KEY:
        raise ValueError("Stripe not configured")
    
    # Retrieve checkout session from Stripe
    session = stripe.checkout.Session.retrieve(session_id)
    
    # Verify this session belongs to the current user
    session_user_id = None
    if session.metadata and session.metadata.get("user_id"):
        session_user_id = int(session.metadata["user_id"])
    elif session.customer:
        # Fallback: check if customer matches current user
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.stripe_customer_id == session.customer:
            session_user_id = user_id
    
    if session_user_id != user_id:
        raise ValueError("Checkout session does not belong to current user")
    
    # Check session status
    if session.payment_status != "paid":
        return {
            "status": "pending",
            "payment_status": session.payment_status,
            "subscription_created": False
        }
    
    # If subscription mode, check if subscription exists
    # Note: We do NOT create/update subscriptions here - that's handled by webhook events
    # This endpoint only checks status and resets tokens if subscription exists and period doesn't match
    subscription_created = False
    subscription_id = None
    if session.mode == "subscription" and session.subscription:
        subscription_id = session.subscription
        # Check if subscription exists in our database
        sub = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription_id
        ).first()
        
        if sub:
            subscription_created = True
            # Ensure tokens are synced for this subscription (idempotent)
            # This handles cases where tokens weren't reset by webhook
            ensure_tokens_synced_for_subscription(user_id, subscription_id, db)
        else:
            # Subscription doesn't exist in database - check if it's invalid in Stripe
            try:
                # Use SubscriptionItem.list() for reliable items checking (more reliable than expand)
                sub_items = stripe.SubscriptionItem.list(
                    subscription=subscription_id,
                    limit=100
                )
                items_count = len(sub_items.data) if sub_items.data else 0
                
                if items_count == 0:
                    # Also retrieve subscription for status/customer info
                    try:
                        stripe_sub = stripe.Subscription.retrieve(subscription_id)
                        logger.error(
                            f"Subscription {subscription_id} exists in Stripe but has NO ITEMS. "
                            f"This subscription is invalid and cannot be processed. "
                            f"Status: {stripe_sub.status}, Customer: {stripe_sub.customer if hasattr(stripe_sub, 'customer') else 'unknown'}"
                        )
                    except stripe.error.StripeError:
                        logger.error(
                            f"Subscription {subscription_id} exists in Stripe but has NO ITEMS. "
                            f"This subscription is invalid and cannot be processed."
                        )
                else:
                    # Subscription has items but not in database - webhook may not have fired yet
                    try:
                        stripe_sub = stripe.Subscription.retrieve(subscription_id)
                        logger.warning(
                            f"Subscription {subscription_id} exists in Stripe with {items_count} item(s) but not in database. "
                            f"Webhook may not have fired yet or failed. Status: {stripe_sub.status}"
                        )
                    except stripe.error.StripeError:
                        logger.warning(
                            f"Subscription {subscription_id} exists in Stripe with {items_count} item(s) but not in database. "
                            f"Webhook may not have fired yet or failed."
                        )
            except stripe.error.StripeError as e:
                logger.warning(
                    f"Subscription {subscription_id} not found in database and could not be retrieved from Stripe: {e}. "
                    f"Webhook may not have fired yet or subscription was deleted."
                )
    
    return {
        "status": "completed" if session.payment_status == "paid" else "pending",
        "payment_status": session.payment_status,
        "subscription_created": subscription_created,
        "subscription_id": subscription_id,
        "mode": session.mode
    }


def cancel_user_subscription(
    user_id: int,
    db: Session
) -> Dict:
    """Cancel the user's subscription and switch to free plan
    
    Cancels the Stripe subscription immediately and creates a new free Stripe subscription.
    Preserves the user's current token balance.
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with cancellation status and preserved tokens
    
    Raises:
        ValueError: If user not found, no subscription, or creation failed
    """
    # Verify user still exists (may have been deleted after authentication)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning(f"Cancel subscription request for deleted user {user_id}")
        raise ValueError("User account no longer exists")
    
    # Get current subscription
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    if not subscription:
        raise ValueError("No subscription found")
    
    # If already on free plan, nothing to do
    if subscription.plan_type == 'free':
        return {
            "status": "success",
            "message": "Already on free plan",
            "plan_type": "free"
        }
    
    # Get current token balance to preserve it (user paid for full period)
    token_balance = get_or_create_token_balance(user_id, db)
    current_tokens = token_balance.tokens_remaining
    
    # Cancel existing Stripe subscription with final invoice for overage
    # prorate=False means user keeps tokens they paid for (full period)
    # Overage is invoiced and doesn't carry over to the new subscription
    old_subscription_id = subscription.stripe_subscription_id
    if old_subscription_id:
        try:
            # Cancel with invoice_now=True to finalize overage charges (no prorating)
            cancel_subscription_with_invoice(old_subscription_id, invoice_now=True)
            logger.info(f"Canceled Stripe subscription {old_subscription_id} for user {user_id} (overage invoiced, tokens preserved)")
        except Exception as e:
            logger.warning(f"Failed to cancel Stripe subscription {old_subscription_id}: {e}")
            # Continue anyway - we'll create the free subscription
    
    # Delete old subscription record
    db.delete(subscription)
    
    # Mark tokens as reset BEFORE creating new subscription to prevent webhook from adding tokens
    # This must happen before create_free_subscription to prevent race condition with webhooks
    # We'll update the period after subscription creation, but setting last_reset_at now prevents webhook grants
    token_balance = get_or_create_token_balance(user_id, db)
    reset_time = datetime.now(timezone.utc)
    token_balance.last_reset_at = reset_time
    
    # Create a transaction record NOW (before subscription creation) to mark tokens as preserved
    # This ensures webhook sees the preserve transaction even if it fires immediately
    preserve_transaction = TokenTransaction(
        user_id=user_id,
        video_id=None,
        transaction_type='reset',
        tokens=0,  # No change - tokens preserved
        balance_before=current_tokens,
        balance_after=current_tokens,
        transaction_metadata={
            'plan_type': 'free',
            'tokens_preserved': True,
            'preserved_amount': current_tokens,
            'cancel_subscription': True
        }
    )
    db.add(preserve_transaction)
    db.commit()
    
    # Create new free Stripe subscription (skip token reset - we'll preserve tokens)
    free_subscription = create_free_subscription(user_id, db, skip_token_reset=True)
    if not free_subscription:
        raise ValueError("Failed to create free subscription")
    
    # Preserve tokens that user paid for (they paid for full period, no prorating)
    # Overage has been invoiced and doesn't carry over
    free_plan_tokens = get_plan_monthly_tokens('free')
    
    # Get the balance after subscription creation
    token_balance = get_or_create_token_balance(user_id, db)
    balance_before = token_balance.tokens_remaining
    
    # Preserve existing tokens (user paid for full period)
    token_balance.tokens_remaining = current_tokens
    
    # Set monthly_tokens to reflect actual starting balance for the new plan
    # Use max of preserved tokens and free plan tokens to ensure counter displays correctly
    token_balance.monthly_tokens = max(current_tokens, free_plan_tokens)
    
    # Reset usage counter for clean start on new plan
    token_balance.tokens_used_this_period = 0
    
    # Update period to match new subscription
    token_balance.period_start = free_subscription.current_period_start
    token_balance.period_end = free_subscription.current_period_end
    # last_reset_at already set above before creating subscription to prevent webhook race condition
    token_balance.updated_at = datetime.now(timezone.utc)
    
    # Update the preserve transaction with period info (transaction already created above)
    # Query recent reset transactions and filter in Python (matches existing codebase pattern)
    recent_transactions = db.query(TokenTransaction).filter(
        TokenTransaction.user_id == user_id,
        TokenTransaction.transaction_type == 'reset',
        TokenTransaction.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)
    ).order_by(TokenTransaction.created_at.desc()).all()
    
    preserve_transaction = None
    for transaction in recent_transactions:
        metadata = transaction.transaction_metadata or {}
        if metadata.get('tokens_preserved') == True and metadata.get('cancel_subscription') == True:
            preserve_transaction = transaction
            break
    
    if preserve_transaction:
        preserve_transaction.transaction_metadata.update({
            'period_start': free_subscription.current_period_start.isoformat(),
            'period_end': free_subscription.current_period_end.isoformat(),
            'subscription_id': free_subscription.stripe_subscription_id
        })
    
    db.commit()
    
    logger.info(f"User {user_id} canceled subscription {old_subscription_id} and switched to free plan. Overage invoiced, preserved {current_tokens} tokens (user paid for full period)")
    return {
        "status": "success",
        "message": "Subscription canceled and switched to free plan",
        "plan_type": "free",
        "tokens_preserved": current_tokens
    }


# ============================================================================
# CHECKOUT CREATION
# ============================================================================

def create_subscription_checkout(
    user_id: int,
    plan_key: str,
    frontend_url: str,
    db: Session
) -> Dict[str, Any]:
    """Create Stripe checkout session for subscription
    
    Consolidates logic from both /checkout and /create-checkout routes.
    Handles plan validation, existing subscription checks, and upgrade scenarios.
    
    Args:
        user_id: User ID
        plan_key: Plan key (e.g., 'starter', 'creator', 'unlimited')
        frontend_url: Frontend URL for success/cancel redirects
        db: Database session
    
    Returns:
        Dict with session data or error response with portal_url
    
    Raises:
        ValueError: If plan is invalid or user already has subscription (with portal_url in response)
    """
    plans = get_plans()
    if plan_key not in plans:
        raise ValueError(f"Invalid plan: {plan_key}")
    
    plan = plans[plan_key]
    if not plan.get("stripe_price_id"):
        raise ValueError(f"Plan {plan_key} is not configured with a Stripe price")
    
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
    
    # Build success and cancel URLs
    success_url = f"{frontend_url}/app/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_url}/app/subscription"
    
    # Check if user already has an active subscription that prevents checkout
    # (only if cancel_existing is False - meaning we're not upgrading)
    if not cancel_existing and existing_subscription:
        # User has subscription but we're not canceling it - return portal URL
        portal_url = get_customer_portal_url(user_id, f"{frontend_url}/app/subscription", db)
        if portal_url:
            return {
                "error": "User already has an active subscription",
                "message": "User already has an active subscription. Use the customer portal to manage it.",
                "portal_url": portal_url
            }
    
    try:
        session_data = create_checkout_session(
            user_id,
            plan["stripe_price_id"],
            success_url,
            cancel_url,
            db,
            cancel_existing=cancel_existing
        )
        
        if not session_data:
            raise ValueError("Failed to create checkout session")
        
        return session_data
    except ValueError as e:
        # Re-raise ValueError exceptions (invalid plan, etc.)
        raise


# ============================================================================
# CURRENT SUBSCRIPTION WITH AUTO-REPAIR
# ============================================================================

def get_current_subscription_with_auto_repair(
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Get user's current subscription with auto-repair logic
    
    If user doesn't have a subscription, automatically creates a free one.
    This is the "auto-repair" logic that ensures all users have a subscription.
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with subscription info and token balance
    
    Raises:
        ValueError: If user doesn't exist
    """
    # Verify user still exists (may have been deleted after authentication)
    user = get_user_by_id(user_id, db)
    if not user:
        logger.warning(f"Subscription request for deleted user {user_id}")
        raise ValueError("User account no longer exists")
    
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


# ============================================================================
# WEBHOOK PROCESSING
# ============================================================================

def process_stripe_webhook(
    payload: bytes,
    sig_header: str,
    db: Session
) -> Dict[str, Any]:
    """Process Stripe webhook event
    
    Validates webhook signature, handles idempotency, and processes different event types.
    Returns success (200) even on processing errors to prevent Stripe retries.
    Only raises exceptions for signature validation failures.
    
    Args:
        payload: Raw request body as bytes (must not be parsed by middleware)
        sig_header: Stripe signature header
        db: Database session
    
    Returns:
        Dict with status information
    
    Raises:
        ValueError: For invalid payload
        stripe.error.SignatureVerificationError: For invalid signature
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Webhook secret not configured")
        raise ValueError("Webhook secret not configured")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise ValueError("Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise stripe.error.SignatureVerificationError("Invalid signature", sig_header)
    
    # Log event for idempotency
    stripe_event = log_stripe_event(
        event["id"],
        event["type"],
        event,
        db
    )
    
    if stripe_event.processed:
        logger.info(f"Webhook event {event['id']} already processed")
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
        logger.info(f"Successfully processed webhook event {event['id']} of type {event_type}")
        return {"status": "success"}
    except Exception as e:
        # Log error but return success to prevent Stripe retries
        # This is critical: Stripe will retry webhooks that return non-2xx responses
        logger.error(f"Error processing webhook {event['id']}: {e}", exc_info=True)
        mark_stripe_event_processed(event["id"], db, error_message=str(e))
        # Return success even on error to prevent infinite retries
        return {"status": "error_logged", "error": str(e)}

