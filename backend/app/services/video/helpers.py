"""Platform-agnostic helper functions"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.oauth_token import OAuthToken
    from app.models.video import Video

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.helpers import (
    get_user_settings, get_all_user_settings, get_all_oauth_tokens, get_oauth_token
)
from app.db.redis import get_upload_progress, get_platform_upload_progress
from app.models.oauth_token import OAuthToken
from app.models.video import Video
from app.utils.templates import (
    replace_template_placeholders, get_video_title, get_video_description
)
from app.services.video.config import PLATFORM_CONFIG
from app.services.video.platforms.tiktok_api import fetch_tiktok_publish_status
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)
upload_logger = logging.getLogger("upload")


def format_platform_error(platform: str, error_message: str) -> str:
    """Format error message with platform name prefix (DRY, extensible)
    
    Args:
        platform: Platform name (e.g., 'youtube', 'tiktok', 'instagram')
        error_message: The error message to format
        
    Returns:
        Formatted error message with platform prefix
    """
    # Capitalize platform name for display
    platform_display = platform.capitalize()
    
    # If error already starts with platform name, don't duplicate
    if error_message.lower().startswith(platform.lower()):
        return error_message
    
    return f"{platform_display}: {error_message}"


def should_publish_progress(current_progress: int, last_published_progress: int) -> bool:
    """Determine if progress should be published (1% increments or completion)
    
    Args:
        current_progress: Current progress percentage (0-100)
        last_published_progress: Last published progress percentage
        
    Returns:
        True if progress should be published (>= 1% change or at 100%)
    """
    return (current_progress - last_published_progress >= 1) or (current_progress == 100)


def build_upload_context(user_id: int, db: Session) -> Dict[str, Any]:
    """Build upload context for a user (enabled destinations, settings, tokens)
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Dictionary with:
            - enabled_destinations: List of enabled destination names
            - dest_settings: Destination settings dict
            - all_tokens: All OAuth tokens dict
    """
    # Batch load destination settings and OAuth tokens to prevent N+1 queries
    dest_settings = get_user_settings(user_id, "destinations", db=db)
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    
    # Determine enabled destinations
    enabled_destinations = []
    for dest_name in ["youtube", "tiktok", "instagram"]:
        is_enabled = dest_settings.get(f"{dest_name}_enabled", False)
        has_token = all_tokens.get(dest_name) is not None
        if is_enabled and has_token:
            enabled_destinations.append(dest_name)
    
    return {
        "enabled_destinations": enabled_destinations,
        "dest_settings": dest_settings,
        "all_tokens": all_tokens
    }


def build_video_response(video: Video, all_settings: Dict[str, Dict], all_tokens: Dict[str, Optional[OAuthToken]], user_id: int) -> Dict[str, Any]:
    """Build video response dictionary with computed titles and upload properties
    
    Args:
        video: Video object
        all_settings: Dictionary of all user settings by category
        all_tokens: Dictionary of all OAuth tokens by platform
        user_id: User ID for Redis progress lookup
        
    Returns:
        Dictionary with video data in the same format as GET /api/videos
    """
    global_settings = all_settings.get("global", {})
    youtube_settings = all_settings.get("youtube", {})
    tiktok_settings = all_settings.get("tiktok", {})
    instagram_settings = all_settings.get("instagram", {})
    dest_settings = all_settings.get("destinations", {})
    
    youtube_token = all_tokens.get("youtube")
    tiktok_token = all_tokens.get("tiktok")
    instagram_token = all_tokens.get("instagram")
    
    video_dict = {
        "id": video.id,
        "filename": video.filename,
        "path": video.path,
        "status": video.status,
        "generated_title": video.generated_title,
        "custom_settings": video.custom_settings or {},
        "error": video.error,
        "scheduled_time": video.scheduled_time.isoformat() if video.scheduled_time else None,
        "file_size_bytes": video.file_size_bytes,
        "tokens_required": video.tokens_required,
        "tokens_consumed": video.tokens_consumed or 0
    }
    
    # Add upload progress from Redis if available
    upload_progress = get_upload_progress(user_id, video.id)
    if upload_progress is not None:
        video_dict['upload_progress'] = upload_progress
    
    # Add platform-specific progress from Redis for each enabled platform
    platform_progress = {}
    for platform_name in ["youtube", "tiktok", "instagram"]:
        enabled_key = f"{platform_name}_enabled"
        is_enabled = dest_settings.get(enabled_key, False)
        has_token = all_tokens.get(platform_name) is not None
        if is_enabled and has_token:
            progress = get_platform_upload_progress(user_id, video.id, platform_name)
            if progress is not None:
                platform_progress[platform_name] = progress
    
    if platform_progress:
        video_dict['platform_progress'] = platform_progress
    
    filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
    
    # Compute YouTube title for display (DRY - shared helper function)
    custom_settings = video.custom_settings or {}
    youtube_title = get_video_title(
        video=video,
        custom_settings=custom_settings,
        destination_settings=youtube_settings,
        global_settings=global_settings,
        filename_no_ext=filename_no_ext,
        template_key='title_template'
    )
    
    # Enforce YouTube's 100 character limit
    video_dict['youtube_title'] = youtube_title[:100] if len(youtube_title) > 100 else youtube_title
    video_dict['title_too_long'] = len(youtube_title) > 100
    video_dict['title_original_length'] = len(youtube_title)
    
    # Compute upload properties
    upload_props = {}
    
    # YouTube properties
    if dest_settings.get("youtube_enabled") and youtube_token:
        upload_props['youtube'] = {
            'title': video_dict['youtube_title'],
            'visibility': custom_settings.get('visibility', youtube_settings.get('visibility', 'private')),
            'made_for_kids': custom_settings.get('made_for_kids', youtube_settings.get('made_for_kids', False)),
        }
        
        # Description (DRY - shared helper function)
        upload_props['youtube']['description'] = get_video_description(
            video=video,
            custom_settings=custom_settings,
            destination_settings=youtube_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='description_template',
            default=''
        )
        
        # Tags
        if 'tags' in custom_settings:
            upload_props['youtube']['tags'] = custom_settings['tags']
        else:
            tags_template = youtube_settings.get('tags_template', '')
            upload_props['youtube']['tags'] = replace_template_placeholders(
                tags_template, filename_no_ext, global_settings.get('wordbank', [])
            ) if tags_template else ''
    
    # TikTok properties for display (DRY - shared helper function)
    if dest_settings.get("tiktok_enabled") and tiktok_token:
        tiktok_title = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=tiktok_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='title_template'
        )
        
        upload_props['tiktok'] = {
            'title': tiktok_title[:2200] if len(tiktok_title) > 2200 else tiktok_title,
            'privacy_level': custom_settings.get('privacy_level', tiktok_settings.get('privacy_level', '')),
            'allow_comments': custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', False)),
            'allow_duet': custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', False)),
            'allow_stitch': custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', False)),
            'commercial_content_disclosure': custom_settings.get('commercial_content_disclosure', tiktok_settings.get('commercial_content_disclosure', False)),
            'commercial_content_your_brand': custom_settings.get('commercial_content_your_brand', tiktok_settings.get('commercial_content_your_brand', False)),
            'commercial_content_branded': custom_settings.get('commercial_content_branded', tiktok_settings.get('commercial_content_branded', False))
        }
        video_dict['tiktok_title'] = tiktok_title[:2200] if len(tiktok_title) > 2200 else tiktok_title
    else:
        video_dict['tiktok_title'] = None
    
    # Instagram properties for display (DRY - shared helper function)
    if dest_settings.get("instagram_enabled") and instagram_token:
        # Caption (uses caption_template instead of title_template)
        caption = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=instagram_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='caption_template'
        )
        
        upload_props['instagram'] = {
            'caption': caption[:2200] if len(caption) > 2200 else caption,
            'disable_comments': custom_settings.get('disable_comments', instagram_settings.get('disable_comments', False)),
            'disable_likes': custom_settings.get('disable_likes', instagram_settings.get('disable_likes', False)),
            'media_type': custom_settings.get('media_type', instagram_settings.get('media_type', 'REELS')),
            'share_to_feed': custom_settings.get('share_to_feed', instagram_settings.get('share_to_feed', True)),
            'cover_url': custom_settings.get('cover_url', instagram_settings.get('cover_url', ''))
            # 'audio_name': custom_settings.get('audio_name', instagram_settings.get('audio_name', ''))  # Commented out - removed Audio Name feature
        }
        video_dict['instagram_caption'] = caption[:2200] if len(caption) > 2200 else caption
    else:
        video_dict['instagram_caption'] = None
    
    video_dict['upload_properties'] = upload_props
    
    # Add platform upload statuses (for UI indicators)
    platform_statuses = get_platform_statuses(video, dest_settings, all_tokens)
    video_dict['platform_statuses'] = platform_statuses
    
    # Add TikTok publish status if available
    tiktok_publish_id = custom_settings.get("tiktok_publish_id")
    if tiktok_publish_id and tiktok_token:
        # Try to fetch current status (non-blocking - if it fails, we'll get it on next poll)
        try:
            status_data = fetch_tiktok_publish_status(user_id, tiktok_publish_id, db=None)
            if status_data:
                video_dict['tiktok_publish_status'] = status_data.get("status", "UNKNOWN")
                if status_data.get("fail_reason"):
                    video_dict['tiktok_publish_error'] = status_data.get("fail_reason")
        except Exception:
            # If fetch fails, don't block the response - background task will update it
            pass
    
    return video_dict


def check_upload_success(video: Video, dest_name: str) -> bool:
    """Check if upload to a destination succeeded based on video state (DRY, extensible)
    
    Args:
        video: Video object to check
        dest_name: Destination name (youtube, tiktok, instagram)
        
    Returns:
        True if upload succeeded, False otherwise
    """
    config = PLATFORM_CONFIG.get(dest_name)
    if not config:
        return False
    
    custom_settings = video.custom_settings or {}
    id_keys = config['id_keys']
    # Check if any ID key exists and has a value
    return any(bool(custom_settings.get(key)) for key in id_keys)


def get_platform_statuses(video: Video, dest_settings: Dict[str, Any], all_tokens: Dict[str, Optional[OAuthToken]]) -> Dict[str, Any]:
    """Get upload status and specific error for each enabled platform (DRY, extensible)
    
    Reads from stored platform_statuses in custom_settings. Returns "not_enabled" for
    platforms that are not enabled or don't have tokens.
    
    Args:
        video: Video object to check
        dest_settings: Destination settings dict
        all_tokens: All OAuth tokens dict
        
    Returns:
        Dictionary mapping platform names to dict with 'status' and 'error' keys:
        - status: 'success', 'failed', 'pending', 'uploading', 'cancelled', or 'not_enabled'
        - error: Platform-specific error message (None if no error)
    """
    custom_settings = video.custom_settings or {}
    stored_platform_statuses = custom_settings.get("platform_statuses", {})
    platform_statuses = {}
    
    # Process each platform using configuration
    for platform_name, config in PLATFORM_CONFIG.items():
        enabled_key = config['enabled_key']
        
        is_enabled = dest_settings.get(enabled_key, False)
        has_token = all_tokens.get(platform_name) is not None
        
        if not is_enabled or not has_token:
            platform_statuses[platform_name] = {"status": "not_enabled", "error": None}
            continue
        
        # Get stored status for this platform (defaults to pending if not found)
        stored_status = stored_platform_statuses.get(platform_name, {"status": "pending", "error": None})
        platform_statuses[platform_name] = {
            "status": stored_status.get("status", "pending"),
            "error": stored_status.get("error")
        }
    
    return platform_statuses


def get_platform_status(video: Video, platform: str) -> Dict[str, Any]:
    """Get status for a specific platform (requires platform_statuses to exist - no fallback)
    
    Args:
        video: Video object
        platform: Platform name (youtube, tiktok, instagram)
        
    Returns:
        Dictionary with 'status', 'error', and 'updated_at' keys
    """
    platform_statuses = video.custom_settings.get("platform_statuses", {})
    return platform_statuses.get(platform, {"status": "pending", "error": None, "updated_at": None})


def get_all_platform_statuses(video: Video) -> Dict[str, Dict[str, Any]]:
    """Get all platform statuses from video
    
    Args:
        video: Video object
        
    Returns:
        Dictionary mapping platform names to status dicts
    """
    return video.custom_settings.get("platform_statuses", {})


def get_upload_state(video: Video, user_id: int, enabled_destinations: List[str]) -> Dict[str, Any]:
    """Get current upload state (R2 and/or destinations)
    
    Checks both R2 upload progress from Redis and platform statuses to determine
    what uploads are currently in progress. This provides a unified view of upload state.
    
    Args:
        video: Video object
        user_id: User ID for Redis progress lookup
        enabled_destinations: List of enabled destination names
        
    Returns:
        Dictionary with:
            - 'has_r2_upload': bool - True if R2 upload is in progress (< 100%)
            - 'has_destination_uploads': bool - True if any destination is uploading/pending
            - 'active_platforms': List[str] - Platforms with status 'uploading' or 'pending'
            - 'r2_progress': Optional[int] - R2 upload progress (0-100) or None
    """
    # Check R2 upload progress
    r2_progress = get_upload_progress(user_id, video.id)
    
    # Check if any platform has progress (indicates destination uploads have started)
    has_platform_progress = any(
        get_platform_upload_progress(user_id, video.id, platform) is not None
        for platform in ["youtube", "tiktok", "instagram"]
    )
    
    # R2 upload is in progress if we have progress < 100% and no platform progress yet
    has_r2_upload = r2_progress is not None and r2_progress < 100 and not has_platform_progress
    
    # Check platform statuses for active destination uploads
    platform_statuses = get_all_platform_statuses(video)
    active_platforms = []
    for platform in enabled_destinations:
        platform_status = platform_statuses.get(platform, {}).get("status", "pending")
        if platform_status in ["uploading", "pending"]:
            active_platforms.append(platform)
    
    has_destination_uploads = len(active_platforms) > 0
    
    return {
        "has_r2_upload": has_r2_upload,
        "has_destination_uploads": has_destination_uploads,
        "active_platforms": active_platforms,
        "r2_progress": r2_progress
    }


def is_video_cancellable(video: Video, enabled_destinations: List[str], user_id: int) -> bool:
    """Check if video has any active uploads that can be cancelled
    
    A video is cancellable if:
    - R2 upload is in progress (< 100%)
    - OR any enabled platform has status "uploading" or "pending"
    
    This works regardless of global status (handles "partial" correctly).
    A video with status "partial" can still have active uploads if some platforms
    succeeded while others are still uploading.
    
    Args:
        video: Video object
        enabled_destinations: List of enabled destination names
        user_id: User ID for Redis progress lookup
        
    Returns:
        True if video can be cancelled, False otherwise
    """
    upload_state = get_upload_state(video, user_id, enabled_destinations)
    return upload_state['has_r2_upload'] or upload_state['has_destination_uploads']


def compute_global_status(video: Video, enabled_destinations: List[str]) -> str:
    """Compute global status from platform statuses
    
    Args:
        video: Video object
        enabled_destinations: List of enabled destination names
        
    Returns:
        Global status string: 'pending', 'uploading', 'uploaded', 'failed', 'partial', or 'cancelled'
    """
    platform_statuses = get_all_platform_statuses(video)
    enabled_statuses = [
        platform_statuses.get(platform, {}).get("status", "pending")
        for platform in enabled_destinations
    ]
    
    if not enabled_statuses:
        return "pending"
    
    if all(s == "success" for s in enabled_statuses):
        return "uploaded"
    elif any(s == "uploading" for s in enabled_statuses):
        return "uploading"
    elif any(s == "pending" for s in enabled_statuses):
        # If any destination is still pending, status is "uploading" (not "partial")
        # This prevents premature status changes when some destinations succeed but others haven't started
        return "uploading"
    elif all(s == "failed" for s in enabled_statuses):
        return "failed"
    elif all(s == "cancelled" for s in enabled_statuses):
        return "cancelled"
    elif any(s == "success" for s in enabled_statuses):
        # Partial success: some succeeded, others failed (no pending or uploading)
        return "partial"
    else:
        return "pending"


async def set_platform_status(
    video_id: int,
    user_id: int,
    platform: str,
    status: str,
    error: Optional[str] = None,
    db: Session = None
) -> None:
    """Set status for a platform and update global status
    
    Args:
        video_id: Video ID
        user_id: User ID
        platform: Platform name (youtube, tiktok, instagram)
        status: Status string ('pending', 'uploading', 'success', 'failed', 'cancelled')
        error: Optional error message (required if status is 'failed')
        db: Database session (optional)
    """
    from app.db.session import SessionLocal
    from app.db.helpers import update_video, get_user_settings
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.event_service import publish_video_status_changed
    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        video = db.query(Video).filter(
            Video.id == video_id,
            Video.user_id == user_id
        ).first()
        
        if not video:
            return
        
        # Initialize custom_settings and platform_statuses if needed
        if video.custom_settings is None:
            video.custom_settings = {}
        if "platform_statuses" not in video.custom_settings:
            video.custom_settings["platform_statuses"] = {}
        
        # Update platform status
        video.custom_settings["platform_statuses"][platform] = {
            "status": status,
            "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Flag as modified so SQLAlchemy detects the change
        flag_modified(video, "custom_settings")
        
        # Get enabled destinations to compute global status
        dest_settings = get_user_settings(user_id, "destinations", db=db)
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        enabled_destinations = []
        for dest_name in ["youtube", "tiktok", "instagram"]:
            is_enabled = dest_settings.get(f"{dest_name}_enabled", False)
            has_token = all_tokens.get(dest_name) is not None
            if is_enabled and has_token:
                enabled_destinations.append(dest_name)
        
        # Compute and update global status
        old_status = video.status
        new_global_status = compute_global_status(video, enabled_destinations)
        
        # Update global status if it changed
        if old_status != new_global_status:
            video.status = new_global_status
            # Clear error if status is not failed
            if new_global_status != "failed":
                video.error = None
        
        db.commit()
        
        # Refresh video to get updated data
        db.refresh(video)
        
        # Publish WebSocket event with updated video data
        all_settings = get_all_user_settings(user_id, db=db)
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        video_dict = build_video_response(video, all_settings, all_tokens, user_id)
        await publish_video_status_changed(user_id, video_id, old_status, new_global_status, video_dict=video_dict)
        
    finally:
        if should_close:
            db.close()


def record_platform_error(video_id: int, user_id: int, platform: str, error_message: str, db: Session = None):
    """Record a platform-specific error in custom_settings (DRY, extensible)
    
    Args:
        video_id: Video ID
        user_id: User ID
        platform: Platform name (youtube, tiktok, instagram)
        error_message: Error message to record
        db: Database session (optional)
    """
    from app.db.session import SessionLocal
    from sqlalchemy.orm.attributes import flag_modified
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        video = db.query(Video).filter(
            Video.id == video_id,
            Video.user_id == user_id
        ).first()
        
        if not video:
            return
        
        # Initialize custom_settings and platform_errors if needed
        if video.custom_settings is None:
            video.custom_settings = {}
        if "platform_errors" not in video.custom_settings:
            video.custom_settings["platform_errors"] = {}
        
        # Record the error for this platform
        video.custom_settings["platform_errors"][platform] = error_message
        
        # Flag as modified so SQLAlchemy detects the change
        flag_modified(video, "custom_settings")
        
        db.commit()
    finally:
        if should_close:
            db.close()


def cleanup_video_file(video: Video) -> bool:
    """Delete video file from R2 after successful upload
    
    This is called after all destinations succeed. The database record
    is kept for history, but the R2 object is removed to save space.
    
    ROOT CAUSE FIX: Don't delete files if TikTok is using PULL_FROM_URL
    (has tiktok_publish_id but no tiktok_id yet) - TikTok still needs to download it.
    
    Args:
        video: Video object with R2 object key in path field
        
    Returns:
        True if cleanup succeeded or object already gone, False on error
    """
    try:
        # Check if TikTok is using PULL_FROM_URL and still downloading
        custom_settings = video.custom_settings or {}
        tiktok_publish_id = custom_settings.get("tiktok_publish_id")
        tiktok_id = custom_settings.get("tiktok_id")
        
        # If TikTok has publish_id but no video_id yet, it's still downloading via PULL_FROM_URL
        if tiktok_publish_id and not tiktok_id:
            upload_logger.debug(
                f"Skipping cleanup for {video.filename} - TikTok PULL_FROM_URL still in progress "
                f"(publish_id: {tiktok_publish_id}, waiting for tiktok_id)"
            )
            return True  # Don't delete yet, but return success
        
        # Delete from R2
        if not video.path:
            upload_logger.debug(f"Video {video.filename} has no R2 object key, nothing to clean up")
            return True
        
        from app.services.storage.r2_service import get_r2_service
        r2_service = get_r2_service()
        
        if r2_service.delete_object(video.path):
            upload_logger.info(f"Cleaned up video file from R2: {video.filename} (R2 key: {video.path})")
            return True
        else:
            upload_logger.debug(f"Video file already removed from R2 or doesn't exist: {video.filename}")
            return True
    except Exception as e:
        upload_logger.error(
            f"Failed to cleanup video file {video.filename}: {str(e)}",
            exc_info=True
        )
        return False


def get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe
    
    Args:
        video_path: Path to video file (local file path)
        
    Returns:
        Duration in seconds as float
        
    Raises:
        Exception: If ffprobe is not available or video cannot be analyzed
    """
    try:
        # Use ffprobe to get duration
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30.0
        )
        
        if result.returncode != 0:
            raise Exception(f"ffprobe failed: {result.stderr}")
        
        duration_str = result.stdout.strip()
        if not duration_str:
            raise Exception("ffprobe returned empty duration")
        
        duration = float(duration_str)
        if duration <= 0:
            raise Exception(f"Invalid duration: {duration}")
        
        return duration
        
    except FileNotFoundError:
        raise Exception("ffprobe not found. Please install ffmpeg to enable video duration validation.")
    except subprocess.TimeoutExpired:
        raise Exception("ffprobe timed out while analyzing video")
    except ValueError as e:
        raise Exception(f"Failed to parse video duration: {e}")
    except Exception as e:
        if "ffprobe" in str(e):
            raise
        raise Exception(f"Failed to get video duration: {e}")


def get_google_client_config():
    """Build Google OAuth client config from environment variables"""
    if not all([settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_PROJECT_ID]):
        return None
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "project_id": settings.GOOGLE_PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uris": []  # Will be set dynamically
        }
    }

