"""Settings API routes for global and platform-specific settings"""
import logging
from typing import Optional
from urllib.parse import unquote
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.db import helpers as db_helpers
from app.services.settings_service import get_destinations_status, toggle_destination

router = APIRouter(prefix="/api", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/global/settings")
def get_global_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get global settings"""
    return db_helpers.get_user_settings(user_id, "global", db=db)


@router.post("/global/settings")
def update_global_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    title_template: Optional[str] = Query(None),
    description_template: Optional[str] = Query(None),
    upload_immediately: Optional[bool] = Query(None),
    schedule_mode: Optional[str] = Query(None),
    schedule_interval_value: Optional[int] = Query(None),
    schedule_interval_unit: Optional[str] = Query(None),
    schedule_start_time: Optional[str] = Query(None),
    allow_duplicates: Optional[bool] = Query(None),
    upload_first_immediately: Optional[bool] = Query(None)
):
    """Update global settings"""
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "global", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "global", "description_template", description_template, db=db)
    
    if upload_immediately is not None:
        db_helpers.set_user_setting(user_id, "global", "upload_immediately", upload_immediately, db=db)
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        db_helpers.set_user_setting(user_id, "global", "schedule_mode", schedule_mode, db=db)
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_value", schedule_interval_value, db=db)
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_unit", schedule_interval_unit, db=db)
    
    if schedule_start_time is not None:
        db_helpers.set_user_setting(user_id, "global", "schedule_start_time", schedule_start_time, db=db)
    
    if allow_duplicates is not None:
        db_helpers.set_user_setting(user_id, "global", "allow_duplicates", allow_duplicates, db=db)
    
    if upload_first_immediately is not None:
        db_helpers.set_user_setting(user_id, "global", "upload_first_immediately", upload_first_immediately, db=db)
    
    return db_helpers.get_user_settings(user_id, "global", db=db)


@router.post("/global/wordbank")
def add_wordbank_word(word: str, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Add a word to the global wordbank"""
    # Strip whitespace and capitalize
    word = word.strip().capitalize()
    if not word:
        raise HTTPException(400, "Word cannot be empty")
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word not in wordbank:
        wordbank.append(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    # Return updated settings
    return db_helpers.get_user_settings(user_id, "global", db=db)


@router.delete("/global/wordbank/{word}")
def remove_wordbank_word(word: str, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove a word from the global wordbank"""
    # Decode URL-encoded word
    word = unquote(word)
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word in wordbank:
        wordbank.remove(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    return {"wordbank": wordbank}


@router.delete("/global/wordbank")
def clear_wordbank(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Clear all words from the global wordbank"""
    db_helpers.set_user_setting(user_id, "global", "wordbank", [], db=db)
    return {"wordbank": []}


@router.get("/youtube/settings")
def get_youtube_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube upload settings"""
    return db_helpers.get_user_settings(user_id, "youtube", db=db)


@router.post("/youtube/settings")
def update_youtube_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    visibility: Optional[str] = Query(None), 
    made_for_kids: Optional[bool] = Query(None),
    title_template: Optional[str] = Query(None),
    description_template: Optional[str] = Query(None),
    tags_template: Optional[str] = Query(None)
):
    """Update YouTube upload settings"""
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        db_helpers.set_user_setting(user_id, "youtube", "visibility", visibility, db=db)
    
    if made_for_kids is not None:
        db_helpers.set_user_setting(user_id, "youtube", "made_for_kids", made_for_kids, db=db)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "youtube", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "description_template", description_template, db=db)
    
    if tags_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "tags_template", tags_template, db=db)
    
    return db_helpers.get_user_settings(user_id, "youtube", db=db)


@router.get("/tiktok/settings")
def get_tiktok_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get TikTok upload settings"""
    return db_helpers.get_user_settings(user_id, "tiktok", db=db)


@router.post("/tiktok/settings")
def update_tiktok_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    privacy_level: Optional[str] = Query(None),
    allow_comments: Optional[bool] = Query(None),
    allow_duet: Optional[bool] = Query(None),
    allow_stitch: Optional[bool] = Query(None),
    title_template: Optional[str] = Query(None),
    description_template: Optional[str] = Query(None),
    commercial_content_disclosure: Optional[bool] = Query(None),
    commercial_content_your_brand: Optional[bool] = Query(None),
    commercial_content_branded: Optional[bool] = Query(None)
):
    """Update TikTok upload settings"""
    if privacy_level is not None:
        # Handle empty string or "null" string from frontend
        if privacy_level == "" or privacy_level.lower() == "null":
            # Clear the privacy level setting
            db_helpers.set_user_setting(user_id, "tiktok", "privacy_level", None, db=db)
        else:
            # Accept both old format (public/private/friends) and new API format (PUBLIC_TO_EVERYONE/SELF_ONLY/etc)
            valid_levels = ["public", "private", "friends", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY", "FOLLOWER_OF_CREATOR"]
            if privacy_level not in valid_levels:
                raise HTTPException(400, f"Invalid privacy level: {privacy_level}. Must be one of {valid_levels}")
            db_helpers.set_user_setting(user_id, "tiktok", "privacy_level", privacy_level, db=db)
    
    if allow_comments is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_comments", allow_comments, db=db)
    
    if allow_duet is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_duet", allow_duet, db=db)
    
    if allow_stitch is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_stitch", allow_stitch, db=db)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "tiktok", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "description_template", description_template, db=db)
    
    if commercial_content_disclosure is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "commercial_content_disclosure", commercial_content_disclosure, db=db)
    
    if commercial_content_your_brand is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "commercial_content_your_brand", commercial_content_your_brand, db=db)
    
    if commercial_content_branded is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "commercial_content_branded", commercial_content_branded, db=db)
    
    return db_helpers.get_user_settings(user_id, "tiktok", db=db)


@router.get("/instagram/settings")
def get_instagram_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram upload settings"""
    return db_helpers.get_user_settings(user_id, "instagram", db=db)


@router.post("/instagram/settings")
def update_instagram_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    caption_template: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    disable_comments: Optional[bool] = Query(None),
    disable_likes: Optional[bool] = Query(None)
):
    """Update Instagram upload settings"""
    if caption_template is not None:
        if len(caption_template) > 2200:
            raise HTTPException(400, "Caption template must be 2200 characters or less")
        db_helpers.set_user_setting(user_id, "instagram", "caption_template", caption_template, db=db)
    
    if location_id is not None:
        db_helpers.set_user_setting(user_id, "instagram", "location_id", location_id, db=db)
    
    if disable_comments is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_comments", disable_comments, db=db)
    
    if disable_likes is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_likes", disable_likes, db=db)
    
    return db_helpers.get_user_settings(user_id, "instagram", db=db)


# ============================================================================
# DESTINATIONS ROUTES
# ============================================================================

destinations_router = APIRouter(prefix="/api/destinations", tags=["destinations"])


@destinations_router.get("")
def get_destinations(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get destination status for current user"""
    try:
        return get_destinations_status(user_id, db)
    except Exception as e:
        logger.error(f"Error getting destinations for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load destinations: {str(e)}")


@destinations_router.post("/youtube/toggle")
def toggle_youtube(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle YouTube destination on/off"""
    return toggle_destination(user_id, "youtube", enabled, db)


@destinations_router.post("/tiktok/toggle")
def toggle_tiktok(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle TikTok destination on/off"""
    return toggle_destination(user_id, "tiktok", enabled, db)


@destinations_router.post("/instagram/toggle")
def toggle_instagram(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle Instagram destination on/off"""
    return toggle_destination(user_id, "instagram", enabled, db)

