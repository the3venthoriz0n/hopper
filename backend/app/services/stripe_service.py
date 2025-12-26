import logging
import stripe
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone, timedelta
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
    """
    _cache = {}
    _last_sync = None

    @classmethod
    def sync(cls):
        """Fetches active prices and metadata. Registry uses 'tokens' key."""
        if not settings.STRIPE_SECRET_KEY:
            logger.error("Stripe secret key not configured.")
            return
            
        try:
            prices = stripe.Price.list(active=True, expand=['data.product']).data
            new_cache = {}
            for p in prices:
                if p.lookup_key:
                    prod = p.product
                    new_cache[p.lookup_key] = {
                        "price_id": p.id,
                        "product_id": prod.id,
                        "name": prod.name,
                        # Updated to look for 'tokens' instead of 'monthly_tokens'
                        "tokens": int(prod.metadata.get('tokens', 0)),
                        "hidden": prod.metadata.get('hidden', 'false').lower() == 'true',
                        "amount_dollars": p.unit_amount / 100.0 if p.unit_amount else 0.0,
                        "currency": p.currency.upper(),
                        "formatted": f"${p.unit_amount/100.0:.2f}" if p.unit_amount else "Free"
                    }
            cls._cache = new_cache
            cls._last_sync = datetime.now(timezone.utc)
            logger.info(f"Stripe Registry synced: {len(cls._cache)} keys found.")
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
        return {
            k.replace('_price', ''): v 
            for k, v in cls._cache.items() 
            if k.endswith('_price') and not k.endswith('_overage_price')
        }

# ============================================================================
# UTILITY FUNCTIONS (Including missing video_service helper)
# ============================================================================

def calculate_tokens_from_bytes(file_size_bytes: int) -> int:
    """
    Calculates token cost based on video size. 
    Required by video_service.py.
    Example: 1 token per 100MB, minimum 1 token.
    """
    if file_size_bytes <= 0:
        return 0
    # Logic: 1 token per 100MB (100 * 1024 * 1024 bytes)
    mb_size = file_size_bytes / (1024 * 1024)
    tokens = max(1, int(mb_size / 100))
    return tokens

# ============================================================================
# CORE STRIPE OPERATIONS
# ============================================================================

def get_price_info(price_id: str) -> Optional[Dict]:
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

def create_checkout_session(user_id: int, price_id: str, success_url: str, cancel_url: str, db: Session) -> Dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    plan_key = None
    for key, data in StripeRegistry._cache.items():
        if data["price_id"] == price_id:
            plan_key = key.replace("_price", "")
            break

    line_items = [{"price": price_id, "quantity": 1}]
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
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.stripe_customer_id:
        return None
    try:
        session = stripe.billing_portal.Session.create(customer=user.stripe_customer_id, return_url=return_url)
        return session.url
    except Exception as e:
        logger.error(f"Error creating portal session: {e}")
        return None

# ============================================================================
# WEBHOOK & EVENT LOGGING
# ============================================================================

def log_stripe_event(event_id: str, event_type: str, payload: dict, db: Session) -> StripeEvent:
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if not stripe_event:
        stripe_event = StripeEvent(
            event_id=event_id,
            stripe_event_id=event_id,  # Keep both fields in sync
            event_type=event_type,
            payload=payload,
            processed=False
        )
        db.add(stripe_event)
        db.commit()
        db.refresh(stripe_event)
    return stripe_event

def mark_stripe_event_processed(event_id: str, db: Session, error_message: str = None):
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if stripe_event:
        stripe_event.processed = True
        stripe_event.processed_at = datetime.now(timezone.utc)
        stripe_event.error_message = error_message
        db.commit()

# ============================================================================
# STRIPE OBJECT ACCESS HELPER
# ============================================================================

def _get_stripe_value(obj: Any, key: str, default=None):
    """Safely extract value from Stripe object (supports both dict and attribute access)."""
    if obj is None:
        return default
    # Try attribute access first (Stripe objects)
    if hasattr(obj, key):
        value = getattr(obj, key, default)
        if value is not None:
            return value
    # Fall back to dict access
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default

# ============================================================================
# SUBSCRIPTION HANDLERS
# ============================================================================

def get_subscription_info(user_id: int, db: Session) -> Optional[Dict]:
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        return None
    plan_details = StripeRegistry.get(f"{sub.plan_type}_price")
    return {
        "id": sub.id, "plan_type": sub.plan_type, "status": sub.status,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "plan_name": plan_details["name"] if plan_details else sub.plan_type.capitalize()
    }

def cancel_subscription_with_invoice(subscription_id: str, invoice_now: bool = True):
    return stripe.Subscription.delete(subscription_id, invoice_now=invoice_now)

def handle_checkout_completed(session: Any, db: Session):
    metadata = _get_stripe_value(session, 'metadata', {})
    user_id = _get_stripe_value(metadata, 'user_id') if isinstance(metadata, dict) else None
    if not user_id:
        return
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        customer_id = _get_stripe_value(session, 'customer')
        if customer_id:
            user.stripe_customer_id = customer_id
            db.commit()

def handle_subscription_created(subscription: Any, db: Session):
    customer_id = _get_stripe_value(subscription, 'customer')
    if not customer_id:
        logger.warning(f"Subscription missing customer field: {_get_stripe_value(subscription, 'id')}")
        return
    
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        return
    
    items = _get_stripe_value(subscription, 'items', {})
    items_data = _get_stripe_value(items, 'data', [])
    if not items_data or not items_data[0]:
        logger.warning(f"Subscription missing items data: {_get_stripe_value(subscription, 'id')}")
        return
    
    price = _get_stripe_value(items_data[0], 'price', {})
    price_id = _get_stripe_value(price, 'id')
    if not price_id:
        logger.warning(f"Subscription missing price_id: {_get_stripe_value(subscription, 'id')}")
        return
    
    plan_key = "free"
    for key, data in StripeRegistry._cache.items():
        if data["price_id"] == price_id:
            plan_key = key.replace("_price", "")
            break
    
    sub_record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub_record:
        sub_record = Subscription(user_id=user.id)
        db.add(sub_record)
    
    sub_record.stripe_subscription_id = _get_stripe_value(subscription, 'id')
    sub_record.plan_type = plan_key
    sub_record.status = _get_stripe_value(subscription, 'status', 'active')
    
    current_period_start = _get_stripe_value(subscription, 'current_period_start')
    current_period_end = _get_stripe_value(subscription, 'current_period_end')
    
    if current_period_start:
        sub_record.current_period_start = datetime.fromtimestamp(current_period_start, tz=timezone.utc)
    if current_period_end:
        sub_record.current_period_end = datetime.fromtimestamp(current_period_end, tz=timezone.utc)
    
    db.commit()

def handle_subscription_updated(subscription: Any, db: Session):
    handle_subscription_created(subscription, db)

def handle_subscription_deleted(subscription: Any, db: Session):
    subscription_id = _get_stripe_value(subscription, 'id')
    if not subscription_id:
        return
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == subscription_id).first()
    if sub_record:
        sub_record.status = "canceled"
        db.commit()

def handle_invoice_payment_succeeded(invoice: Any, db: Session):
    subscription_id = _get_stripe_value(invoice, 'subscription')
    if not subscription_id:
        return
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == subscription_id).first()
    if sub_record:
        from app.services.token_service import ensure_tokens_synced_for_subscription
        ensure_tokens_synced_for_subscription(sub_record.user_id, subscription_id, db)

def handle_invoice_payment_failed(invoice: Any, db: Session):
    invoice_id = _get_stripe_value(invoice, 'id', 'unknown')
    logger.warning(f"Payment failed for invoice {invoice_id}")

def create_free_subscription(user_id: int, db: Session, skip_token_reset: bool = False) -> Optional[Subscription]:
    user = db.query(User).filter(User.id == user_id).first()
    if not user: return None
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