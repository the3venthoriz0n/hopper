"""Admin service - Admin operations and user management"""
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_transaction import TokenTransaction
from app.models.video import Video
from app.services.token_service import get_token_balance
from app.services.video_service import cleanup_video_file

logger = logging.getLogger(__name__)
cleanup_logger = logging.getLogger("cleanup")


def list_users_with_subscriptions(
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    db: Session = None
) -> Dict:
    """List users with basic info and subscription aggregation
    
    Args:
        page: Page number (1-indexed)
        limit: Users per page
        search: Optional search term for email
        db: Database session
    
    Returns:
        Dict with 'users', 'total', 'page', 'limit'
    """
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        query = db.query(User)
        if search:
            query = query.filter(User.email.ilike(f"%{search}%"))
        
        total = query.count()
        users = query.order_by(User.created_at.desc()).offset((page-1)*limit).limit(limit).all()
        
        # Get subscriptions for all users in one query
        user_ids = [u.id for u in users]
        subscriptions = {s.user_id: s for s in db.query(Subscription).filter(Subscription.user_id.in_(user_ids)).all()}
        
        return {
            "users": [{
                "id": u.id,
                "email": u.email,
                "created_at": u.created_at.isoformat(),
                "plan_type": subscriptions.get(u.id).plan_type if subscriptions.get(u.id) else None,
                "is_admin": u.is_admin
            } for u in users],
            "total": total,
            "page": page,
            "limit": limit
        }
    finally:
        if should_close:
            db.close()


def get_user_details_with_balance(
    user_id: int,
    db: Session
) -> Dict:
    """Get detailed user information with token balance and usage
    
    Args:
        user_id: User ID to get details for
        db: Database session
    
    Returns:
        Dict with user, token_balance, token_usage, and subscription info
    
    Raises:
        ValueError: If user not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    
    # Get token balance
    balance = get_token_balance(user_id, db)
    
    # Get subscription info
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    # Calculate total tokens used (sum of all negative token transactions, which are deductions)
    total_tokens_used = db.query(func.sum(func.abs(TokenTransaction.tokens))).filter(
        TokenTransaction.user_id == user_id,
        TokenTransaction.tokens < 0  # Negative tokens represent usage/deductions
    ).scalar() or 0
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "plan_type": subscription.plan_type if subscription else None,
            "is_admin": user.is_admin,
            "stripe_customer_id": user.stripe_customer_id
        },
        "token_balance": balance,
        "token_usage": {
            "tokens_used_this_period": balance.get("tokens_used_this_period", 0) if balance else 0,
            "total_tokens_used": int(total_tokens_used)
        },
        "subscription": {
            "plan_type": subscription.plan_type if subscription else None,
            "status": subscription.status if subscription else None
        } if subscription else None
    }


def trigger_manual_cleanup(
    user_id: int,
    db: Session
) -> Dict:
    """Manually trigger cleanup of old and orphaned files
    
    This function allows users to clean up their own old uploaded videos.
    Removes video files for videos uploaded more than 24 hours ago.
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with cleanup results
    """
    cleanup_logger.info(f"Manual cleanup triggered by user {user_id}")
    
    # Clean up user's old uploaded videos (older than 24 hours)
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
    old_uploaded_videos = db.query(Video).filter(
        Video.user_id == user_id,
        Video.status == "uploaded",
        Video.created_at < cutoff_time
    ).all()
    
    cleaned_count = 0
    for video in old_uploaded_videos:
        if cleanup_video_file(video):
            cleaned_count += 1
    
    cleanup_logger.info(f"Manual cleanup by user {user_id}: cleaned {cleaned_count} files")
    
    return {
        "success": True,
        "cleaned_files": cleaned_count,
        "message": f"Cleaned up {cleaned_count} old uploaded video files"
    }

