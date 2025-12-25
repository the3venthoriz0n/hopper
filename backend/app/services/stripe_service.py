import logging
import stripe
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.models.subscription import Subscription
from app.models.stripe_event import StripeEvent

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeRegistry:
    """
    Single source of truth for Stripe Price IDs and Product Metadata.
    Eliminates the need for local JSON configuration files.
    """
    _cache = {}
    _last_sync = None

    @classmethod
    def sync(cls):
        """Fetches active prices and their product metadata from Stripe."""
        if not settings.STRIPE_SECRET_KEY:
            logger.error("Stripe secret key not configured. Registry sync skipped.")
            return
            
        try:
            # Expand 'product' to get metadata (e.g., monthly_tokens)
            prices = stripe.Price.list(active=True, expand=['data.product']).data
            new_cache = {}
            for p in prices:
                if p.lookup_key:
                    prod = p.product
                    new_cache[p.lookup_key] = {
                        "price_id": p.id,
                        "product_id": prod.id,
                        "name": prod.name,
                        # Get token count from Stripe Metadata; default to 0
                        "monthly_tokens": int(prod.metadata.get('monthly_tokens', 0)),
                        "amount_dollars": p.unit_amount / 100.0 if p.unit_amount else 0.0,
                        "currency": p.currency.upper(),
                        "formatted": f"${p.unit_amount/100.0:.2f}" if p.unit_amount else "Free"
                    }
            cls._cache = new_cache
            cls._last_sync = datetime.now(timezone.utc)
            logger.info(f"Stripe Registry synced successfully: {len(cls._cache)} keys found.")
        except Exception as e:
            logger.error(f"Failed to sync Stripe Registry: {e}")

    @classmethod
    def get(cls, lookup_key: str) -> Optional[Dict]:
        if not cls._cache:
            cls.sync()
        return cls._cache.get(lookup_key)

    @classmethod
    def get_all_base_plans(cls) -> Dict:
        if not cls._cache:
            cls.sync()
        # Returns primary plans (e.g. 'starter'), filtering out overage/hidden items
        return {
            k.replace('_price', ''): v 
            for k, v in cls._cache.items() 
            if k.endswith('_price') and not k.endswith('_overage_price')
        }

# ============================================================================
# CORE STRIPE OPERATIONS
# ============================================================================

def get_price_info(price_id: str) -> Optional[Dict]:
    """Retrieves formatted price info from Stripe."""
    try:
        price = stripe.Price.retrieve(price_id)
        amount_dollars = price.unit_amount / 100.0
        return {
            "amount": price.unit_amount,
            "amount_dollars": amount_dollars,
            "currency": price.currency.upper(),
            "formatted": f"${amount_dollars:.2f}"
        }
    except Exception as e:
        logger.error(f"Error retrieving price {price_id}: {e}")
        return None

def create_checkout_session(
    user_id: int, 
    price_id: str, 
    success_url: str, 
    cancel_url: str, 
    db: Session,
    cancel_existing: bool = False
) -> Dict:
    """Creates a Stripe Checkout Session."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    # Find the lookup_key for this price_id to check for overages
    plan_key = None
    registry = StripeRegistry._cache
    for key, data in registry.items():
        if data["price_id"] == price_id:
            plan_key = key.replace("_price", "")
            break

    line_items = [{"price": price_id, "quantity": 1}]
    
    # Automatically attach overage price if it exists for this plan
    if plan_key:
        overage = StripeRegistry.get(f"{plan_key}_overage_price")
        if overage:
            line_items.append({"price": overage["price_id"]})

    checkout_params = {
        "payment_method_types": ["card"],
        "line_items": line_items,
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"user_id": user_id, "plan_key": plan_key},
    }

    if user.stripe_customer_id:
        checkout_params["customer"] = user.stripe_customer_id
    else:
        checkout_params["customer_email"] = user.email

    session = stripe.checkout.Session.create(**checkout_params)
    return {"id": session.id, "url": session.url}

def get_customer_portal_url(user_id: int, return_url: str, db: Session) -> Optional[str]:
    """Generates a Stripe Billing Portal URL."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.stripe_customer_id:
        return None
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        return session.url
    except Exception as e:
        logger.error(f"Error creating portal session: {e}")
        return None

# ============================================================================
# WEBHOOK & EVENT LOGGING
# ============================================================================

def log_stripe_event(event_id: str, event_type: str, payload: dict, db: Session) -> StripeEvent:
    """Logs a webhook event for idempotency."""
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if not stripe_event:
        stripe_event = StripeEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            processed=False
        )
        db.add(stripe_event)
        db.commit()
        db.refresh(stripe_event)
    return stripe_event

def mark_stripe_event_processed(event_id: str, db: Session, error_message: str = None):
    """Marks an event as handled."""
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if stripe_event:
        stripe_event.processed = True
        stripe_event.processed_at = datetime.now(timezone.utc)
        stripe_event.error_message = error_message
        db.commit()

# ============================================================================
# SUBSCRIPTION HELPERS (REQUIRED BY SERVICE)
# ============================================================================

def get_subscription_info(user_id: int, db: Session) -> Optional[Dict]:
    """Retrieves current subscription record with registry metadata."""
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        return None
    
    # Sync plan details from registry if possible
    plan_details = StripeRegistry.get(f"{sub.plan_type}_price")
    
    return {
        "id": sub.id,
        "plan_type": sub.plan_type,
        "status": sub.status,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "plan_name": plan_details["name"] if plan_details else sub.plan_type.capitalize()
    }

def cancel_subscription_with_invoice(subscription_id: str, invoice_now: bool = True):
    """Cancels a subscription in Stripe immediately."""
    return stripe.Subscription.delete(subscription_id, invoice_now=invoice_now)

# ============================================================================
# WEBHOOK HANDLERS (LOGIC CONTINUED)
# ============================================================================

def handle_checkout_completed(session: Any, db: Session):
    """Handle successful checkout session."""
    user_id = session.metadata.get("user_id")
    plan_key = session.metadata.get("plan_key")
    stripe_customer_id = session.customer
    subscription_id = session.subscription

    if not user_id:
        logger.error(f"No user_id in checkout session {session.id}")
        return

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.stripe_customer_id = stripe_customer_id
        db.commit()

    # If it's a subscription, the details will be finalized in 
    # handle_subscription_created or handle_subscription_updated
    logger.info(f"Checkout completed for user {user_id}, plan: {plan_key}")


def handle_subscription_created(subscription: Any, db: Session):
    """Handle new subscription creation from Stripe."""
    stripe_customer_id = subscription.customer
    user = db.query(User).filter(User.stripe_customer_id == stripe_customer_id).first()
    
    if not user:
        logger.error(f"User not found for customer {stripe_customer_id}")
        return

    # Use Registry to find the plan key by price ID
    price_id = subscription["items"]["data"][0]["price"]["id"]
    plan_key = "free"
    for key, data in StripeRegistry._cache.items():
        if data["price_id"] == price_id:
            plan_key = key.replace("_price", "")
            break

    # Update or create subscription record
    sub_record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub_record:
        sub_record = Subscription(user_id=user.id)
        db.add(sub_record)

    sub_record.stripe_subscription_id = subscription.id
    sub_record.plan_type = plan_key
    sub_record.status = subscription.status
    sub_record.current_period_start = datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc)
    sub_record.current_period_end = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
    
    db.commit()
    logger.info(f"Subscription {subscription.id} created for user {user.id}")


def handle_subscription_updated(subscription: Any, db: Session):
    """Handle subscription updates (plan changes, renewals)."""
    # Logic is identical to creation for updating fields
    handle_subscription_created(subscription, db)


def handle_subscription_deleted(subscription: Any, db: Session):
    """Handle subscription cancellation."""
    sub_record = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription.id
    ).first()
    
    if sub_record:
        # Instead of deleting, we often switch them to 'free' 
        # based on your app's auto-repair logic
        sub_record.status = "canceled"
        db.commit()
        logger.info(f"Subscription {subscription.id} marked as canceled in DB")


def handle_invoice_payment_succeeded(invoice: Any, db: Session):
    """Handle successful payment - critical for token resetting."""
    subscription_id = invoice.subscription
    if not subscription_id:
        return

    sub_record = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_id
    ).first()
    
    if sub_record:
        # Trigger token sync logic
        from app.services.token_service import ensure_tokens_synced_for_subscription
        ensure_tokens_synced_for_subscription(sub_record.user_id, subscription_id, db)
        logger.info(f"Tokens synced for user {sub_record.user_id} following invoice success")


def handle_invoice_payment_failed(invoice: Any, db: Session):
    """Handle failed payment."""
    logger.warning(f"Payment failed for invoice {invoice.id} (Subscription: {invoice.subscription})")
    # You could notify the user here


def create_free_subscription(user_id: int, db: Session, skip_token_reset: bool = False) -> Optional[Subscription]:
    """Helper to create a local record for a free plan."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    # Check if sub already exists
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        sub = Subscription(user_id=user_id)
        db.add(sub)

    sub.plan_type = "free"
    sub.status = "active"
    sub.stripe_subscription_id = f"free_{user_id}_{int(datetime.now().timestamp())}"
    sub.current_period_start = datetime.now(timezone.utc)
    sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
    
    db.commit()
    
    if not skip_token_reset:
        from app.services.token_service import ensure_tokens_synced_for_subscription
        ensure_tokens_synced_for_subscription(user_id, sub.stripe_subscription_id, db)
        
    return sub