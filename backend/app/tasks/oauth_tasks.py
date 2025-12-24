"""Background tasks for OAuth operations"""
import logging
from datetime import datetime, timezone

from app.db.helpers import get_oauth_token
from app.db.session import SessionLocal
from app.services.video_service import _ensure_fresh_token, _fetch_creator_info_safe
from app.services.platform_service import extract_tiktok_account_from_creator_info

tiktok_logger = logging.getLogger("tiktok")


def refresh_tiktok_account_data(user_id: int):
    """Background task to refresh TikTok account data
    
    ROOT CAUSE FIX: Fetch token from DB at execution time to avoid using stale token strings.
    This prevents race conditions where a token refresh happens between when the task is scheduled
    and when it executes.
    
    Args:
        user_id: User ID
    """
    db = SessionLocal()
    try:
        # ROOT CAUSE FIX: Fetch fresh token from DB at execution time, not from parameter
        # This ensures we always use the latest token, even if it was refreshed after task was scheduled
        access_token = _ensure_fresh_token(user_id, db)
        if not access_token:
            tiktok_logger.warning(f"Could not get fresh token for background refresh (user {user_id})")
            return
        
        token_obj = get_oauth_token(user_id, "tiktok", db=db)
        if not token_obj:
            return
        
        extra_data = token_obj.extra_data or {}
        open_id = extra_data.get("open_id")
        if not open_id:
            return
        
        # Fetch fresh data using token fetched from DB
        # ROOT CAUSE FIX: Pass db session so retry logic can re-fetch token if needed
        fresh_creator_info = _fetch_creator_info_safe(access_token, user_id, db=db)
        if not fresh_creator_info:
            return
        
        # Extract account fields using service function
        fresh_account = extract_tiktok_account_from_creator_info(fresh_creator_info, open_id)
        
        # Check if data changed
        cached_creator_info = extra_data.get("creator_info")
        data_changed = False
        
        if cached_creator_info:
            # Check privacy options
            cached_privacy = cached_creator_info.get("privacy_level_options", [])
            fresh_privacy = fresh_creator_info.get("privacy_level_options", [])
            if cached_privacy != fresh_privacy:
                data_changed = True
                tiktok_logger.info(
                    f"Privacy options changed (user {user_id}): "
                    f"{cached_privacy} -> {fresh_privacy}"
                )
            
            # Check other fields
            for field in ["display_name", "username"]:
                if extra_data.get(field) != fresh_account.get(field):
                    data_changed = True
        else:
            data_changed = True
        
        # Update cache if changed
        if data_changed and (fresh_account.get("display_name") or fresh_account.get("username")):
            # ROOT CAUSE FIX: Update extra_data in place to preserve all existing fields
            # save_oauth_token will merge this, but we update in place to be safe
            extra_data.update({
                "display_name": fresh_account["display_name"],
                "username": fresh_account["username"],
                "avatar_url": fresh_account["avatar_url"],
                "creator_info": fresh_creator_info,
                "last_data_refresh": datetime.now(timezone.utc).isoformat()
            })
            
            # ROOT CAUSE FIX: Update token directly instead of calling save_oauth_token
            # This prevents overwriting extra_data and preserves all existing fields
            token_obj.extra_data = extra_data
            db.commit()
            db.refresh(token_obj)
            tiktok_logger.info(f"Background refresh completed - cache updated (user {user_id})")
        else:
            tiktok_logger.debug(f"Background refresh completed - no changes (user {user_id})")
            
    except Exception as e:
        tiktok_logger.warning(f"Background refresh failed (user {user_id}): {str(e)}")
    finally:
        db.close()

