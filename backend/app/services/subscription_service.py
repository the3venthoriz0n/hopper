"""Subscription service - Subscription management and business logic"""
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import stripe

from app.core.config import settings
from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_transaction import TokenTransaction
from app.services.stripe_service import (
    get_plans, get_price_info, get_plan_monthly_tokens,
    create_free_subscription, cancel_subscription_with_invoice
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
                stripe_sub = stripe.Subscription.retrieve(subscription_id, expand=['items.data.price'])
                items_data = []
                if hasattr(stripe_sub, 'items') and stripe_sub.items:
                    items_data = stripe_sub.items.data if hasattr(stripe_sub.items, 'data') else []
                
                if len(items_data) == 0:
                    logger.error(
                        f"Subscription {subscription_id} exists in Stripe but has NO ITEMS. "
                        f"This subscription is invalid and cannot be processed. "
                        f"Status: {stripe_sub.status}, Customer: {stripe_sub.customer}"
                    )
                else:
                    logger.warning(
                        f"Subscription {subscription_id} exists in Stripe with {len(items_data)} items but not in database. "
                        f"Webhook may not have fired yet or failed. Status: {stripe_sub.status}"
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

