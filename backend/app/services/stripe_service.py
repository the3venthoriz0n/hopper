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

# ============================================================================
# STRIPE REGISTRY
# ============================================================================

class StripeRegistry:
    """Single source of truth for Stripe Price IDs and Product Metadata."""
    _cache = {}
    _last_sync = None
    _sync_attempts = 0
    _max_sync_attempts = 2
    _sync_interval_seconds = 300  # Re-sync every 5 minutes

    @classmethod
    def _should_sync(cls, force: bool = False) -> bool:
        """Determine if we should sync based on cache state and time."""
        if force:
            return True
        if not cls._cache:
            return True
        if cls._last_sync is None:
            return True
        # Re-sync if cache is stale
        time_since_sync = (datetime.now(timezone.utc) - cls._last_sync).total_seconds()
        return time_since_sync > cls._sync_interval_seconds

    @classmethod
    def sync(cls, force: bool = False):
        """Fetches active prices and metadata. Registry uses 'tokens' key."""
        if not settings.STRIPE_SECRET_KEY:
            logger.error("Stripe secret key not configured.")
            return
        
        if not cls._should_sync(force):
            return
            
        try:
            cls._sync_attempts = 0
            logger.info("Starting Stripe Registry sync...")
            try:
                prices = list(stripe.Price.list(active=True, expand=['data.product']).auto_paging_iter())
                logger.info(f"Fetched {len(prices)} active prices from Stripe")
            except Exception as fetch_error:
                logger.error(f"Failed to fetch prices from Stripe: {fetch_error}", exc_info=True)
                raise
            
            if len(prices) == 0:
                logger.warning("No active prices found in Stripe. This may indicate a configuration issue.")
            
            # Group prices by lookup_key and take the most recent for each
            prices_by_key = {}
            prices_without_lookup = 0
            for p in prices:
                if not p.lookup_key:
                    prices_without_lookup += 1
                    continue
                
                if p.lookup_key not in prices_by_key:
                    prices_by_key[p.lookup_key] = []
                prices_by_key[p.lookup_key].append(p)
            
            logger.info(
                f"Prices with lookup_key: {len(prices) - prices_without_lookup}, "
                f"without lookup_key: {prices_without_lookup}, "
                f"unique lookup_keys: {len(prices_by_key)}"
            )
            
            if prices_by_key:
                logger.debug(f"Found lookup_keys: {', '.join(sorted(prices_by_key.keys()))}")
            
            # Process each lookup_key, using the most recent price
            new_cache = {}
            skipped_reasons = {}
            
            for lookup_key, price_list in prices_by_key.items():
                # Sort by created timestamp, newest first
                price_list.sort(key=lambda x: x.created, reverse=True)
                
                # Try each price until we find one with an active product
                price_processed = False
                for p in price_list:
                    # Get product (handle both expanded object and string ID)
                    prod = p.product
                    if isinstance(prod, str):
                        logger.debug(f"Product expansion returned string ID for '{lookup_key}', fetching product {prod}")
                        try:
                            prod = stripe.Product.retrieve(prod)
                            logger.debug(f"Successfully retrieved product {prod.id} for '{lookup_key}'")
                        except Exception as e:
                            logger.debug(f"Failed to retrieve product {prod} for price {p.id} (lookup_key: '{lookup_key}'): {e}, trying next price")
                            continue  # Try next price instead of skipping entirely
                    else:
                        logger.debug(f"Product expansion worked for '{lookup_key}', product: {prod.id if hasattr(prod, 'id') else 'unknown'}")
                    
                    # Skip inactive products - try next price
                    if not prod.active:
                        logger.debug(f"Skipping price {p.id} for '{lookup_key}' - product {prod.id} is inactive, trying next price")
                        continue
                    
                    # Found a valid price with active product - use it
                    if len(price_list) > 1:
                        skipped_prices = [pr.id for pr in price_list if pr != p]
                        logger.debug(f"Multiple prices found for '{lookup_key}'. Using {p.id}, skipped: {skipped_prices}")
                    
                    logger.debug(f"Processing '{lookup_key}' - using price {p.id} with product {prod.id} ({prod.name})")
                    
                    # Calculate amount in dollars
                    amount_dollars = 0.0
                    if p.unit_amount:
                        try:
                            amount_dollars = float(p.unit_amount) / 100.0
                        except (ValueError, TypeError):
                            amount_dollars = 0.0
                    elif hasattr(p, 'unit_amount_decimal') and p.unit_amount_decimal:
                        try:
                            amount_dollars = float(p.unit_amount_decimal) / 100.0
                        except (ValueError, TypeError):
                            amount_dollars = 0.0
                    
                    formatted = f"${amount_dollars:.2f}" if amount_dollars > 0 else "Free"
                    recurring_interval = p.recurring.get('interval') if hasattr(p, 'recurring') and p.recurring else None
                    
                    new_cache[lookup_key] = {
                        "price_id": p.id,
                        "product_id": prod.id,
                        "name": prod.name,
                        "description": prod.description or "",
                        "tokens": int(prod.metadata.get('tokens', 0)),
                        "hidden": prod.metadata.get('hidden', 'false').lower() == 'true',
                        "max_accrual": int(prod.metadata.get('max_accrual', 0)) if prod.metadata.get('max_accrual') else None,
                        "recurring_interval": recurring_interval,
                        "amount_dollars": amount_dollars,
                        "currency": p.currency.upper(),
                        "formatted": formatted
                    }
                    
                    price_processed = True
                    break  # Found valid price, stop trying others
                
                # If no valid price found after trying all, log the skip reason
                if not price_processed:
                    # Try to get a reason from the first price
                    first_price = price_list[0]
                    prod = first_price.product
                    if isinstance(prod, str):
                        try:
                            prod = stripe.Product.retrieve(prod)
                        except Exception:
                            skipped_reasons[lookup_key] = "all prices failed product retrieval"
                            logger.warning(f"Skipping '{lookup_key}' - all prices failed product retrieval")
                            continue
                    
                    if not prod.active:
                        skipped_reasons[lookup_key] = f"product {prod.id} is inactive"
                        logger.warning(f"Skipping '{lookup_key}' - all prices have inactive products")
                    else:
                        skipped_reasons[lookup_key] = "unknown reason"
                        logger.warning(f"Skipping '{lookup_key}' - no valid price found (unknown reason)")
            
            cls._cache = new_cache
            cls._last_sync = datetime.now(timezone.utc)
            cls._sync_attempts = 0
            
            cached_keys = sorted(cls._cache.keys())
            logger.info(
                f"Stripe Registry sync complete: {len(cls._cache)} lookup_keys cached. "
                f"Keys: {', '.join(cached_keys) if cached_keys else 'none'}"
            )
            
            # Log skipped prices for debugging
            if skipped_reasons:
                logger.warning(
                    f"Skipped {len(skipped_reasons)} prices during sync. "
                    f"Reasons: {skipped_reasons}"
                )
            
            # Check for missing expected plans
            common_plans = ['free_daily', 'starter', 'creator', 'unlimited']
            missing_plans = [plan for plan in common_plans if f"{plan}_price" not in cls._cache]
            if missing_plans:
                logger.error(
                    f"Stripe Registry: Missing required plans: {', '.join(missing_plans)}. "
                    f"Total prices fetched: {len(prices)}, "
                    f"Prices with lookup_key: {len(prices) - prices_without_lookup}, "
                    f"Unique lookup_keys found: {len(prices_by_key)}, "
                    f"Cached keys: {', '.join(cached_keys) if cached_keys else 'none'}. "
                    f"Run setup_stripe.py to create missing plans."
                )
        except Exception as e:
            cls._sync_attempts += 1
            logger.error(f"Failed to sync Stripe Registry (attempt {cls._sync_attempts}/{cls._max_sync_attempts}): {e}")
            if cls._sync_attempts < cls._max_sync_attempts:
                logger.info("Retrying Stripe Registry sync...")
                return cls.sync(force=True)
            raise

    @classmethod
    def get(cls, lookup_key: str) -> Optional[Dict]:
        """Get a plan config by lookup key (e.g., 'free_daily_price')."""
        if not cls._cache:
            cls.sync()
        return cls._cache.get(lookup_key)

    @classmethod
    def get_plan_config(cls, plan_type: str) -> Optional[Dict]:
        """Get plan configuration by plan type (e.g., 'free_daily', 'starter')."""
        if not cls._cache:
            cls.sync()
        
        lookup_key = f"{plan_type}_price"
        config = cls._cache.get(lookup_key)
        
        # If not found, force a fresh sync before giving up
        if not config:
            logger.warning(f"Plan '{plan_type}' not found in cache, forcing fresh sync...")
            try:
                cls.sync(force=True)
                config = cls._cache.get(lookup_key)
                
                if not config:
                    # Still not found - log detailed error
                    # Only show plans that are actually in the cache (not hidden)
                    available = [
                        k.replace('_price', '') 
                        for k, v in cls._cache.items() 
                        if k.endswith('_price') 
                        and not k.endswith('_overage_price') 
                        and not v.get('hidden', False)
                    ]
                    logger.error(
                        f"Plan '{plan_type}' still not found after fresh sync. "
                        f"Available plans: {', '.join(available) or 'none'}. "
                        f"All cached keys: {', '.join(sorted(cls._cache.keys()))}"
                    )
            except Exception as e:
                logger.error(f"Failed to force sync when looking up plan '{plan_type}': {e}")
        
        return config

    @classmethod
    def get_all_base_plans(cls) -> Dict:
        """Get all base plans (excluding overage prices and hidden plans)."""
        if not cls._cache:
            cls.sync()
        return {
            k.replace('_price', ''): v 
            for k, v in cls._cache.items() 
            if k.endswith('_price') and not k.endswith('_overage_price') and not v.get('hidden', False)
        }

    @classmethod
    def get_plans(cls) -> Dict[str, Any]:
        """Get all available plan keys for validation (backward compatibility)."""
        return cls.get_all_base_plans()
    
    @classmethod
    def invalidate_cache(cls):
        """Invalidate the cache to force a fresh sync on next access."""
        cls._cache = {}
        cls._last_sync = None
        logger.info("Stripe Registry cache invalidated")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_stripe_value(obj: Any, key: str, default=None):
    """Safely extract value from Stripe object (supports both dict and attribute access)."""
    if obj is None:
        return default
    if hasattr(obj, key):
        value = getattr(obj, key, default)
        if value is not None:
            return value
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _extract_customer_id(obj: Any) -> Optional[str]:
    """Extract customer ID from Stripe object (handles both string and nested object)."""
    customer = _get_stripe_value(obj, 'customer')
    if isinstance(customer, dict):
        return customer.get('id')
    return customer


def _build_subscription_items(plan_type: str) -> List[Dict]:
    """Build subscription items array with base price and overage (if available)."""
    plan_config = StripeRegistry.get_plan_config(plan_type)
    if not plan_config:
        available_plans = list(StripeRegistry.get_all_base_plans().keys())
        available_str = ', '.join(available_plans) if available_plans else 'none'
        raise ValueError(
            f"Plan '{plan_type}' not found in Stripe registry. "
            f"Available plans: {available_str}. "
            f"Please ensure the plan exists in Stripe and the registry is synced."
        )
    
    # Verify product is active
    product_id = plan_config.get("product_id")
    if product_id:
        try:
            product = stripe.Product.retrieve(product_id)
            if not product.active:
                raise ValueError(
                    f"Product for plan '{plan_type}' is inactive (product_id: {product_id}). "
                    f"Cannot create subscription with inactive product."
                )
        except stripe.error.StripeError as e:
            logger.error(f"Failed to retrieve product {product_id} from Stripe API: {e}")
            raise ValueError(f"Failed to verify product status for plan '{plan_type}': {e}")
    
    items = [{"price": plan_config["price_id"], "quantity": 1}]
    
    overage = StripeRegistry.get(f"{plan_type}_overage_price")
    if overage:
        items.append({"price": overage["price_id"]})
    
    return items


# ============================================================================
# CHECKOUT & PORTAL
# ============================================================================

def get_price_info(price_id: str) -> Optional[Dict]:
    """Get price information from Stripe."""
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


def create_checkout_session(user_id: int, plan_type: str, success_url: str, cancel_url: str, db: Session) -> Dict:
    """Create a Stripe Checkout session for a subscription."""
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
    """Get Stripe Customer Portal URL for managing subscriptions."""
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
# SUBSCRIPTION MANAGEMENT
# ============================================================================

def get_subscription_info(user_id: int, db: Session) -> Optional[Dict]:
    """Get subscription information for a user."""
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        return None
    plan_details = StripeRegistry.get_plan_config(sub.plan_type)
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
    """Cancel a Stripe subscription."""
    return stripe.Subscription.delete(subscription_id, invoice_now=invoice_now)


def cancel_all_user_subscriptions(user_id: int, db: Session, invoice_now: bool = True, 
                                  status_filter: Optional[str] = None, update_db_status: bool = False) -> int:
    """Cancel all Stripe subscriptions for a user."""
    query = db.query(Subscription).filter(Subscription.user_id == user_id)
    if status_filter:
        query = query.filter(Subscription.status == status_filter)
    subscriptions = query.all()
    
    canceled_count = 0
    for subscription in subscriptions:
        if subscription.stripe_subscription_id:
            try:
                cancel_subscription_with_invoice(subscription.stripe_subscription_id, invoice_now=invoice_now)
                logger.info(f"Canceled Stripe subscription {subscription.stripe_subscription_id} for user {user_id}")
                canceled_count += 1
                
                if update_db_status:
                    subscription.status = "canceled"
            except Exception as e:
                logger.warning(f"Failed to cancel Stripe subscription {subscription.stripe_subscription_id}: {e}")
    
    if update_db_status and canceled_count > 0:
        db.commit()
    
    return canceled_count


def create_stripe_subscription(
    user_id: int,
    plan_type: str,
    db: Session,
    skip_token_reset: bool = False,
    preserved_tokens: Optional[int] = None,
    preserved_plan_type: Optional[str] = None
) -> Optional[Subscription]:
    """Create a Stripe subscription for a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    if not user.stripe_customer_id:
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
    
    # Handle existing subscriptions
    existing_subs = db.query(Subscription).filter(Subscription.user_id == user_id).all()
    
    if existing_subs:
        # Check if user already has the same plan
        for existing_sub in existing_subs:
            if existing_sub.plan_type == plan_type:
                logger.info(f"User {user_id} already has subscription for plan '{plan_type}': {existing_sub.stripe_subscription_id}")
                return existing_sub
        
        # Cancel all existing subscriptions
        cancel_all_user_subscriptions(user_id, db, invoice_now=True)
        
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
        
        # Handle race condition with webhooks
        sub = db.query(Subscription).filter(
            (Subscription.user_id == user_id) | 
            (Subscription.stripe_subscription_id == subscription.id)
        ).first()
        
        if not sub:
            sub = Subscription(user_id=user_id)
            db.add(sub)
            logger.info(f"Creating new subscription record for user {user_id}")
        else:
            logger.info(f"Subscription record already exists for user {user_id} (likely created by webhook)")
        
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
        if preserved_plan_type is not None:
            sub.preserved_plan_type = preserved_plan_type
        
        db.commit()
        
        if not skip_token_reset:
            from app.services.token_service import ensure_tokens_synced_for_subscription
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(ensure_tokens_synced_for_subscription(user_id, subscription.id, db))
            except RuntimeError:
                asyncio.run(ensure_tokens_synced_for_subscription(user_id, subscription.id, db))
        
        logger.info(f"Created Stripe subscription {subscription.id} for plan '{plan_type}' for user {user_id}")
        return sub
    except Exception as e:
        logger.error(f"Failed to create Stripe subscription for user {user_id} with plan '{plan_type}': {e}")
        return None


# ============================================================================
# CUSTOMER MANAGEMENT
# ============================================================================

def create_stripe_customer(email: str, user_id: int, db: Session) -> Optional[str]:
    """Create a Stripe customer for a user."""
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Stripe not configured, skipping customer creation")
        return None
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        
        if user.stripe_customer_id:
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
    """Delete a Stripe customer (automatically cancels all subscriptions)."""
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


# ============================================================================
# METERED BILLING
# ============================================================================

def record_token_usage_to_stripe(user_id: int, tokens: int, db: Session) -> bool:
    """Record token usage to Stripe for metered billing (overage tokens)."""
    if not settings.STRIPE_SECRET_KEY:
        logger.warning("Cannot record token usage: STRIPE_SECRET_KEY not set")
        return False
    
    try:
        from app.services.token_service import get_or_create_token_balance, get_plan_tokens
        
        logger.info(f"🔍 record_token_usage_to_stripe called for user {user_id}, tokens_used={tokens}")
        
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if not subscription:
            logger.warning(f"❌ No subscription found for user {user_id}")
            return False
        
        # Free and unlimited plans don't have metered usage
        if subscription.plan_type in ('unlimited', 'free', 'free_daily'):
            logger.debug(f"⏭️  User {user_id} on {subscription.plan_type} plan (no metered usage)")
            return True
        
        customer_id = subscription.stripe_customer_id
        if not customer_id:
            logger.warning(f"❌ Subscription {subscription.stripe_subscription_id} has no valid customer ID")
            return False
        
        # Calculate overage tokens
        balance = get_or_create_token_balance(user_id, db)
        included_tokens = balance.monthly_tokens if balance.monthly_tokens > 0 else get_plan_tokens(subscription.plan_type)
        
        total_used = balance.tokens_used_this_period
        current_overage = max(0, total_used - included_tokens)
        
        previous_total_used = total_used - tokens
        previous_overage = max(0, previous_total_used - included_tokens)
        
        new_overage = current_overage - previous_overage
        
        logger.info(
            f"📊 Token usage for user {user_id}: total_used={total_used}, included={included_tokens}, "
            f"current_overage={current_overage}, new_overage={new_overage}"
        )
        
        if new_overage > 0:
            try:
                import time
                unique_timestamp = int(time.time() * 1000000)
                identifier = f"user_{user_id}_{unique_timestamp}_{new_overage}"
                
                logger.info(f"Creating meter event: customer={customer_id}, value={new_overage}, identifier={identifier}")
                
                db.refresh(balance)
                
                meter_event = stripe.billing.MeterEvent.create(
                    event_name="hopper_tokens",
                    identifier=identifier,
                    payload={
                        "stripe_customer_id": customer_id,
                        "value": new_overage,
                    }
                )
                
                meter_event_id = getattr(meter_event, 'id', 'unknown') if meter_event else 'unknown'
                
                logger.info(
                    f"✅ Recorded {new_overage} overage tokens to Stripe for user {user_id} "
                    f"(meter_event_id={meter_event_id}, total used: {total_used}, overage: {current_overage})"
                )
                
                return True
            except stripe.error.StripeError as e:
                logger.error(
                    f"❌ Stripe error recording meter event for user {user_id}: {e} "
                    f"(customer_id={customer_id}, new_overage={new_overage})"
                )
                return False
        else:
            logger.info(f"ℹ️  No new overage to report for user {user_id} (total used: {total_used}, overage: {current_overage})")
            return True
            
    except Exception as e:
        logger.error(f"Error recording token usage to Stripe for user {user_id}: {e}", exc_info=True)
        return False


# ============================================================================
# WEBHOOK HANDLERS
# ============================================================================

def log_stripe_event(event_id: str, event_type: str, payload: dict, db: Session) -> StripeEvent:
    """Log a Stripe webhook event to the database."""
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if not stripe_event:
        stripe_event = StripeEvent(
            event_id=event_id,
            stripe_event_id=event_id,
            event_type=event_type,
            payload=payload,
            processed=False
        )
        db.add(stripe_event)
        db.commit()
        db.refresh(stripe_event)
    return stripe_event


def mark_stripe_event_processed(event_id: str, db: Session, error_message: str = None):
    """Mark a Stripe webhook event as processed."""
    stripe_event = db.query(StripeEvent).filter(StripeEvent.event_id == event_id).first()
    if stripe_event:
        stripe_event.processed = True
        stripe_event.processed_at = datetime.now(timezone.utc)
        stripe_event.error_message = error_message
        db.commit()


def handle_checkout_completed(session: Any, db: Session):
    """Handle checkout.session.completed webhook."""
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


async def handle_subscription_created(subscription_data: Any, db: Session):
    """Handle customer.subscription.created webhook."""
    sub_id = _get_stripe_value(subscription_data, 'id')
    if not sub_id:
        logger.error("No subscription ID found in event data")
        return

    try:
        stripe_sub = stripe.Subscription.retrieve(sub_id, expand=['items.data.price'])
        sub_items = stripe.SubscriptionItem.list(subscription=sub_id, limit=20)
        items_data = sub_items.data
    except Exception as e:
        logger.error(f"Could not retrieve subscription {sub_id} from Stripe: {e}")
        return

    if not items_data:
        logger.error(f"Subscription {sub_id} has no items")
        return

    customer_id = _extract_customer_id(stripe_sub)
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        logger.warning(f"No user found for customer {customer_id}")
        return

    # Map subscription items to plan
    price_id = None
    plan_key = None
    for item in items_data:
        p_id = _get_stripe_value(_get_stripe_value(item, 'price'), 'id')
        for key, data in StripeRegistry._cache.items():
            if data.get("price_id") == p_id and not key.endswith('_overage_price'):
                price_id = p_id
                plan_key = key.replace("_price", "")
                break
        if price_id:
            break

    if not price_id:
        logger.error(f"Could not map items in {sub_id} to a known plan")
        return

    # Cancel other active subscriptions
    existing_new_sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == sub_id
    ).first()

    if not existing_new_sub:
        existing_active = db.query(Subscription).filter(
            Subscription.user_id == user.id,
            Subscription.status == 'active',
            Subscription.stripe_subscription_id != sub_id
        ).all()
        
        for existing_sub in existing_active:
            if existing_sub.stripe_subscription_id:
                try:
                    logger.info(f"Canceling existing subscription {existing_sub.stripe_subscription_id} for user {user.id}")
                    cancel_subscription_with_invoice(existing_sub.stripe_subscription_id, invoice_now=True)
                    existing_sub.status = "canceled"
                except Exception as e:
                    logger.warning(f"Failed to cancel subscription {existing_sub.stripe_subscription_id}: {e}")
        
        if existing_active:
            db.commit()

    # Update or create subscription record
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    if not sub_record:
        sub_record = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub_record:
        sub_record = Subscription(user_id=user.id)
        db.add(sub_record)
        logger.info(f"Creating new subscription record for user {user.id}")
    else:
        logger.info(f"Updating existing subscription record for user {user.id}")

    sub_record.stripe_subscription_id = sub_id
    sub_record.plan_type = plan_key
    sub_record.status = _get_stripe_value(stripe_sub, 'status', 'active')
    
    # Set metered item ID if applicable
    overage_config = StripeRegistry.get(f"{plan_key}_overage_price")
    if overage_config:
        for item in items_data:
            if _get_stripe_value(_get_stripe_value(item, 'price'), 'id') == overage_config['price_id']:
                sub_record.stripe_metered_item_id = item.id
                break

    # Set period timestamps
    start_ts = _get_stripe_value(stripe_sub, 'current_period_start')
    end_ts = _get_stripe_value(stripe_sub, 'current_period_end')
    if start_ts:
        sub_record.current_period_start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    if end_ts:
        sub_record.current_period_end = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    try:
        db.commit()
        logger.info(f"✅ Subscription {sub_id} synced. Plan: {plan_key}")
        
        from app.services.token_service import ensure_tokens_synced_for_subscription
        await ensure_tokens_synced_for_subscription(user.id, sub_id, db)
    except Exception as e:
        db.rollback()
        logger.error(f"Database error saving subscription {sub_id}: {e}")


async def handle_subscription_updated(subscription: Any, db: Session):
    """Handle customer.subscription.updated webhook."""
    await handle_subscription_created(subscription, db)


def handle_subscription_deleted(subscription: Any, db: Session):
    """Handle customer.subscription.deleted webhook."""
    subscription_id = _get_stripe_value(subscription, 'id')
    if not subscription_id:
        return
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == subscription_id).first()
    if sub_record:
        sub_record.status = "canceled"
        db.commit()


async def handle_invoice_payment_succeeded(invoice: Any, db: Session):
    """Handle invoice.payment_succeeded webhook."""
    subscription_id = _get_stripe_value(invoice, 'subscription')
    if not subscription_id:
        return
    sub_record = db.query(Subscription).filter(Subscription.stripe_subscription_id == subscription_id).first()
    if sub_record:
        from app.services.token_service import ensure_tokens_synced_for_subscription
        await ensure_tokens_synced_for_subscription(sub_record.user_id, subscription_id, db)


def handle_invoice_payment_failed(invoice: Any, db: Session):
    """Handle invoice.payment_failed webhook."""
    invoice_id = _get_stripe_value(invoice, 'id', 'unknown')
    logger.warning(f"Payment failed for invoice {invoice_id}")


# ============================================================================
# BACKWARD COMPATIBILITY
# ============================================================================

def get_plans() -> Dict[str, Any]:
    """Get all available plan keys for validation (backward compatibility)."""
    return StripeRegistry.get_plans()