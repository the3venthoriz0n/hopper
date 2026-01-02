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
    db: Session
) -> Dict[str, Any]:
    """Recompute video title from current template
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with 'ok' and 'title'
    """
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise ValueError("Video not found")
    
    # Get settings
    global_settings = get_user_settings(user_id, "global", db=db)
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    
    # Remove custom title if exists in custom_settings
    custom_settings = video.custom_settings or {}
    if "title" in custom_settings:
        del custom_settings["title"]
        update_video(video_id, user_id, db=db, custom_settings=custom_settings)
    
    # Regenerate title
    filename_no_ext = video.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    
    new_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Update generated_title in database
    update_video(video_id, user_id, db=db, generated_title=new_title)
    
    return {"ok": True, "title": new_title[:100]}


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
    caption: Optional[str] = None
) -> Dict[str, Any]:
    """Update video settings
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session
        title: Optional title override
        description: Optional description
        tags: Optional tags
        visibility: Optional visibility (public/private/unlisted)
        made_for_kids: Optional made for kids flag
        scheduled_time: Optional scheduled time (ISO format string or None to clear)
        privacy_level: Optional privacy level (TikTok)
        allow_comments: Optional allow comments (TikTok)
        allow_duet: Optional allow duet (TikTok)
        allow_stitch: Optional allow stitch (TikTok)
        caption: Optional caption (Instagram)
    
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
        if len(title) > 100:
            raise ValueError("Title must be 100 characters or less")
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
    if caption is not None:
        if len(caption) > 2200:
            raise ValueError("Caption must be 2200 characters or less")
        custom_settings["caption"] = caption
    
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

