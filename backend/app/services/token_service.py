"""Token service - ledger logic for credits"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import logging

from app.models.token_balance import TokenBalance
from app.models.token_transaction import TokenTransaction
from app.models.user import User
from app.models.video import Video
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


def get_or_create_token_balance(user_id: int, db: Session) -> TokenBalance:
    """Get or create token balance for a user"""
    balance = db.query(TokenBalance).filter(TokenBalance.user_id == user_id).first()
    
    if not balance:
        # Create initial balance with 0 tokens (will be set when subscription is created)
        balance = TokenBalance(
            user_id=user_id,
            tokens_remaining=0,
            tokens_used_this_period=0,
            monthly_tokens=0,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc),
        )
        db.add(balance)
        db.commit()
        db.refresh(balance)
    
    return balance


def get_token_balance(user_id: int, db: Session) -> Dict[str, Any]:
    """Get current token balance information for a user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    # Check if user has unlimited plan
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if subscription and subscription.plan_type == 'unlimited':
        return {
            'tokens_remaining': -1,  # -1 indicates unlimited
            'tokens_used_this_period': 0,
            'unlimited': True,
            'period_start': None,
            'period_end': None,
        }
    
    balance = get_or_create_token_balance(user_id, db)
    
    # Get monthly token allocation for the plan (for overage calculation)
    from app.services.stripe_service import get_plan_monthly_tokens
    plan_monthly_tokens = get_plan_monthly_tokens(subscription.plan_type) if subscription else 0
    
    # For display purposes, show 0 if tokens_remaining is negative (user is in overage)
    # The negative value is used internally for tracking, but UI should show 0
    # Overage tokens are tracked separately and billed via Stripe metered billing
    display_tokens_remaining = max(0, balance.tokens_remaining)
    
    # Use stored monthly_tokens (starting balance for period), fallback to plan_monthly_tokens if not set
    stored_monthly_tokens = balance.monthly_tokens if balance.monthly_tokens > 0 else plan_monthly_tokens
    
    # Calculate overage tokens (tokens used beyond the included amount)
    # Use stored_monthly_tokens (actual starting balance) not plan_monthly_tokens (base plan amount)
    # This accounts for preserved/granted tokens when user upgrades
    overage_tokens = max(0, balance.tokens_used_this_period - stored_monthly_tokens) if stored_monthly_tokens > 0 else 0
    
    return {
        'tokens_remaining': display_tokens_remaining,  # Show 0 if negative (in overage)
        'tokens_used_this_period': balance.tokens_used_this_period,
        'monthly_tokens': stored_monthly_tokens,  # Starting balance for period (plan + granted tokens)
        'overage_tokens': overage_tokens,  # Tokens used beyond included amount
        'unlimited': False,
        'period_start': balance.period_start.isoformat() if balance.period_start else None,
        'period_end': balance.period_end.isoformat() if balance.period_end else None,
    }


def check_tokens_available(user_id: int, tokens_required: int, db: Session) -> bool:
    """
    Check if user has enough tokens available.
    
    For paid plans (starter, creator): Returns True if user can use tokens (included + overage allowed)
    For free plan: Returns True only if included tokens are available (hard limit, no overage)
    For unlimited plan: Always returns True
    
    Returns:
        True if tokens can be used, False otherwise
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    # Unlimited plan bypasses check
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if subscription and subscription.plan_type == 'unlimited':
        return True
    
    balance = get_or_create_token_balance(user_id, db)
    
    # Free plan has hard limit - must have enough included tokens
    if subscription and subscription.plan_type == 'free':
        return balance.tokens_remaining >= tokens_required
    
    # Paid plans (starter, creator) allow overage - always return True
    # The actual overage will be tracked and billed via Stripe metered billing
    return True


def deduct_tokens(
    user_id: int,
    tokens: int,
    transaction_type: str = 'upload',
    video_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db: Session = None
) -> bool:
    """
    Deduct tokens from user's balance.
    
    Args:
        user_id: User ID
        tokens: Number of tokens to deduct (should be positive)
        transaction_type: Type of transaction ('upload', 'purchase', 'refund', 'reset', 'grant')
        video_id: Optional video ID if this is for an upload
        metadata: Optional metadata to store with transaction
        db: Database session
        
    Returns:
        True if deduction was successful, False otherwise
    """
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token deduction")
            return False
        
        # Unlimited plan bypasses deduction
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if subscription and subscription.plan_type == 'unlimited':
            # Still log the transaction for audit purposes
            balance_before = -1
            balance_after = -1
            transaction = TokenTransaction(
                user_id=user_id,
                video_id=video_id,
                transaction_type=transaction_type,
                tokens=-tokens,  # Negative for deduction
                balance_before=balance_before,
                balance_after=balance_after,
                transaction_metadata=metadata or {}
            )
            db.add(transaction)
            db.commit()
            logger.info(f"Token deduction logged for unlimited user {user_id}: {tokens} tokens (unlimited)")
            return True
        
        balance = get_or_create_token_balance(user_id, db)
        balance_before = balance.tokens_remaining
        
        # Calculate how much is from included tokens vs overage
        # Included tokens are consumed first, then overage
        included_tokens_used = min(tokens, max(0, balance.tokens_remaining))
        overage_tokens_used = max(0, tokens - included_tokens_used)
        
        # Check if free plan is trying to go over limit (free plan has hard limit, no overage)
        from app.services.stripe_service import get_plan_monthly_tokens
        plan_monthly_tokens = get_plan_monthly_tokens(subscription.plan_type) if subscription else 0
        if subscription and subscription.plan_type == 'free' and overage_tokens_used > 0:
            logger.warning(
                f"Free plan user {user_id} attempted to use {tokens} tokens but only has {balance.tokens_remaining} remaining. "
                f"Free plan has hard limit, blocking overage."
            )
            return False
        
        # Deduct tokens (included tokens first, can go to 0 or negative for overage tracking)
        balance.tokens_remaining -= included_tokens_used
        # Note: tokens_remaining can be negative for overage tracking, but we display it as 0 in UI
        balance.tokens_used_this_period += tokens
        balance.updated_at = datetime.now(timezone.utc)
        
        balance_after = balance.tokens_remaining
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user_id,
            video_id=video_id,
            transaction_type=transaction_type,
            tokens=-tokens,  # Negative for deduction
            balance_before=balance_before,
            balance_after=balance_after,
            transaction_metadata={
                **(metadata or {}),
                'included_tokens_used': included_tokens_used,
                'overage_tokens_used': overage_tokens_used
            }
        )
        db.add(transaction)
        db.commit()
        
        # Record usage to Stripe for metered billing (overage tokens only)
        # This must happen AFTER committing the token deduction so we have accurate usage counts
        # Always call for paid plans (function will calculate overage based on total usage vs included tokens)
        # The function will only report to Stripe if there's actual overage
        if subscription and subscription.plan_type not in ('free', 'unlimited'):
            from app.services.stripe_service import record_token_usage_to_stripe
            # Pass total tokens used - function will calculate overage incrementally
            # It compares tokens_used_this_period vs included_tokens to determine overage
            record_token_usage_to_stripe(user_id, tokens, db)
        
        logger.info(
            f"Tokens deducted for user {user_id}: {tokens} tokens "
            f"({included_tokens_used} from included, {overage_tokens_used} overage) "
            f"(balance: {balance_before} -> {balance_after})"
        )
        return True
        
    except Exception as e:
        logger.error(f"Error deducting tokens for user {user_id}: {e}", exc_info=True)
        if db:
            db.rollback()
        return False
    finally:
        if should_close:
            db.close()


def add_tokens(
    user_id: int,
    tokens: int,
    transaction_type: str = 'purchase',
    metadata: Optional[Dict[str, Any]] = None,
    db: Session = None
) -> bool:
    """
    Add tokens to user's balance.
    
    Args:
        user_id: User ID
        tokens: Number of tokens to add (should be positive)
        transaction_type: Type of transaction ('purchase', 'refund', 'reset', 'grant')
        metadata: Optional metadata to store with transaction
        db: Database session
        
    Returns:
        True if addition was successful, False otherwise
    """
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token addition")
            return False
        
        # Unlimited plan bypasses addition (but still log)
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if subscription and subscription.plan_type == 'unlimited':
            balance_before = -1
            balance_after = -1
            transaction = TokenTransaction(
                user_id=user_id,
                video_id=None,
                transaction_type=transaction_type,
                tokens=tokens,
                balance_before=balance_before,
                balance_after=balance_after,
                transaction_metadata=metadata or {}
            )
            db.add(transaction)
            db.commit()
            logger.info(f"Token addition logged for unlimited user {user_id}: {tokens} tokens (unlimited)")
            return True
        
        balance = get_or_create_token_balance(user_id, db)
        balance_before = balance.tokens_remaining
        
        # Add tokens to both remaining and monthly_tokens (monthly_tokens tracks starting balance)
        balance.tokens_remaining += tokens
        balance.monthly_tokens += tokens  # Increase monthly_tokens when tokens are granted
        balance.updated_at = datetime.now(timezone.utc)
        
        balance_after = balance.tokens_remaining
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user_id,
            video_id=None,
            transaction_type=transaction_type,
            tokens=tokens,
            balance_before=balance_before,
            balance_after=balance_after,
            transaction_metadata=metadata or {}
        )
        db.add(transaction)
        db.commit()
        
        # NOTE: We do NOT update Stripe subscription quantity when tokens are granted.
        # Subscription quantity should always reflect the plan's base monthly_tokens.
        # Granted tokens are tracked separately in the database and don't affect billing.
        
        logger.info(f"Tokens added for user {user_id}: {tokens} tokens (balance: {balance_before} -> {balance_after})")
        return True
        
    except Exception as e:
        logger.error(f"Error adding tokens for user {user_id}: {e}", exc_info=True)
        if db:
            db.rollback()
        return False
    finally:
        if should_close:
            db.close()


def reset_tokens_for_subscription(user_id: int, plan_type: str, period_start: datetime, period_end: datetime, db: Session, is_renewal: bool = False) -> bool:
    """
    Reset or add monthly tokens for a user's subscription period.
    
    On RENEWAL (is_renewal=True): Resets tokens to monthly allocation (clears to 0, then sets to monthly_tokens)
    On NEW SUBSCRIPTION (is_renewal=False): Adds monthly tokens to current balance (preserves granted tokens)
    
    Args:
        user_id: User ID
        plan_type: Plan type ('free', 'starter', 'creator')
        period_start: Start of the billing period
        period_end: End of the billing period
        db: Database session
        is_renewal: If True, reset tokens to monthly allocation. If False, add to current balance.
        
    Returns:
        True if reset was successful, False otherwise
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token reset")
            return False
        
        # Unlimited plan doesn't need reset
        subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if subscription and subscription.plan_type == 'unlimited':
            return True
        
        balance = get_or_create_token_balance(user_id, db)
        
        # Get monthly allocation for plan
        from app.services.stripe_service import get_plan_monthly_tokens
        monthly_tokens = get_plan_monthly_tokens(plan_type)
        
        balance_before = balance.tokens_remaining
        
        if is_renewal:
            # RENEWAL: Reset tokens to monthly allocation (clear to 0, then set to monthly_tokens)
            # This is the ONLY time tokens should be reset to the plan's initial value
            # Tokens do NOT carry over on renewal - they are reset to the monthly allocation
            balance.tokens_remaining = monthly_tokens
            balance.monthly_tokens = monthly_tokens  # Reset monthly_tokens to plan allocation
            tokens_change = monthly_tokens - balance_before
            logger.info(
                f"🔄 RENEWAL: User {user_id} on {plan_type} plan - tokens RESET from {balance_before} to {monthly_tokens} "
                f"(monthly allocation). Tokens do NOT carry over on renewal."
            )
        else:
            # NEW SUBSCRIPTION: Add monthly tokens to current balance (preserves granted tokens)
            balance.tokens_remaining = balance_before + monthly_tokens
            balance.monthly_tokens = balance.tokens_remaining  # Set monthly_tokens to new starting balance
            tokens_change = monthly_tokens
            logger.info(f"New subscription for user {user_id} on {plan_type} plan: {balance_before} + {monthly_tokens} = {balance.tokens_remaining} tokens (preserving existing tokens including granted tokens)")
        
        balance.tokens_used_this_period = 0
        balance.period_start = period_start
        balance.period_end = period_end
        balance.last_reset_at = datetime.now(timezone.utc)
        balance.updated_at = datetime.now(timezone.utc)
        
        # Get subscription ID for metadata
        subscription_id = subscription.stripe_subscription_id if subscription else None
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user_id,
            video_id=None,
            transaction_type='reset',
            tokens=tokens_change,  # Net change in tokens
            balance_before=balance_before,
            balance_after=balance.tokens_remaining,
            transaction_metadata={
                'plan_type': plan_type,
                'period_start': period_start.isoformat(),
                'period_end': period_end.isoformat(),
                'is_renewal': is_renewal,
                'subscription_id': subscription_id  # Track which subscription this was for
            }
        )
        db.add(transaction)
        db.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error resetting tokens for user {user_id}: {e}", exc_info=True)
        if db:
            db.rollback()
        return False


def handle_subscription_renewal(user_id: int, subscription: Subscription, old_period_end: Optional[datetime], db: Session) -> bool:
    """
    Handle subscription renewal by resetting tokens to monthly allocation.
    
    This is the single source of truth for renewal handling. A renewal is detected when:
    - The subscription's current_period_end has moved forward significantly (more than 1 day)
    - The subscription is active (not canceled/past_due)
    - The new period_end is in the future
    - This indicates the subscription has advanced to a new billing cycle
    
    Args:
        user_id: User ID
        subscription: Subscription model instance (already updated with new period)
        old_period_end: The previous period_end before the update (None if new subscription)
        db: Database session
        
    Returns:
        True if renewal was handled, False otherwise
    """
    if not old_period_end:
        # No previous period - this is a new subscription, not a renewal
        return False
    
    new_period_end = subscription.current_period_end
    if new_period_end <= old_period_end:
        # Period didn't advance - not a renewal
        return False
    
    # Calculate period difference
    period_diff_days = (new_period_end - old_period_end).total_seconds() / 86400
    
    # Check if subscription is active (renewals only happen for active subscriptions)
    if subscription.status not in ['active', 'trialing']:
        logger.debug(
            f"Period advanced for user {user_id} but subscription status is '{subscription.status}', not active. "
            f"Not treating as renewal."
        )
        return False
    
    # Check if new period_end is in the future (renewals advance to future periods)
    now = datetime.now(timezone.utc)
    if new_period_end <= now:
        logger.debug(
            f"Period advanced for user {user_id} but new period_end ({new_period_end}) is not in the future. "
            f"Not treating as renewal."
        )
        return False
    
    # Renewal detection: period advanced by at least 20 days
    if 20 <= period_diff_days < 365:
        logger.info(
            f"✅ RENEWAL DETECTED: User {user_id} (subscription {subscription.stripe_subscription_id}): "
            f"period_end advanced by {period_diff_days:.1f} days ({old_period_end} -> {new_period_end}). "
            f"Resetting tokens to monthly allocation (tokens do NOT carry over)."
        )
        
        # Reset tokens to monthly allocation on renewal (is_renewal=True ensures reset, not add)
        result = reset_tokens_for_subscription(
            user_id,
            subscription.plan_type,
            subscription.current_period_start,
            subscription.current_period_end,
            db,
            is_renewal=True  # CRITICAL: This flag ensures tokens are RESET, not added
        )
        
        if result:
            logger.info(f"✅ Renewal token reset completed for user {user_id}")
        else:
            logger.error(f"❌ Renewal token reset FAILED for user {user_id}")
        
        return result
    
    # Period changed but doesn't match renewal criteria
    logger.warning(
        f"⚠️  Period changed for user {user_id} but NOT detected as renewal (diff: {period_diff_days:.1f} days). "
        f"Old: {old_period_end}, New: {new_period_end}, Status: {subscription.status}. "
        f"This may be a renewal that wasn't caught - check period calculation."
    )
    return False


def _check_if_tokens_already_added_for_period(
    user_id: int, 
    subscription_id: str, 
    period_start: datetime, 
    period_end: datetime,
    db: Session
) -> bool:
    """
    Check if tokens were already added for a specific subscription period.
    
    This prevents duplicate token grants when:
    - Subscription is created programmatically and then webhooks fire
    - Both .created and .updated events fire for the same subscription
    - Multiple sync attempts happen
    
    Args:
        user_id: User ID
        subscription_id: Stripe subscription ID
        period_start: Subscription period start
        period_end: Subscription period end
        db: Database session
        
    Returns:
        True if tokens were already added for this period, False otherwise
    """
    # Check for any reset transaction for this subscription and period
    # Match by subscription_id in metadata AND period dates
    existing_reset = db.query(TokenTransaction).filter(
        TokenTransaction.user_id == user_id,
        TokenTransaction.transaction_type == 'reset'
    ).order_by(TokenTransaction.created_at.desc()).all()
    
    for transaction in existing_reset:
        metadata = transaction.transaction_metadata or {}
        reset_subscription_id = metadata.get('subscription_id')
        reset_period_start_str = metadata.get('period_start')
        reset_period_end_str = metadata.get('period_end')
        is_renewal = metadata.get('is_renewal', False)
        
        # Skip renewals - they should always reset tokens
        if is_renewal:
            continue
        
        # Check if this transaction is for the same subscription and period
        if reset_subscription_id == subscription_id:
            try:
                if reset_period_start_str:
                    reset_period_start = datetime.fromisoformat(reset_period_start_str.replace('Z', '+00:00'))
                    reset_period_end = datetime.fromisoformat(reset_period_end_str.replace('Z', '+00:00'))
                    
                    # If periods match (within 1 minute tolerance for timing differences)
                    period_start_diff = abs((period_start - reset_period_start).total_seconds())
                    period_end_diff = abs((period_end - reset_period_end).total_seconds())
                    
                    if period_start_diff < 60 and period_end_diff < 60:
                        logger.debug(
                            f"Tokens already added for user {user_id}, subscription {subscription_id}, "
                            f"period {period_start} - {period_end} (found transaction at {transaction.created_at})"
                        )
                        return True
            except (ValueError, AttributeError) as e:
                logger.debug(f"Error parsing period dates from transaction metadata: {e}")
                continue
    
    return False


def ensure_tokens_synced_for_subscription(user_id: int, subscription_id: str, db: Session) -> bool:
    """
    Ensure tokens are properly synced for a subscription.
    
    This is a repair/sync function for cases where:
    - Webhooks haven't fired yet
    - Tokens weren't reset due to errors
    - Manual intervention is needed
    
    This function delegates renewal handling to handle_subscription_renewal() to avoid duplication.
    This function only handles new subscriptions and ensures tokens are added once per period.
    
    Args:
        user_id: User ID
        subscription_id: Stripe subscription ID
        db: Database session
        
    Returns:
        True if tokens are synced (or were already synced), False if subscription not found
    """
    try:
        # Get subscription from database
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription_id
        ).first()
        
        if not subscription:
            logger.debug(f"Subscription {subscription_id} not found in database for user {user_id}")
            return False
        
        # Check if token balance period matches subscription period
        token_balance = get_or_create_token_balance(user_id, db)
        
        # Check if tokens were already added for this specific subscription period
        # This prevents duplicate grants when subscription is created programmatically and then webhooks fire
        if _check_if_tokens_already_added_for_period(
            user_id, 
            subscription_id, 
            subscription.current_period_start, 
            subscription.current_period_end,
            db
        ):
            logger.info(
                f"Tokens already added for user {user_id}, subscription {subscription_id}, "
                f"period {subscription.current_period_start} - {subscription.current_period_end}. "
                f"Skipping to avoid double-adding. Current balance: {token_balance.tokens_remaining}"
            )
            
            # Just ensure period is updated to match subscription
            if token_balance.period_start != subscription.current_period_start or token_balance.period_end != subscription.current_period_end:
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Updated token balance period to match subscription period")
            
            return True
        
        # For unlimited plans, only check period mismatch (amount is always -1)
        if subscription.plan_type == 'unlimited':
            if token_balance.period_start != subscription.current_period_start or token_balance.period_end != subscription.current_period_end:
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id} (unlimited plan). Updating period.")
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
            return True
        
        # For regular plans, check if we need to handle renewal first
        # Try to detect and handle renewal using the dedicated handler (single source of truth)
        old_period_end = token_balance.period_end if token_balance.period_end != token_balance.period_start else None
        renewal_handled = handle_subscription_renewal(user_id, subscription, old_period_end, db)
        
        if renewal_handled:
            # Renewal was handled - tokens are already reset
            logger.debug(f"Renewal handled for user {user_id}, subscription {subscription_id}")
            return True
        
        # Not a renewal - check if tokens need to be added for new subscription
        period_mismatch = (token_balance.period_start != subscription.current_period_start or 
                          token_balance.period_end != subscription.current_period_end)
        from app.services.stripe_service import get_plan_monthly_tokens
        monthly_tokens = get_plan_monthly_tokens(subscription.plan_type)
        amount_mismatch = token_balance.tokens_remaining != monthly_tokens
        period_uninitialized = (token_balance.period_start == token_balance.period_end)
        
        # If period matches and amount matches, tokens are already synced
        if not period_mismatch and not amount_mismatch:
            logger.debug(f"Tokens already synced for user {user_id}, subscription {subscription_id}")
            return True
        
        # If period doesn't match, check if it's a new subscription or plan switch
        if period_mismatch:
            period_start_diff = abs((subscription.current_period_start - token_balance.period_start).total_seconds())
            period_end_diff = abs((subscription.current_period_end - token_balance.period_end).total_seconds())
            
            # Plan switch: period changes happen within minutes (same day)
            is_likely_plan_switch = period_start_diff < 3600  # Less than 1 hour
            
            if is_likely_plan_switch:
                # Plan switch - preserve tokens, only update period
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id}. Detected plan switch (period diff: {period_start_diff}s). Preserving {token_balance.tokens_remaining} tokens and updating period.")
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
            elif period_uninitialized or (subscription.current_period_end > datetime.now(timezone.utc) and period_end_diff > 86400):
                # New subscription - period is uninitialized or significantly different and in the future
                # Add monthly tokens (preserves granted tokens)
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id}. Detected new subscription. Adding {monthly_tokens} tokens to current balance of {token_balance.tokens_remaining}.")
                return reset_tokens_for_subscription(
                    user_id,
                    subscription.plan_type,
                    subscription.current_period_start,
                    subscription.current_period_end,
                    db,
                    is_renewal=False  # New subscription - adds tokens
                )
        
        # Amount mismatch but period matches - check if tokens were added for this period
        if amount_mismatch and not period_mismatch:
            if subscription.current_period_end > datetime.now(timezone.utc):
                # Active subscription - if no reset transaction for this period, add tokens
                if not _check_if_tokens_already_added_for_period(
                    user_id, 
                    subscription_id, 
                    subscription.current_period_start, 
                    subscription.current_period_end,
                    db
                ):
                    logger.info(f"Token amount mismatch for user {user_id}, subscription {subscription_id} (plan: {subscription.plan_type}, current: {token_balance.tokens_remaining}, expected: {monthly_tokens}). No tokens found for this period. Adding {monthly_tokens} tokens.")
                    return reset_tokens_for_subscription(
                        user_id,
                        subscription.plan_type,
                        subscription.current_period_start,
                        subscription.current_period_end,
                        db,
                        is_renewal=False
                    )
                else:
                    # Tokens were already added - user has granted tokens, preserve them
                    logger.info(f"Token amount mismatch for user {user_id}, subscription {subscription_id} (plan: {subscription.plan_type}, current: {token_balance.tokens_remaining}, expected: {monthly_tokens}). Tokens already added for this period - preserving (user has granted tokens).")
                    return True
        
        return True
            
    except Exception as e:
        logger.error(f"Error ensuring tokens synced for user {user_id}, subscription {subscription_id}: {e}", exc_info=True)
        return False


def get_token_transactions(user_id: int, limit: int = 50, db: Session = None) -> List[Dict[str, Any]]:
    """Get token transaction history for a user"""
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        transactions = db.query(TokenTransaction).filter(
            TokenTransaction.user_id == user_id
        ).order_by(
            TokenTransaction.created_at.desc()
        ).limit(limit).all()
        
        return [
            {
                'id': t.id,
                'transaction_type': t.transaction_type,
                'tokens': t.tokens,
                'balance_before': t.balance_before,
                'balance_after': t.balance_after,
                'metadata': t.transaction_metadata,
                'created_at': t.created_at.isoformat(),
                'video_id': t.video_id,
            }
            for t in transactions
        ]
    finally:
        if should_close:
            db.close()

