"""Settings service - Business logic for user settings and destination management"""
import logging
from typing import Dict
from sqlalchemy.orm import Session

from app.db.helpers import (
    get_oauth_token, check_token_expiration,
    get_all_oauth_tokens, get_user_settings, set_user_setting, get_user_videos
)

logger = logging.getLogger(__name__)


def get_destinations_status(user_id: int, db: Session) -> Dict:
    """Get destination status for current user with token expiration info
    
    Uses a platform registry pattern to avoid repetitive code.
    """
    # Batch load OAuth tokens and settings to prevent N+1 queries
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    dest_settings = get_user_settings(user_id, "destinations", db=db)
    
    # Platform registry - defines all supported platforms
    platforms = ["youtube", "tiktok", "instagram"]
    
    # Build status for each platform dynamically
    status = {}
    for platform in platforms:
        token = all_tokens.get(platform)
        expiry = check_token_expiration(token)
        
        status[platform] = {
            "connected": token is not None,
            "enabled": dest_settings.get(f"{platform}_enabled", False),
            "token_status": expiry["status"],
            "token_expired": expiry["expired"],
            "token_expires_soon": expiry["expires_soon"]
        }
    
    # Get scheduled video count
    videos = get_user_videos(user_id, db=db)
    scheduled_count = len([v for v in videos if v.status == 'scheduled'])
    
    status["scheduled_videos"] = scheduled_count
    return status


def toggle_destination(user_id: int, platform: str, enabled: bool, db: Session) -> Dict:
    """Toggle destination on/off"""
    set_user_setting(user_id, "destinations", f"{platform}_enabled", enabled, db=db)
    
    token = get_oauth_token(user_id, platform, db=db)
    return {
        platform: {
            "connected": token is not None,
            "enabled": enabled
        }
    }

