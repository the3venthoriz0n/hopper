"""Settings API routes for global and platform-specific settings"""
import logging
from urllib.parse import unquote
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.db import helpers as db_helpers
from app.schemas.settings import (
    GlobalSettingsUpdate, YouTubeSettingsUpdate, TikTokSettingsUpdate,
    InstagramSettingsUpdate, AddWordbankWordRequest, TikTokPrivacyLevel,
    ToggleDestinationRequest
)
from app.services.settings_service import (
    get_destinations_status, toggle_destination, update_settings_batch,
    add_wordbank_word, remove_wordbank_word, clear_wordbank
)

router = APIRouter(prefix="/api", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("/global/settings")
def get_global_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get global settings"""
    return db_helpers.get_user_settings(user_id, "global", db=db)


@router.post("/global/settings")
async def update_global_settings(
    settings: GlobalSettingsUpdate,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update global settings"""
    # Convert Pydantic model to dict, excluding unset fields
    update_data = settings.model_dump(exclude_unset=True)
    return await update_settings_batch(user_id, "global", update_data, db)


@router.post("/global/wordbank")
def add_wordbank_word_route(
    request: AddWordbankWordRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Add a word to the global wordbank"""
    try:
        return add_wordbank_word(user_id, request.word, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/global/wordbank/{word}")
def remove_wordbank_word_route(word: str, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove a word from the global wordbank"""
    # Decode URL-encoded word
    decoded_word = unquote(word)
    return remove_wordbank_word(user_id, decoded_word, db)


@router.delete("/global/wordbank")
def clear_wordbank_route(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Clear all words from the global wordbank"""
    return clear_wordbank(user_id, db)


@router.get("/youtube/settings")
def get_youtube_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube upload settings"""
    return db_helpers.get_user_settings(user_id, "youtube", db=db)


@router.post("/youtube/settings")
async def update_youtube_settings(
    settings: YouTubeSettingsUpdate,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update YouTube upload settings"""
    # Convert Pydantic model to dict, excluding unset fields
    update_data = settings.model_dump(exclude_unset=True)
    return await update_settings_batch(user_id, "youtube", update_data, db)


@router.get("/tiktok/settings")
def get_tiktok_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get TikTok upload settings"""
    return db_helpers.get_user_settings(user_id, "tiktok", db=db)


@router.post("/tiktok/settings")
async def update_tiktok_settings(
    settings: TikTokSettingsUpdate,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update TikTok upload settings"""
    # Convert Pydantic model to dict, excluding unset fields
    update_data = settings.model_dump(exclude_unset=True)
    
    # Convert privacy_level enum to string value if present
    # Pydantic's model_dump() will serialize the enum to its value automatically
    # But we need to handle the case where it might still be an enum instance
    if "privacy_level" in update_data:
        privacy_level = update_data["privacy_level"]
        if privacy_level is not None and isinstance(privacy_level, TikTokPrivacyLevel):
            update_data["privacy_level"] = privacy_level.value
    
    return await update_settings_batch(user_id, "tiktok", update_data, db)


@router.get("/instagram/settings")
def get_instagram_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram upload settings"""
    return db_helpers.get_user_settings(user_id, "instagram", db=db)


@router.post("/instagram/settings")
async def update_instagram_settings(
    settings: InstagramSettingsUpdate,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update Instagram upload settings"""
    # Convert Pydantic model to dict, excluding unset fields
    update_data = settings.model_dump(exclude_unset=True)
    return await update_settings_batch(user_id, "instagram", update_data, db)


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
async def toggle_youtube(
    request: ToggleDestinationRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle YouTube destination on/off"""
    return await toggle_destination(user_id, "youtube", request.enabled, db)


@destinations_router.post("/tiktok/toggle")
async def toggle_tiktok(
    request: ToggleDestinationRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle TikTok destination on/off"""
    return await toggle_destination(user_id, "tiktok", request.enabled, db)


@destinations_router.post("/instagram/toggle")
async def toggle_instagram(
    request: ToggleDestinationRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle Instagram destination on/off"""
    return await toggle_destination(user_id, "instagram", request.enabled, db)

