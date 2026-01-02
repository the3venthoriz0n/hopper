"""Video settings management and recomputation"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.helpers import get_user_videos, get_user_settings, update_video
from app.utils.templates import replace_template_placeholders
from app.services.video.config import PLATFORM_CONFIG

logger = logging.getLogger(__name__)


def recompute_video_title(
    video_id: int,
    user_id: int,
    db: Session,
    platform: str = 'youtube'
) -> Dict[str, Any]:
    """Recompute video title from current template for specified platform
    
    This clears any manual title override and regenerates from template.
    All platforms use the unified 'title' field in custom_settings.
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session
        platform: Platform to recompute for (youtube, tiktok, instagram)
    
    Returns:
        Dict with 'ok' and 'title'
    """
    from app.services.video.config import PLATFORM_CONFIG
    
    if platform not in PLATFORM_CONFIG:
        raise ValueError(f"Invalid platform: {platform}")
    
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise ValueError("Video not found")
    
    global_settings = get_user_settings(user_id, "global", db=db)
    platform_settings = get_user_settings(user_id, platform, db=db)
    
    # Remove unified title override
    custom_settings = dict(video.custom_settings or {})
    if "title" in custom_settings:
        del custom_settings["title"]
        update_video(video_id, user_id, db=db, custom_settings=custom_settings)
    
    # Get platform's template
    config = PLATFORM_CONFIG[platform]
    recompute_fields = config.get('recompute_fields', {})
    primary_field = list(recompute_fields.keys())[0] if recompute_fields else 'title'
    field_config = recompute_fields.get(primary_field, {})
    template_key = field_config.get('template_key', 'title_template')
    
    filename_no_ext = video.filename.rsplit('.', 1)[0]
    title_template = platform_settings.get(template_key, '') or global_settings.get('title_template', '{filename}')
    
    new_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Update generated_title
    update_video(video_id, user_id, db=db, generated_title=new_title)
    
    # Return with appropriate length limit
    max_length = 2200 if platform in ['tiktok', 'instagram'] else 100
    return {"ok": True, "title": new_title[:max_length]}


def update_video_settings(
    video_id: int,
    user_id: int,
    db: Session,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[str] = None,
    visibility: Optional[str] = None,
    made_for_kids: Optional[bool] = None,
    scheduled_time: Optional[str] = None,
    privacy_level: Optional[str] = None,
    allow_comments: Optional[bool] = None,
    allow_duet: Optional[bool] = None,
    allow_stitch: Optional[bool] = None,
    media_type: Optional[str] = None,
    share_to_feed: Optional[bool] = None,
    cover_url: Optional[str] = None,
    disable_comments: Optional[bool] = None,
    disable_likes: Optional[bool] = None
) -> Dict[str, Any]:
    """Update video settings
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session
        title: Optional title override (unified for all platforms - YouTube/TikTok/Instagram)
        description: Optional description
        tags: Optional tags
        visibility: Optional visibility (public/private/unlisted)
        made_for_kids: Optional made for kids flag
        scheduled_time: Optional scheduled time (ISO format string or None to clear)
        privacy_level: Optional privacy level (TikTok)
        allow_comments: Optional allow comments (TikTok)
        allow_duet: Optional allow duet (TikTok)
        allow_stitch: Optional allow stitch (TikTok)
        media_type: Optional media type (Instagram: REELS/VIDEO)
        share_to_feed: Optional share to feed (Instagram)
        cover_url: Optional cover image URL (Instagram)
        disable_comments: Optional disable comments (Instagram)
        disable_likes: Optional disable likes (Instagram)
    
    Returns:
        Dict with updated video info
    """
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise ValueError("Video not found")
    
    # Update custom settings
    custom_settings = video.custom_settings or {}
    
    if title is not None:
        if len(title) > 2200:
            raise ValueError("Title must be 2200 characters or less")
        custom_settings["title"] = title
    
    if description is not None:
        custom_settings["description"] = description
    
    if tags is not None:
        custom_settings["tags"] = tags
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise ValueError("Invalid visibility option")
        custom_settings["visibility"] = visibility
    
    if made_for_kids is not None:
        custom_settings["made_for_kids"] = made_for_kids
    
    # TikTok-specific settings
    if privacy_level is not None:
        # Accept both old format (public/private/friends) and new API format (PUBLIC_TO_EVERYONE/SELF_ONLY/etc)
        valid_levels = ["public", "private", "friends", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY", "FOLLOWER_OF_CREATOR"]
        if privacy_level not in valid_levels:
            raise ValueError(f"Invalid privacy level: {privacy_level}. Must be one of {valid_levels}")
        custom_settings["privacy_level"] = privacy_level
    
    if allow_comments is not None:
        custom_settings["allow_comments"] = allow_comments
    
    if allow_duet is not None:
        custom_settings["allow_duet"] = allow_duet
    
    if allow_stitch is not None:
        custom_settings["allow_stitch"] = allow_stitch
    
    # Instagram-specific settings
    if media_type is not None:
        if media_type not in ["REELS", "VIDEO"]:
            raise ValueError("Invalid media_type: must be REELS or VIDEO")
        custom_settings["media_type"] = media_type
    
    if share_to_feed is not None:
        custom_settings["share_to_feed"] = share_to_feed
    
    if cover_url is not None:
        custom_settings["cover_url"] = cover_url
    
    if disable_comments is not None:
        custom_settings["disable_comments"] = disable_comments
    
    if disable_likes is not None:
        custom_settings["disable_likes"] = disable_likes
    
    # Build update dict
    update_data = {"custom_settings": custom_settings}
    
    # Handle scheduled_time
    if scheduled_time is not None:
        if scheduled_time:  # Set schedule
            try:
                from datetime import datetime, timezone
                parsed_time = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                update_data["scheduled_time"] = parsed_time
                if video.status == "pending":
                    update_data["status"] = "scheduled"
            except ValueError:
                raise ValueError("Invalid datetime format")
        else:  # Clear schedule
            update_data["scheduled_time"] = None
            if video.status == "scheduled":
                update_data["status"] = "pending"
    
    # Update in database
    update_video(video_id, user_id, db=db, **update_data)
    
    # Return updated video
    updated_videos = get_user_videos(user_id, db=db)
    updated_video = next((v for v in updated_videos if v.id == video_id), None)
    
    return {
        "id": updated_video.id,
        "filename": updated_video.filename,
        "status": updated_video.status,
        "custom_settings": updated_video.custom_settings,
        "scheduled_time": updated_video.scheduled_time.isoformat() if hasattr(updated_video, 'scheduled_time') and updated_video.scheduled_time else None
    }


def recompute_all_videos_for_platform(
    user_id: int,
    platform: str,
    db: Session
) -> int:
    """Recompute all videos for a specific platform using current templates
    
    This is a DRY, extensible function that works for any platform by using
    PLATFORM_CONFIG to determine which fields to recompute.
    
    Args:
        user_id: User ID
        platform: Platform name ('youtube', 'tiktok', 'instagram')
        db: Database session
    
    Returns:
        Number of videos updated
    """
    if platform not in PLATFORM_CONFIG:
        raise ValueError(f"Unknown platform: {platform}")
    
    platform_config = PLATFORM_CONFIG[platform]
    recompute_fields = platform_config.get('recompute_fields', {})
    
    if not recompute_fields:
        logger.warning(f"No recompute fields configured for platform: {platform}")
        return 0
    
    # Get all videos and settings
    videos = get_user_videos(user_id, db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    platform_settings = get_user_settings(user_id, platform, db=db)
    wordbank = global_settings.get('wordbank', [])
    
    updated_count = 0
    
    for video in videos:
        filename_no_ext = video.filename.rsplit('.', 1)[0]
        custom_settings = dict(video.custom_settings or {})  # Create a copy to avoid mutating original
        video_updated = False
        update_data = {}
        custom_settings_modified = False
        
        # Process each field configured for this platform
        for field_name, field_config in recompute_fields.items():
            template_key = field_config['template_key']
            field_type = field_config['field']  # 'generated_title' or 'custom_settings'
            custom_key = field_config.get('custom_key')
            
            # Skip if manually overridden
            if custom_key and custom_key in custom_settings:
                continue
            
            # Get template (platform-specific or global fallback)
            template = platform_settings.get(template_key, '')
            if not template:
                # For caption_template, fallback to title_template
                if template_key == 'caption_template':
                    template = global_settings.get('title_template', '{filename}')
                else:
                    template = global_settings.get(template_key, '{filename}' if 'title' in template_key else '')
            
            # Skip if no template available
            if not template:
                continue
            
            # Generate new value
            new_value = replace_template_placeholders(template, filename_no_ext, wordbank)
            
            # Store in appropriate location
            if field_type == 'generated_title':
                update_data['generated_title'] = new_value
                video_updated = True
            elif field_type == 'custom_settings':
                custom_settings[custom_key] = new_value
                custom_settings_modified = True
                video_updated = True
        
        # Update custom_settings if we modified it
        if custom_settings_modified:
            update_data['custom_settings'] = custom_settings
        
        # Update video if any fields were recomputed
        if video_updated:
            update_video(video.id, user_id, db=db, **update_data)
            updated_count += 1
    
    return updated_count

