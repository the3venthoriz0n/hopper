"""Settings service - Business logic for user settings and destination management"""
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.db.helpers import (
    get_oauth_token, check_token_expiration,
    get_all_oauth_tokens, get_user_settings, set_user_setting, get_user_videos,
    get_all_user_settings,
    add_wordbank_word as db_add_wordbank_word,
    remove_wordbank_word as db_remove_wordbank_word,
    clear_wordbank as db_clear_wordbank,
    get_wordbank_words_list
)
from app.services.event_service import publish_destination_toggled, publish_settings_changed
from app.services.video.helpers import build_video_response

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
    """Toggle destination on/off and publish updated video data
    
    ROOT CAUSE FIX: When destination is toggled, send updated video data via websocket
    so frontend immediately has correct upload_properties and platform_statuses.
    This prevents race conditions and state inconsistencies.
    """
    set_user_setting(user_id, "destinations", f"{platform}_enabled", enabled, db=db)
    
    # Get connection status before publishing event
    token = get_oauth_token(user_id, platform, db=db)
    connected = token is not None
    
    try:
        # Get all videos with updated settings (batch load to prevent N+1)
        videos = get_user_videos(user_id, db=db)
        all_settings = get_all_user_settings(user_id, db=db)
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        
        logger.info(f"Building video responses for {len(videos)} videos (user {user_id}, platform {platform})")
        
        # Build video responses with updated platform_statuses and upload_properties
        # Deduplicate by video ID to prevent sending duplicates to frontend
        updated_videos = []
        seen_ids = set()
        for video in videos:
            try:
                if video.id in seen_ids:
                    logger.warning(f"Duplicate video ID {video.id} detected for user {user_id}, skipping")
                    continue
                seen_ids.add(video.id)
                
                video_dict = build_video_response(video, all_settings, all_tokens, user_id)
                updated_videos.append(video_dict)
            except Exception as e:
                logger.error(f"Failed to build video response for video {video.id}: {e}", exc_info=True)
        
        logger.info(f"Successfully built {len(updated_videos)} video responses")
        
        # Publish event with connection status AND updated videos
        publish_destination_toggled(user_id, platform, enabled, connected, videos=updated_videos)
        logger.info(f"Published destination_toggled event for user {user_id}, platform {platform}")
        
    except Exception as e:
        logger.error(f"Error in toggle_destination for user {user_id}, platform {platform}: {e}", exc_info=True)
        # Still publish event even if video data fails, just without videos
        publish_destination_toggled(user_id, platform, enabled, connected, videos=[])
    
    return {
        platform: {
            "connected": connected,
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
    
    # Publish event
    publish_settings_changed(user_id, category)
    
    # Return updated settings
    return get_user_settings(user_id, category, db=db)


# ============================================================================
# WORDBANK MANAGEMENT
# ============================================================================

def add_wordbank_word(user_id: int, word: str, db: Session) -> Dict:
    """Add a word to the global wordbank"""
    # Use direct database INSERT operation
    db_add_wordbank_word(user_id, word, db=db)
    
    # Return updated settings
    return get_user_settings(user_id, "global", db=db)


def remove_wordbank_word(user_id: int, word: str, db: Session) -> Dict:
    """Remove a word from the global wordbank"""
    # Use direct database DELETE operation
    db_remove_wordbank_word(user_id, word, db=db)
    
    # Return updated wordbank
    wordbank = get_wordbank_words_list(user_id, db=db)
    return {"wordbank": wordbank}


def clear_wordbank(user_id: int, db: Session) -> Dict:
    """Clear all words from the global wordbank"""
    # Use direct database DELETE operation
    db_clear_wordbank(user_id, db=db)
    return {"wordbank": []}

