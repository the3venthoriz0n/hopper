"""Platform-specific services for OAuth account management"""
import logging
from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.db.helpers import get_oauth_token, check_token_expiration
from app.services.video_service import _ensure_fresh_token, _fetch_creator_info_safe

tiktok_logger = logging.getLogger("tiktok")


def get_tiktok_account_info(
    user_id: int,
    db: Session,
    force_refresh: bool = False
) -> Dict:
    """Get TikTok account information with stale-while-revalidate pattern
    
    Strategy:
    1. Ensure token is fresh (with distributed locking)
    2. Always fetch privacy_level_options synchronously (critical for UI)
    3. Use cached data for other fields (fast response)
    4. Extract and update display_name/username from fresh creator_info
    
    Args:
        user_id: User ID
        db: Database session
        force_refresh: If True, force synchronous refresh (skip background task)
    
    Returns:
        Dict with account, creator_info, token_status, token_expired, token_expires_soon, has_cache
    """
    token_obj = get_oauth_token(user_id, "tiktok", db=db)
    
    if not token_obj:
        return {
            "account": None,
            "creator_info": None,
            "token_status": "missing",
            "token_expired": True,
            "token_expires_soon": False,
            "has_cache": False
        }
    
    # Get token status
    token_expiry = check_token_expiration(token_obj)
    token_status = token_expiry.get("status", "valid")
    token_expired = token_expiry.get("expired", False)
    token_expires_soon = token_expiry.get("expires_soon", False)
    
    # Get cached data
    extra_data = token_obj.extra_data or {}
    cached_account = {
        "open_id": extra_data.get("open_id"),
        "display_name": extra_data.get("display_name"),
        "username": extra_data.get("username"),
        "avatar_url": extra_data.get("avatar_url")
    }
    cached_creator_info = extra_data.get("creator_info")
    has_cache = (
        (cached_account.get("display_name") or cached_account.get("username")) and 
        cached_creator_info
    )
    
    # Ensure token is fresh (with distributed locking)
    access_token = _ensure_fresh_token(user_id, db)
    if not access_token:
        # Token refresh failed - return cached data if available
        if has_cache:
            tiktok_logger.warning(f"Token refresh failed, returning cached account data (user {user_id})")
            return {
                "account": cached_account,
                "creator_info": cached_creator_info,
                "token_status": token_status,
                "token_expired": token_expired,
                "token_expires_soon": token_expires_soon,
                "has_cache": has_cache
            }
        return {
            "account": None,
            "creator_info": None,
            "token_status": "expired",
            "token_expired": True,
            "token_expires_soon": False,
            "has_cache": False
        }
    
    # Always fetch privacy_level_options synchronously (critical for UI)
    # This ensures the UI always has the latest privacy options
    try:
        fresh_creator_info = _fetch_creator_info_safe(access_token, user_id, db=db)
        if fresh_creator_info:
            # ROOT CAUSE FIX: Extract and update display_name/username synchronously
            # This ensures account info is available immediately, not just in background task
            fresh_display_name = (
                fresh_creator_info.get("creator_nickname") or 
                fresh_creator_info.get("display_name")
            )
            fresh_username = (
                fresh_creator_info.get("creator_username") or 
                fresh_creator_info.get("username")
            )
            fresh_avatar_url = (
                fresh_creator_info.get("creator_avatar_url") or 
                fresh_creator_info.get("avatar_url")
            )
            
            # Update cached_account for immediate return if we have new data
            if fresh_display_name or fresh_username:
                cached_account = {
                    "open_id": extra_data.get("open_id"),
                    "display_name": fresh_display_name or cached_account.get("display_name"),
                    "username": fresh_username or cached_account.get("username"),
                    "avatar_url": fresh_avatar_url or cached_account.get("avatar_url")
                }
            
            # Update cache with fresh privacy_level_options and account info
            account_updated = False
            privacy_updated = False
            
            # Check if privacy options changed
            if not cached_creator_info or cached_creator_info.get("privacy_level_options") != fresh_creator_info.get("privacy_level_options"):
                privacy_updated = True
            
            # Check if account info changed
            if fresh_display_name and extra_data.get("display_name") != fresh_display_name:
                extra_data["display_name"] = fresh_display_name
                account_updated = True
            if fresh_username and extra_data.get("username") != fresh_username:
                extra_data["username"] = fresh_username
                account_updated = True
            if fresh_avatar_url and extra_data.get("avatar_url") != fresh_avatar_url:
                extra_data["avatar_url"] = fresh_avatar_url
                account_updated = True
            
            # Update cache if anything changed
            if privacy_updated or account_updated:
                extra_data["creator_info"] = fresh_creator_info
                token_obj.extra_data = extra_data
                db.commit()
                if account_updated:
                    tiktok_logger.info(
                        f"Updated TikTok account info synchronously (user {user_id}): "
                        f"{fresh_display_name} (@{fresh_username})"
                    )
                if privacy_updated:
                    tiktok_logger.debug(f"Updated privacy_level_options from API (user {user_id})")
            
            # Use fresh creator_info for response
            creator_info = fresh_creator_info
        else:
            # API call failed, use cached data
            creator_info = cached_creator_info
    except Exception as e:
        tiktok_logger.warning(f"Failed to fetch creator info (user {user_id}): {str(e)}")
        creator_info = cached_creator_info
    
    return {
        "account": cached_account,
        "creator_info": creator_info,
        "token_status": token_status,
        "token_expired": token_expired,
        "token_expires_soon": token_expires_soon,
        "has_cache": has_cache
    }


def extract_tiktok_account_from_creator_info(creator_info: Dict, open_id: Optional[str] = None) -> Dict:
    """Extract account fields from TikTok creator_info response
    
    Args:
        creator_info: Creator info dict from TikTok API
        open_id: Optional open_id to include in account dict
    
    Returns:
        Dict with open_id, display_name, username, avatar_url
    """
    return {
        "open_id": open_id,
        "display_name": (
            creator_info.get("creator_nickname") or 
            creator_info.get("display_name")
        ),
        "username": (
            creator_info.get("creator_username") or 
            creator_info.get("username")
        ),
        "avatar_url": (
            creator_info.get("creator_avatar_url") or 
            creator_info.get("avatar_url")
        ),
    }

