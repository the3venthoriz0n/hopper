"""Token balance and transaction helper functions"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import logging

from models import TokenBalance, TokenTransaction, User, Video
from stripe_config import calculate_tokens_from_bytes, get_plan_monthly_tokens

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
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc),
        )
        db.add(balance)
        db.commit()
        db.refresh(balance)
    
    return balance


def get_token_balance(user_id: int, db: Session) -> Dict[str, Any]:
    """Get current token balance information for a user"""
    from models import Subscription
    
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
    
    return {
        'tokens_remaining': balance.tokens_remaining,
        'tokens_used_this_period': balance.tokens_used_this_period,
        'unlimited': False,
        'period_start': balance.period_start.isoformat() if balance.period_start else None,
        'period_end': balance.period_end.isoformat() if balance.period_end else None,
    }


def check_tokens_available(user_id: int, tokens_required: int, db: Session) -> bool:
    """
    Check if user has enough tokens available.
    
    Returns:
        True if tokens are available, False otherwise
    """
    from models import Subscription
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    # Unlimited plan bypasses check
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if subscription and subscription.plan_type == 'unlimited':
        return True
    
    balance = get_or_create_token_balance(user_id, db)
    return balance.tokens_remaining >= tokens_required


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
    if db is None:
        from models import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        from models import Subscription
        
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
        
        # Check if enough tokens available
        if balance.tokens_remaining < tokens:
            logger.warning(f"Insufficient tokens for user {user_id}: {balance.tokens_remaining} < {tokens}")
            return False
        
        # Deduct tokens
        balance.tokens_remaining -= tokens
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
            transaction_metadata=metadata or {}
        )
        db.add(transaction)
        db.commit()
        
        logger.info(f"Tokens deducted for user {user_id}: {tokens} tokens (balance: {balance_before} -> {balance_after})")
        return True
        
    except Exception as e:
        logger.error(f"Error deducting tokens for user {user_id}: {e}", exc_info=True)
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
    if db is None:
        from models import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        from models import Subscription
        
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
        
        # Add tokens
        balance.tokens_remaining += tokens
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
        
        logger.info(f"Tokens added for user {user_id}: {tokens} tokens (balance: {balance_before} -> {balance_after})")
        return True
        
    except Exception as e:
        logger.error(f"Error adding tokens for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        if should_close:
            db.close()


def reset_tokens_for_subscription(user_id: int, plan_type: str, period_start: datetime, period_end: datetime, db: Session) -> bool:
    """
    Add monthly tokens for a user's subscription period renewal.
    ADDS the plan's monthly allocation to current balance (does not replace).
    
    Args:
        user_id: User ID
        plan_type: Plan type ('free', 'medium', 'pro')
        period_start: Start of the billing period
        period_end: End of the billing period
        db: Database session
        
    Returns:
        True if reset was successful, False otherwise
    """
    try:
        from models import Subscription
        
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
        monthly_tokens = get_plan_monthly_tokens(plan_type)
        
        # ALWAYS ADD tokens to current balance (never replace)
        # This ensures granted tokens are preserved
        balance_before = balance.tokens_remaining
        
        # Check if this is truly the first setup (tokens are 0 AND period is uninitialized)
        # Only in this case, we set tokens instead of adding (to avoid adding to 0)
        # But if user has ANY tokens (including granted), always add
        period_uninitialized = (balance.period_start == balance.period_end)
        
        # Only treat as first setup if tokens are 0 AND period is completely uninitialized
        # This is the ONLY case where we set instead of add
        is_first_setup = (balance.tokens_remaining == 0 and period_uninitialized)
        
        if is_first_setup:
            # First time setup with 0 tokens and uninitialized period - set to plan allocation
            balance.tokens_remaining = monthly_tokens
            tokens_added = monthly_tokens
            logger.info(f"First token setup for user {user_id} on {plan_type} plan: setting to {monthly_tokens} tokens")
        else:
            # Renewal, period change, or user has tokens (including granted) - ADD tokens to current balance
            # This preserves any granted tokens
            balance.tokens_remaining = balance_before + monthly_tokens  # ADD, don't replace
            tokens_added = monthly_tokens
            logger.info(f"Tokens added for user {user_id} on {plan_type} plan: {balance_before} + {monthly_tokens} = {balance.tokens_remaining} tokens (preserving existing tokens)")
        
        balance.tokens_used_this_period = 0
        balance.period_start = period_start
        balance.period_end = period_end
        balance.last_reset_at = datetime.now(timezone.utc)
        balance.updated_at = datetime.now(timezone.utc)
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user_id,
            video_id=None,
            transaction_type='reset',
            tokens=tokens_added,  # Amount added
            balance_before=balance_before,
            balance_after=balance.tokens_remaining,
            transaction_metadata={'plan_type': plan_type, 'period_start': period_start.isoformat(), 'period_end': period_end.isoformat(), 'is_first_setup': is_first_setup}
        )
        db.add(transaction)
        db.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error resetting tokens for user {user_id}: {e}", exc_info=True)
        db.rollback()
        return False


def ensure_tokens_synced_for_subscription(user_id: int, subscription_id: str, db: Session) -> bool:
    """
    Ensure tokens are properly synced for a subscription.
    This is idempotent and safe to call multiple times.
    
    Checks if token balance period matches subscription period, and resets if needed.
    This handles cases where webhooks haven't fired yet or tokens weren't reset.
    
    Args:
        user_id: User ID
        subscription_id: Stripe subscription ID
        db: Database session
        
    Returns:
        True if tokens are synced (or were already synced), False if subscription not found
    """
    try:
        from models import Subscription
        
        # Get subscription from database
        subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription_id
        ).first()
        
        if not subscription:
            logger.debug(f"Subscription {subscription_id} not found in database for user {user_id}")
            return False
        
        # Check if token balance period matches subscription period
        token_balance = get_or_create_token_balance(user_id, db)
        
        # Reset tokens if:
        # 1. Period doesn't match (renewal or new subscription)
        # 2. Token amount doesn't match plan allocation (plan changed, but skip for unlimited)
        period_mismatch = (token_balance.period_start != subscription.current_period_start or 
                          token_balance.period_end != subscription.current_period_end)
        
        # For unlimited plans, only check period mismatch (amount is always -1)
        if subscription.plan_type == 'unlimited':
            if period_mismatch:
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id} (unlimited plan). Updating period.")
                # Unlimited plans don't need token reset, but update period
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
            else:
                logger.debug(f"Tokens already synced for user {user_id}, subscription {subscription_id} (unlimited)")
                return True
        
        # For regular plans, check both period and amount
        monthly_tokens = get_plan_monthly_tokens(subscription.plan_type)
        amount_mismatch = token_balance.tokens_remaining != monthly_tokens
        
        # IMPORTANT: Always preserve tokens when switching plans. Only reset tokens on period renewals.
        # This means:
        # - If period changed AND it's a genuine renewal (not a plan switch), reset tokens
        # - If only amount changed (plan switch), preserve tokens and just update period
        # - Tokens should accumulate across plan changes
        
        if period_mismatch:
            # Period changed - could be a renewal OR a plan switch
            # Check if this is likely a plan switch by comparing old and new subscription periods
            # If the period dates are very close (within a few minutes), it's likely a plan switch, not a renewal
            period_start_diff = abs((subscription.current_period_start - token_balance.period_start).total_seconds())
            period_end_diff = abs((subscription.current_period_end - token_balance.period_end).total_seconds())
            
            # Plan switch: period changes happen within minutes (same day)
            # Renewal: period_end moves forward by ~30 days (monthly cycle)
            is_likely_plan_switch = period_start_diff < 3600  # Less than 1 hour difference = likely plan switch
            is_likely_renewal = (period_end_diff > 2592000 * 0.9 and  # At least 90% of a month (23+ days)
                                period_end_diff < 2592000 * 1.1)  # At most 110% of a month (33 days)
            
            if is_likely_plan_switch and not is_likely_renewal:
                # This is likely a plan switch, not a renewal - preserve tokens
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id}. Detected plan switch (period diff: {period_start_diff}s). Preserving {token_balance.tokens_remaining} tokens and updating period.")
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
            elif is_likely_renewal:
                # This is a genuine renewal - ADD monthly tokens to current balance
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id}. Detected renewal (period_end moved forward by {period_end_diff/86400:.1f} days). Adding {monthly_tokens} tokens to current balance of {token_balance.tokens_remaining}.")
                return reset_tokens_for_subscription(
                    user_id,
                    subscription.plan_type,
                    subscription.current_period_start,
                    subscription.current_period_end,
                    db
                )
            else:
                # Uncertain case - preserve tokens to be safe (could be a plan switch or unusual renewal)
                logger.info(f"Token period mismatch for user {user_id}, subscription {subscription_id}. Uncertain case (period_start_diff: {period_start_diff}s, period_end_diff: {period_end_diff/86400:.1f} days). Preserving {token_balance.tokens_remaining} tokens and updating period.")
                token_balance.period_start = subscription.current_period_start
                token_balance.period_end = subscription.current_period_end
                token_balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                return True
        elif amount_mismatch:
            # Amount mismatch but period matches - this is definitely a plan switch
            # Always preserve tokens on plan switches
            logger.info(f"Token amount mismatch for user {user_id}, subscription {subscription_id} (plan: {subscription.plan_type}, current: {token_balance.tokens_remaining}, expected: {monthly_tokens}). Preserving tokens (plan switch detected).")
            return True
        else:
            logger.debug(f"Tokens already synced for user {user_id}, subscription {subscription_id}")
            return True
            
    except Exception as e:
        logger.error(f"Error ensuring tokens synced for user {user_id}, subscription {subscription_id}: {e}", exc_info=True)
        return False


def get_token_transactions(user_id: int, limit: int = 50, db: Session = None) -> List[Dict[str, Any]]:
    """Get token transaction history for a user"""
    if db is None:
        from models import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
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


