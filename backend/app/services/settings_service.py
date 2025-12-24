"""Settings service - Business logic for user settings and destination management"""
import logging
from typing import Dict, Any
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


# ============================================================================
# SETTINGS BATCH UPDATES
# ============================================================================

def update_settings_batch(user_id: int, category: str, data_dict: Dict[str, Any], db: Session) -> Dict:
    """Update multiple settings at once in a batch
    
    Args:
        user_id: User ID
        category: Settings category (e.g., "global", "youtube", "tiktok", "instagram")
        data_dict: Dictionary of key-value pairs to update
                  - None values are included to allow clearing settings (e.g., privacy_level)
                  - Only fields explicitly provided in the dict are updated
        db: Database session
    
    Returns:
        Updated settings dictionary
    """
    # Update each setting (including None values to allow clearing)
    for key, value in data_dict.items():
        set_user_setting(user_id, category, key, value, db=db)
    
    # Return updated settings
    return get_user_settings(user_id, category, db=db)


# ============================================================================
# WORDBANK MANAGEMENT
# ============================================================================

def add_wordbank_word(user_id: int, word: str, db: Session) -> Dict:
    """Add a word to the global wordbank"""
    # Strip whitespace and capitalize
    word = word.strip().capitalize()
    if not word:
        raise ValueError("Word cannot be empty")
    
    # Get current wordbank
    settings = get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word not in wordbank:
        wordbank.append(word)
        set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    # Return updated settings
    return get_user_settings(user_id, "global", db=db)


def remove_wordbank_word(user_id: int, word: str, db: Session) -> Dict:
    """Remove a word from the global wordbank"""
    # Get current wordbank
    settings = get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word in wordbank:
        wordbank.remove(word)
        set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    return {"wordbank": wordbank}


def clear_wordbank(user_id: int, db: Session) -> Dict:
    """Clear all words from the global wordbank"""
    set_user_setting(user_id, "global", "wordbank", [], db=db)
    return {"wordbank": []}

