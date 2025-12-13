"""Token balance and transaction helper functions"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone
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
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    # Check if user has unlimited tokens
    if user.unlimited_tokens:
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
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    # Unlimited tokens bypass check
    if user.unlimited_tokens:
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
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token deduction")
            return False
        
        # Unlimited tokens bypass deduction
        if user.unlimited_tokens:
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
                metadata=metadata or {}
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
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token addition")
            return False
        
        # Unlimited tokens bypass addition (but still log)
        if user.unlimited_tokens:
            balance_before = -1
            balance_after = -1
            transaction = TokenTransaction(
                user_id=user_id,
                video_id=None,
                transaction_type=transaction_type,
                tokens=tokens,
                balance_before=balance_before,
                balance_after=balance_after,
                metadata=metadata or {}
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
    Reset tokens for a user's subscription period.
    Sets tokens to the plan's monthly allocation.
    
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
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for token reset")
            return False
        
        # Unlimited tokens don't need reset
        if user.unlimited_tokens:
            return True
        
        balance = get_or_create_token_balance(user_id, db)
        
        # Get monthly allocation for plan
        monthly_tokens = get_plan_monthly_tokens(plan_type)
        
        # Log the reset transaction (old balance -> new balance)
        balance_before = balance.tokens_remaining
        balance.tokens_remaining = monthly_tokens
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
            tokens=monthly_tokens - balance_before,  # Net change
            balance_before=balance_before,
            balance_after=monthly_tokens,
            transaction_metadata={'plan_type': plan_type, 'period_start': period_start.isoformat(), 'period_end': period_end.isoformat()}
        )
        db.add(transaction)
        db.commit()
        
        logger.info(f"Tokens reset for user {user_id} on {plan_type} plan: {balance_before} -> {monthly_tokens} tokens")
        return True
        
    except Exception as e:
        logger.error(f"Error resetting tokens for user {user_id}: {e}", exc_info=True)
        db.rollback()
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


