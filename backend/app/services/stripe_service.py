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
                    
                    # Calculate amount_dollars - handle both regular and metered prices
                    amount_dollars = 0.0
                    if p.unit_amount:
                        amount_dollars = p.unit_amount / 100.0
                    elif hasattr(p, 'unit_amount_decimal') and p.unit_amount_decimal:
                        # For metered prices, unit_amount_decimal is a string (e.g., "1.5" = 1.5 cents)
                        amount_dollars = float(p.unit_amount_decimal) / 100.0
                    
                    # Format the price display
                    if amount_dollars > 0:
                        formatted = f"${amount_dollars:.2f}"
                    else:
                        formatted = "Free"
                    
                    new_cache[p.lookup_key] = {
                        "price_id": p.id,
                        "product_id": prod.id,
                        "name": prod.name,
                        "tokens": int(prod.metadata.get('tokens', 0)),
                        "hidden": prod.metadata.get('hidden', 'false').lower() == 'true',
                        "amount_dollars": amount_dollars,
                        "currency": p.currency.upper(),
                        "formatted": formatted
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

def _build_subscription_items(plan_type: str) -> List[Dict]:
    """Build subscription items array with base price and overage (if available).
    
    Args:
        plan_type: Plan type (e.g., 'free', 'starter', 'creator', 'unlimited')
    
    Returns:
        List of item dictionaries for Stripe subscription creation
    
    Raises:
        ValueError: If plan not found in registry
    """
    plan_config = StripeRegistry.get(f"{plan_type}_price")
    if not plan_config:
        raise ValueError(f"Plan '{plan_type}' not found in Stripe registry")
    
    items = [{"price": plan_config["price_id"], "quantity": 1}]
    
    overage = StripeRegistry.get(f"{plan_type}_overage_price")
    if overage:
        items.append({"price": overage["price_id"]})
    
    return items

def create_checkout_session(user_id: int, plan_type: str, success_url: str, cancel_url: str, db: Session) -> Dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    line_items = _build_subscription_items(plan_type)

    checkout_params = {
        "payment_method_types": ["card"],
        "line_items": line_items,
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"user_id": user_id, "plan_key": plan_type},
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

def handle_subscription_created(subscription_data: Any, db: Session):
    """
    Robust handler for subscription creation.
    Fixes 'missing items' by using SubscriptionItem.list and API retrieval.
    """
    # 1. Identity Extraction
    sub_id = _get_stripe_value(subscription_data, 'id')
    if not sub_id:
        logger.error("No subscription ID found in event data")
        return

    # 2. PROACTIVE DATA RETRIEVAL (The Root Cause Fix)
    # Webhooks are often "thin". Fetch the full object and the items list explicitly.
    try:
        # Fetch the sub with expanded prices
        stripe_sub = stripe.Subscription.retrieve(sub_id, expand=['items.data.price'])
        
        # Best Practice: Use the explicit list method for metered/complex items
        sub_items = stripe.SubscriptionItem.list(subscription=sub_id, limit=20)
        items_data = sub_items.data
    except Exception as e:
        logger.error(f"Critical: Could not retrieve subscription {sub_id} from Stripe: {e}")
        return

    if not items_data:
        logger.error(f"Subscription {sub_id} has NO items. Cannot process plan type.")
        return

    # 3. Customer & User Resolution
    customer_id = _get_stripe_value(stripe_sub, 'customer')
    if isinstance(customer_id, dict):
        customer_id = customer_id.get('id')
        
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        logger.warning(f"No user found for customer {customer_id}")
        return

    # 4. Map Plan Type (DRY Registry lookup)
    # We look for the 'base' price (the one that isn't the overage price)
    price_id = None
    for item in items_data:
        p_id = _get_stripe_value(_get_stripe_value(item, 'price'), 'id')
        # Check if this ID is a base price in our registry
        for key, data in StripeRegistry._cache.items():
            if data.get("price_id") == p_id and not key.endswith('_overage_price'):
                price_id = p_id
                plan_key = key.replace("_price", "")
                break
        if price_id: break

    if not price_id:
        logger.error(f"Could not map any items in {sub_id} to a known registry plan.")
        return

    # 5. Database Atomic Update
    # Query by stripe_subscription_id first (most specific - handles webhook race conditions)
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    
    # If not found, query by user_id (might be updating existing subscription)
    if not sub_record:
        sub_record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    
    # Only create new if absolutely no record exists
    if not sub_record:
        sub_record = Subscription(user_id=user.id)
        db.add(sub_record)
        logger.info(f"Creating new subscription record for user {user.id} with subscription {sub_id}")
    else:
        logger.info(f"Updating existing subscription record for user {user.id} with subscription {sub_id}")

    sub_record.stripe_subscription_id = sub_id
    sub_record.plan_type = plan_key
    sub_record.status = _get_stripe_value(stripe_sub, 'status', 'active')
    
    # Update Metered Item ID (if exists) for usage reporting later
    overage_config = StripeRegistry.get(f"{plan_key}_overage_price")
    if overage_config:
        for item in items_data:
            if _get_stripe_value(_get_stripe_value(item, 'price'), 'id') == overage_config['price_id']:
                sub_record.stripe_metered_item_id = item.id
                break

    # 6. Timestamp Sync
    start_ts = _get_stripe_value(stripe_sub, 'current_period_start')
    end_ts = _get_stripe_value(stripe_sub, 'current_period_end')
    if start_ts:
        sub_record.current_period_start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    if end_ts:
        sub_record.current_period_end = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    try:
        db.commit()
        logger.info(f"✅ Subscription {sub_id} synced. Plan: {plan_key}")
        
        # 7. Grant Initial Tokens (Only for new subs)
        # This calls your token logic to add the initial monthly allowance
        from app.services.token_service import ensure_tokens_synced_for_subscription
        ensure_tokens_synced_for_subscription(user.id, sub_id, db)
        
    except Exception as e:
        db.rollback()
        logger.error(f"Database error saving subscription {sub_id}: {e}")


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

def create_stripe_customer(email: str, user_id: int, db: Session) -> Optional[str]:
    """Create a Stripe customer for a user."""
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Stripe not configured, skipping customer creation")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        
        if user.stripe_customer_id and not user.stripe_customer_id.startswith('free_') and not user.stripe_customer_id.startswith('unlimited_'):
            return user.stripe_customer_id
        
        customer = stripe.Customer.create(
            email=email,
            metadata={"user_id": str(user_id)}
        )
        
        user.stripe_customer_id = customer.id
        db.commit()
        
        logger.info(f"Created Stripe customer {customer.id} for user {user_id}")
        return customer.id
    except Exception as e:
        logger.error(f"Failed to create Stripe customer for user {user_id}: {e}")
        return None

def delete_stripe_customer(customer_id: str) -> bool:
    """Delete a Stripe customer. This automatically cancels all subscriptions.
    
    Args:
        customer_id: Stripe customer ID
    
    Returns:
        True if deletion succeeded, False otherwise
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Stripe not configured, skipping customer deletion")
        return False
    
    try:
        stripe.Customer.delete(customer_id)
        logger.info(f"Deleted Stripe customer {customer_id}")
        return True
    except stripe.error.StripeError as e:
        logger.error(f"Failed to delete Stripe customer {customer_id}: {e}")
        return False

def record_token_usage_to_stripe(user_id: int, tokens: int, db: Session) -> bool:
    """Record token usage to Stripe for metered billing (overage tokens).
    
    Uses the Stripe Meter Event API to report overage tokens.
    This function calculates how many tokens are overage (beyond included tokens)
    and reports only the NEW overage tokens to Stripe using meter events.
    
    Args:
        user_id: User ID
        tokens: Number of tokens just consumed
        db: Database session
        
    Returns:
        True if usage was recorded successfully, False otherwise
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot record token usage: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        from app.services.token_service import get_or_create_token_balance, get_plan_tokens
        
        logger.info(f"🔍 record_token_usage_to_stripe called for user {user_id}, tokens_used={tokens}")
        
        # Get user's subscription
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if not subscription:
            logger.warning(f"❌ No subscription found for user {user_id}, skipping Stripe usage recording")
            return False
        
        # Unlimited and free plans don't have metered usage
        if subscription.plan_type in ('unlimited', 'free'):
            logger.debug(f"⏭️  User {user_id} on {subscription.plan_type} plan (no metered usage)")
            return True
        
        # Get customer ID from subscription
        customer_id = subscription.stripe_customer_id
        if not customer_id or customer_id.startswith('free_') or customer_id.startswith('unlimited_'):
            logger.warning(f"❌ Subscription {subscription.stripe_subscription_id} has no valid customer ID, skipping usage recording")
            return False
        
        # Get token balance to calculate overage
        balance = get_or_create_token_balance(user_id, db)
        # Use monthly_tokens (actual starting balance) not base plan amount
        # This accounts for preserved/granted tokens when user upgrades
        included_tokens = balance.monthly_tokens if balance.monthly_tokens > 0 else get_plan_tokens(subscription.plan_type)
        
        # Calculate overage - we ONLY track tokens beyond the included amount
        # Example: Starter plan gives 100 tokens included, but user upgraded and has 200 tokens
        #   - If user uses 50 tokens: overage = 0 (all within included)
        #   - If user uses 250 tokens: overage = 50 (only tokens 201-250 are billed)
        # tokens_used_this_period includes the tokens just consumed
        total_used = balance.tokens_used_this_period
        current_overage = max(0, total_used - included_tokens)
        
        # Calculate previous overage (before this consumption)
        # This allows us to report only the NEW overage tokens incrementally
        previous_total_used = total_used - tokens
        previous_overage = max(0, previous_total_used - included_tokens)
        
        # Only report NEW overage tokens (incremental)
        # This ensures we only report tokens beyond the included amount, not the included tokens
        # Example: User had used 100 tokens (0 overage), now uses 5 more (105 total)
        #   - current_overage = 105 - 100 = 5
        #   - previous_overage = 100 - 100 = 0
        #   - new_overage = 5 - 0 = 5 (only report the 5 overage tokens to Stripe)
        new_overage = current_overage - previous_overage
        
        logger.info(
            f"📊 Token usage calculation for user {user_id}: "
            f"total_used={total_used}, included_tokens={included_tokens}, "
            f"previous_total_used={previous_total_used}, "
            f"current_overage={current_overage}, previous_overage={previous_overage}, "
            f"new_overage={new_overage}"
        )
        
        if new_overage > 0:
            try:
                # Use the Meter Event API to report usage
                # Event name must match the meter's event_name (configured in setup_stripe.py)
                # Payload format matches meter configuration:
                # - customer_mapping expects "stripe_customer_id" in payload
                # - value_settings expects "value" in payload
                # 
                # NOTE: We don't specify timestamp - Stripe will use the current time automatically.
                # This avoids issues with timestamp validation (must be within 35 days).
                import time
                unique_timestamp = int(time.time() * 1000000)  # microseconds for better uniqueness
                identifier = f"user_{user_id}_{unique_timestamp}_{new_overage}"
                
                logger.info(
                    f"Creating meter event for user {user_id}: "
                    f"event_name=hopper_tokens, customer={customer_id}, value={new_overage}, "
                    f"identifier={identifier}"
                )
                
                # Refresh balance from DB to ensure we have latest data
                db.refresh(balance)
                
                # Validate inputs before calling Stripe API
                if not customer_id:
                    logger.error(f"❌ Cannot record meter event: customer_id is None for user {user_id}")
                    return False
                
                if new_overage <= 0:
                    logger.warning(f"⚠️  new_overage is {new_overage}, skipping meter event (should not happen)")
                    return True
                
                meter_event = stripe.billing.MeterEvent.create(
                    event_name="hopper_tokens",  # Must match meter's event_name
                    identifier=identifier,  # Unique identifier (must be unique per event)
                    payload={
                        "stripe_customer_id": customer_id,  # Matches customer_mapping[event_payload_key]
                        "value": new_overage,  # Matches value_settings[event_payload_key]
                    }
                    # No timestamp parameter - Stripe will use current time automatically
                )
                
                # Safely access meter_event.id with error handling
                meter_event_id = 'unknown'
                if meter_event:
                    try:
                        meter_event_id = getattr(meter_event, 'id', None) or str(meter_event.get('id', 'unknown')) if isinstance(meter_event, dict) else 'unknown'
                    except Exception as attr_error:
                        logger.warning(f"Could not extract meter_event.id: {attr_error}, type: {type(meter_event)}")
                        meter_event_id = 'unknown'
                else:
                    logger.warning(f"Meter event response is None for user {user_id}")
                
                logger.info(
                    f"✅ Successfully recorded {new_overage} overage tokens to Stripe meter for user {user_id} "
                    f"(meter_event_id={meter_event_id}, customer_id={customer_id}, "
                    f"total used: {total_used}, included: {included_tokens}, overage: {current_overage})"
                )
                
                # Log the full meter event response for debugging
                try:
                    logger.debug(f"Meter event response type: {type(meter_event)}, value: {meter_event}")
                except Exception as log_error:
                    logger.debug(f"Could not log meter event response: {log_error}")
                
                return True
            except stripe.error.StripeError as e:
                # Safely extract error information
                error_msg = str(e) if e else "Unknown Stripe error"
                error_code = getattr(e, 'code', None)
                user_message = getattr(e, 'user_message', None)
                
                logger.error(
                    f"❌ Stripe error recording meter event for user {user_id}: {error_msg} "
                    f"(customer_id={customer_id}, new_overage={new_overage})"
                )
                # Log full error details for debugging
                if user_message:
                    logger.error(f"Stripe user message: {user_message}")
                if error_code:
                    logger.error(f"Stripe error code: {error_code}")
                # Log the full error object for debugging
                logger.error(f"Full Stripe error: {repr(e)}")
                return False
        else:
            # No new overage to report (all tokens were from included allocation)
            logger.info(
                f"ℹ️  No new overage to report for user {user_id} "
                f"(total used: {total_used}, included: {included_tokens}, current_overage: {current_overage}, new_overage: {new_overage})"
            )
            return True
            
    except Exception as e:
        # Safely extract error information to avoid AttributeError when converting to string
        error_type = type(e).__name__
        error_msg = str(e) if e else "Unknown error"
        error_repr = repr(e)
        
        logger.error(
            f"Error recording token usage to Stripe for user {user_id}: {error_type}: {error_msg}",
            exc_info=True
        )
        logger.error(f"Full error details: {error_repr}")
        return False

def create_stripe_subscription(
    user_id: int,
    plan_type: str,
    db: Session,
    skip_token_reset: bool = False,
    preserved_tokens: Optional[int] = None
) -> Optional[Subscription]:
    """Create a Stripe subscription for a user with the specified plan type.
    
    Args:
        user_id: User ID
        plan_type: Plan type (e.g., 'free', 'starter', 'creator', 'unlimited')
        db: Database session
        skip_token_reset: Whether to skip token reset
        preserved_tokens: Optional preserved tokens balance (for unlimited plan)
    
    Returns:
        Subscription object or None if creation failed
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    if not user.stripe_customer_id or user.stripe_customer_id.startswith('free_') or user.stripe_customer_id.startswith('unlimited_'):
        if not user.email:
            logger.error(f"User {user_id} does not have an email address")
            return None
        customer_id = create_stripe_customer(user.email, user_id, db)
        if not customer_id:
            logger.error(f"Failed to create Stripe customer for user {user_id}")
            return None
    
    try:
        items = _build_subscription_items(plan_type)
    except ValueError as e:
        logger.error(str(e))
        return None
    
    # Get ALL existing subscriptions for this user
    existing_subs = db.query(Subscription).filter(Subscription.user_id == user_id).all()
    
    if existing_subs:
        # Check if user already has the same plan type
        for existing_sub in existing_subs:
            if existing_sub.plan_type == plan_type:
                logger.info(f"User {user_id} already has a subscription for plan '{plan_type}': {existing_sub.stripe_subscription_id}")
                return existing_sub
        
        # Cancel all existing Stripe subscriptions (if they have real Stripe IDs)
        for existing_sub in existing_subs:
            # Cancel Stripe subscription if it has a real ID (not a placeholder)
            if (existing_sub.stripe_subscription_id and 
                not existing_sub.stripe_subscription_id.startswith('free_') and 
                not existing_sub.stripe_subscription_id.startswith('unlimited_')):
                logger.info(f"User {user_id} has existing subscription {existing_sub.stripe_subscription_id} for plan '{existing_sub.plan_type}', canceling before creating new '{plan_type}' subscription")
                try:
                    cancel_subscription_with_invoice(existing_sub.stripe_subscription_id, invoice_now=True)
                    logger.info(f"Canceled existing subscription {existing_sub.stripe_subscription_id} for user {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to cancel subscription {existing_sub.stripe_subscription_id}: {e}")
        
        # Delete ALL existing subscription records from database
        for existing_sub in existing_subs:
            db.delete(existing_sub)
        db.commit()
        logger.info(f"Deleted {len(existing_subs)} existing subscription record(s) for user {user_id}")
    
    try:
        subscription = stripe.Subscription.create(
            customer=user.stripe_customer_id,
            items=items,
            metadata={"user_id": str(user_id), "plan_type": plan_type}
        )
        
        # ROOT CAUSE FIX: After creating Stripe subscription, webhook may have already created the record
        # Query again to check if subscription record exists (by user_id OR by stripe_subscription_id)
        # This handles race conditions with webhooks and concurrent requests
        sub = db.query(Subscription).filter(
            (Subscription.user_id == user_id) | 
            (Subscription.stripe_subscription_id == subscription.id)
        ).first()
        
        if not sub:
            # No record exists, create new one
            sub = Subscription(user_id=user_id)
            db.add(sub)
            logger.info(f"Creating new subscription record for user {user_id}")
        else:
            # Record already exists (webhook or concurrent request created it), update it
            logger.info(f"Subscription record already exists for user {user_id} (likely created by webhook), updating it")
        
        sub.plan_type = plan_type
        sub.status = subscription.status
        sub.stripe_subscription_id = subscription.id
        sub.stripe_customer_id = user.stripe_customer_id
        
        if subscription.current_period_start:
            sub.current_period_start = datetime.fromtimestamp(subscription.current_period_start, tz=timezone.utc)
        if subscription.current_period_end:
            sub.current_period_end = datetime.fromtimestamp(subscription.current_period_end, tz=timezone.utc)
        
        if preserved_tokens is not None:
            sub.preserved_tokens_balance = preserved_tokens
        
        db.commit()
        
        if not skip_token_reset:
            from app.services.token_service import ensure_tokens_synced_for_subscription
            ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
        
        logger.info(f"Created Stripe subscription {subscription.id} for plan '{plan_type}' for user {user_id}")
        return sub
    except Exception as e:
        logger.error(f"Failed to create Stripe subscription for user {user_id} with plan '{plan_type}': {e}")
        return None

def cancel_all_user_subscriptions(user_id: int, db: Session, invoice_now: bool = True):
    """Cancel all Stripe subscriptions for a user."""
    subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
    
    for subscription in subscriptions:
        if subscription.stripe_subscription_id and not subscription.stripe_subscription_id.startswith('unlimited_'):
            try:
                cancel_subscription_with_invoice(subscription.stripe_subscription_id, invoice_now=invoice_now)
                logger.info(f"Canceled Stripe subscription {subscription.stripe_subscription_id} for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to cancel Stripe subscription {subscription.stripe_subscription_id} for user {user_id}: {e}")
                # Continue with other subscriptions even if one fails

