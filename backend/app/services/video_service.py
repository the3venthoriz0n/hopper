"""Video service - Orchestration of uploads/processing for YouTube, TikTok, and Instagram"""
import asyncio
import json
import logging
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from sqlalchemy.orm import Session

from app.core.config import (
    settings, TIKTOK_CREATOR_INFO_URL, TIKTOK_INIT_UPLOAD_URL,
    TIKTOK_STATUS_URL, TIKTOK_RATE_LIMIT_REQUESTS, TIKTOK_RATE_LIMIT_WINDOW,
    INSTAGRAM_GRAPH_API_BASE
)
from app.db.helpers import (
    get_user_videos, get_user_settings, get_all_oauth_tokens, get_oauth_token,
    oauth_token_to_credentials, credentials_to_oauth_token_data, save_oauth_token,
    check_token_expiration, delete_oauth_token, set_user_setting, update_video
)
from app.db.redis import (
    set_upload_progress, get_upload_progress, delete_upload_progress,
    increment_rate_limit, get_token_check_cooldown, set_token_check_cooldown,
    redis_client
)
from app.models.oauth_token import OAuthToken
from app.models.video import Video
from app.services.stripe_service import calculate_tokens_from_bytes
from app.services.token_service import check_tokens_available, get_token_balance, deduct_tokens
from app.utils.encryption import decrypt
from app.utils.templates import (
    replace_template_placeholders, get_video_title, get_video_description
)
from app.utils.video_tokens import generate_video_access_token

# Get loggers from app.main (they're defined there)
# We'll import them at runtime to avoid circular imports
logger = logging.getLogger(__name__)
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
tiktok_logger = logging.getLogger("tiktok")
youtube_logger = logging.getLogger("youtube")
instagram_logger = logging.getLogger("instagram")

# Constants for redis locking
TOKEN_REFRESH_LOCK_TIMEOUT = 10  # seconds
DATA_REFRESH_COOLDOWN = 60  # seconds


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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
        "tokens_consumed": video.tokens_consumed or 0
    }
    
    # Add upload progress from Redis if available
    upload_progress = get_upload_progress(user_id, video.id)
    if upload_progress is not None:
        video_dict['upload_progress'] = upload_progress
    
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
            'location_id': custom_settings.get('location_id', instagram_settings.get('location_id', '')),
            'disable_comments': instagram_settings.get('disable_comments', False),
            'disable_likes': instagram_settings.get('disable_likes', False)
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
    """Check if upload to a destination succeeded based on video state
    
    Args:
        video: Video object to check
        dest_name: Destination name (youtube, tiktok, instagram)
        
    Returns:
        True if upload succeeded, False otherwise
    """
    custom_settings = video.custom_settings or {}
    
    if dest_name == 'youtube':
        return bool(custom_settings.get('youtube_id'))
    elif dest_name == 'tiktok':
        return bool(custom_settings.get('tiktok_id') or custom_settings.get('tiktok_publish_id'))
    elif dest_name == 'instagram':
        return bool(custom_settings.get('instagram_id') or custom_settings.get('instagram_container_id'))
    return False


def get_platform_statuses(video: Video, dest_settings: Dict[str, Any], all_tokens: Dict[str, Optional[OAuthToken]]) -> Dict[str, str]:
    """Get upload status for each enabled platform
    
    Args:
        video: Video object to check
        dest_settings: Destination settings dict
        all_tokens: All OAuth tokens dict
        
    Returns:
        Dictionary mapping platform names to status: 'success', 'failed', 'pending', or 'not_enabled'
    """
    custom_settings = video.custom_settings or {}
    platform_statuses = {}
    error = (video.error or '').lower()
    
    # Check each platform
    platforms = {
        'youtube': ('youtube_enabled', 'youtube_id', ['youtube', 'google']),
        'tiktok': ('tiktok_enabled', ('tiktok_id', 'tiktok_publish_id'), ['tiktok']),
        'instagram': ('instagram_enabled', ('instagram_id', 'instagram_container_id'), ['instagram', 'facebook'])
    }
    
    for platform_name, (enabled_key, id_keys, error_keywords) in platforms.items():
        is_enabled = dest_settings.get(enabled_key, False)
        has_token = all_tokens.get(platform_name) is not None
        
        if not is_enabled or not has_token:
            platform_statuses[platform_name] = 'not_enabled'
            continue
        
        # Check if upload succeeded (has platform ID)
        if platform_name == 'youtube':
            has_id = bool(custom_settings.get(id_keys))
        elif platform_name == 'tiktok':
            has_id = bool(custom_settings.get(id_keys[0]) or custom_settings.get(id_keys[1]))
        else:  # instagram
            has_id = bool(custom_settings.get(id_keys[0]) or custom_settings.get(id_keys[1]))
        
        if has_id:
            platform_statuses[platform_name] = 'success'
        elif video.status == 'failed':
            # Check if error mentions this platform
            error_mentions_platform = any(keyword in error for keyword in error_keywords)
            if error_mentions_platform:
                platform_statuses[platform_name] = 'failed'
            else:
                # Error doesn't mention this platform - might be pending or failed silently
                # Check if other platforms succeeded (partial success scenario)
                other_platforms_succeeded = any(
                    status == 'success' for p, status in platform_statuses.items() if p != platform_name
                )
                if other_platforms_succeeded:
                    # Other platforms succeeded, this one likely failed
                    platform_statuses[platform_name] = 'failed'
                else:
                    # Still pending or not attempted yet
                    platform_statuses[platform_name] = 'pending'
        elif video.status == 'uploaded' or video.status == 'completed':
            # Video marked as uploaded/completed but no ID for this platform
            # This means it failed for this platform (partial success scenario)
            platform_statuses[platform_name] = 'failed'
        else:
            # Still pending
            platform_statuses[platform_name] = 'pending'
    
    return platform_statuses


def cleanup_video_file(video: Video) -> bool:
    """Delete video file from disk after successful upload
    
    This is called after all destinations succeed. The database record
    is kept for history, but the physical file is removed to save space.
    
    ROOT CAUSE FIX: Don't delete files if TikTok is using PULL_FROM_URL
    (has tiktok_publish_id but no tiktok_id yet) - TikTok still needs to download it.
    
    Args:
        video: Video object with path to file
        
    Returns:
        True if cleanup succeeded or file already gone, False on error
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
        
        # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
        video_path = Path(video.path).resolve()
        if video_path.exists():
            video_path.unlink()
            upload_logger.info(f"Cleaned up video file: {video.filename} ({video_path})")
            return True
        else:
            upload_logger.debug(f"Video file already removed: {video.filename}")
            return True
    except Exception as e:
        upload_logger.error(f"Failed to cleanup video file {video.filename}: {str(e)}")
        return False


def get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe
    
    Args:
        video_path: Path to video file
        
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


# ============================================================================
# TIKTOK HELPER FUNCTIONS
# ============================================================================

def check_tiktok_rate_limit(session_id: str = None, user_id: int = None):
    """Check if TikTok API rate limit is exceeded (6 requests per minute) using Redis"""
    # Use session_id if available, otherwise use user_id
    if session_id:
        identifier = f"tiktok:{session_id}"
    elif user_id:
        identifier = f"tiktok:user:{user_id}"
    else:
        raise Exception("Either session_id or user_id must be provided for TikTok rate limiting")
    
    # Increment counter in Redis (with TTL)
    current_count = increment_rate_limit(identifier, TIKTOK_RATE_LIMIT_WINDOW)
    
    # Check if limit exceeded
    if current_count > TIKTOK_RATE_LIMIT_REQUESTS:
        # Calculate wait time (approximate, since we're using fixed window)
        wait_time = TIKTOK_RATE_LIMIT_WINDOW
        raise Exception(f"TikTok rate limit exceeded. Wait {wait_time}s before trying again.")


@contextmanager
def _distributed_lock(lock_key: str, timeout: int = TOKEN_REFRESH_LOCK_TIMEOUT):
    """Distributed lock using Redis to prevent race conditions
    
    Internal helper - not meant to be called directly from other modules.
    """
    lock_value = f"{time.time()}"
    acquired = False
    
    try:
        acquired = redis_client.set(lock_key, lock_value, nx=True, ex=timeout)
        yield acquired
    finally:
        if acquired:
            try:
                redis_client.delete(lock_key)
            except Exception as e:
                tiktok_logger.debug(f"Failed to release lock {lock_key}: {e}")


def _parse_and_save_tiktok_token_response(
    user_id: int,
    token_json: Dict[str, Any],
    db: Session,
    preserve_account_info: bool = True
) -> str:
    """Parse TikTok token response and save to database
    
    Follows TikTok OAuth documentation:
    https://developers.tiktok.com/doc/oauth-user-access-token-management
    
    Args:
        user_id: User ID
        token_json: Token response JSON from TikTok API
        db: Database session
        preserve_account_info: If True, preserve existing account info in extra_data
        
    Returns:
        str: Decrypted access token
        
    Raises:
        Exception: If required fields are missing
    """
    # Validate required fields per TikTok docs
    if "access_token" not in token_json:
        raise Exception(f"Missing access_token in TikTok response. Keys: {list(token_json.keys())}")
    
    # Extract tokens - CRITICAL: Always use new refresh_token if provided (per TikTok docs)
    access_token = token_json["access_token"]
    new_refresh_token = token_json.get("refresh_token")  # May be different than old one
    expires_in = token_json.get("expires_in")  # 24 hours (86400 seconds)
    refresh_expires_in = token_json.get("refresh_expires_in")  # 365 days (31536000 seconds)
    
    # Calculate expiration times
    expires_at = None
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    
    # Calculate refresh token expiration and store in extra_data
    refresh_expires_at = None
    if refresh_expires_in:
        refresh_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(refresh_expires_in))
    
    # Build extra_data with all TikTok response fields per docs
    new_extra_data = {
        "open_id": token_json.get("open_id"),
        "scope": token_json.get("scope"),
        "token_type": token_json.get("token_type"),
        "refresh_expires_in": refresh_expires_in,
        "refresh_expires_at": refresh_expires_at.isoformat() if refresh_expires_at else None
    }
    
    # ROOT CAUSE FIX: Always preserve existing extra_data to prevent overwriting legacy data
    # Get existing token to merge with new OAuth fields
    existing_token = get_oauth_token(user_id, "tiktok", db=db)
    if existing_token and existing_token.extra_data:
        # Start with existing extra_data to preserve all legacy fields
        extra_data = existing_token.extra_data.copy()
        
        # ROOT CAUSE FIX: Explicitly preserve open_id before update (critical for TikTok API calls)
        preserved_open_id = extra_data.get("open_id")
        
        # Update with new OAuth response fields (these take precedence)
        extra_data.update(new_extra_data)
        
        # ROOT CAUSE FIX: Restore open_id if new response doesn't have it or has None/empty
        if not extra_data.get("open_id") and preserved_open_id:
            extra_data["open_id"] = preserved_open_id
        
        # If preserve_account_info is False (first login), don't preserve account-specific fields
        if not preserve_account_info:
            # Remove account-specific fields so they can be refreshed from API
            for key in ["display_name", "username", "avatar_url", "creator_info", "last_data_refresh"]:
                extra_data.pop(key, None)
    else:
        # No existing token, use new extra_data as-is
        extra_data = new_extra_data
    
    # Save to database
    # ROOT CAUSE FIX: Pass None for refresh_token if TikTok doesn't provide a new one
    save_oauth_token(
        user_id=user_id,
        platform="tiktok",
        access_token=access_token,
        refresh_token=new_refresh_token,  # New token if provided, None if not (will preserve existing)
        expires_at=expires_at,
        extra_data=extra_data,
        db=db
    )
    
    tiktok_logger.debug(
        f"Saved TikTok token for user {user_id}: "
        f"access_token expires in {expires_in}s, "
        f"refresh_token expires in {refresh_expires_in}s"
    )
    
    return access_token


def _check_refresh_token_expiration(user_id: int, db: Session) -> Optional[str]:
    """Check if refresh token is expired and return decrypted token if valid
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        str: Decrypted refresh token if valid, None if expired or missing
    """
    token = get_oauth_token(user_id, "tiktok", db=db)
    if not token or not token.refresh_token:
        return None
    
    # Check refresh token expiration from extra_data
    if token.extra_data and token.extra_data.get("refresh_expires_at"):
        try:
            refresh_expires_at = datetime.fromisoformat(token.extra_data["refresh_expires_at"])
            if refresh_expires_at < datetime.now(timezone.utc):
                tiktok_logger.warning(
                    f"TikTok refresh token expired for user {user_id}. "
                    f"Expired at: {refresh_expires_at}"
                )
                # Clear expired token
                delete_oauth_token(user_id, "tiktok", db=db)
                set_user_setting(user_id, "destinations", "tiktok_enabled", False, db=db)
                return None
        except (ValueError, TypeError) as e:
            tiktok_logger.warning(f"Could not parse refresh_expires_at for user {user_id}: {e}")
    
    # Decrypt and return refresh token
    refresh_token = decrypt(token.refresh_token)
    return refresh_token if refresh_token else None


def refresh_tiktok_token(user_id: int, refresh_token: str, db: Session) -> str:
    """Refresh TikTok access token using refresh token
    
    Follows TikTok OAuth documentation:
    https://developers.tiktok.com/doc/oauth-user-access-token-management
    
    Features:
    - Distributed locking to prevent race conditions
    - Checks refresh token expiration before attempting refresh
    - Always uses new refresh_token if TikTok provides one (per docs)
    - Clears invalid tokens on invalid_grant
    
    Args:
        user_id: User ID
        refresh_token: Refresh token (decrypted) - may be None to check from DB
        db: Database session
        
    Returns:
        str: New access token (decrypted)
        
    Raises:
        Exception: If refresh fails
    """
    lock_key = f"tiktok_token_refresh:{user_id}"
    
    with _distributed_lock(lock_key) as acquired:
        if not acquired:
            # Another process is refreshing - wait and get result
            tiktok_logger.info(f"Waiting for concurrent token refresh (user {user_id})")
            time.sleep(1.5)
            
            # Get refreshed token from database
            fresh_token = get_oauth_token(user_id, "tiktok", db=db)
            if fresh_token:
                fresh_access = decrypt(fresh_token.access_token)
                if fresh_access:
                    tiktok_logger.info(f"Using token refreshed by concurrent process (user {user_id})")
                    return fresh_access
            
            # If no valid token after wait, raise exception
            tiktok_logger.error(f"Concurrent refresh failed to produce valid token (user {user_id})")
            raise Exception("Token refresh in progress failed. Please try again.")
        
        # ROOT CAUSE FIX: Double-Check Locking - Refresh DB session to get latest data
        db.expire_all()
        
        # Re-fetch token from DB to see if it was already refreshed while we waited for lock
        from app.models.oauth_token import OAuthToken
        current_token = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == "tiktok"
        ).first()
        
        # ROOT CAUSE FIX: Explicitly refresh the token object to ensure we have latest data
        if current_token:
            db.refresh(current_token)
        
        if current_token:
            # ROOT CAUSE FIX: Check if token was already refreshed by checking expires_at
            now = datetime.now(timezone.utc)
            if current_token.expires_at:
                time_until_expiry = current_token.expires_at - now
                if time_until_expiry > timedelta(minutes=30):
                    # Token was already refreshed - return it without calling TikTok API
                    tiktok_logger.info(
                        f"Token already refreshed by another process (user {user_id}). "
                        f"Expires in {time_until_expiry.total_seconds() / 3600:.1f} hours"
                    )
                    new_access = decrypt(current_token.access_token)
                    if new_access:
                        return new_access
            
            # Also check if refresh_token changed (backup check)
            current_refresh = decrypt(current_token.refresh_token) if current_token.refresh_token else None
            if current_refresh and refresh_token and current_refresh != refresh_token:
                # Token was refreshed between check and lock acquisition
                tiktok_logger.info(f"Token already refreshed by another process (refresh_token changed, user {user_id})")
                new_access = decrypt(current_token.access_token)
                if new_access:
                    return new_access
        
        # Get refresh token if not provided
        if not refresh_token:
            refresh_token = _check_refresh_token_expiration(user_id, db)
            if not refresh_token:
                raise Exception("No valid refresh token available. Please reconnect your TikTok account.")
        
        # Check refresh token expiration before attempting refresh
        token = get_oauth_token(user_id, "tiktok", db=db)
        if token and token.extra_data and token.extra_data.get("refresh_expires_at"):
            try:
                refresh_expires_at = datetime.fromisoformat(token.extra_data["refresh_expires_at"])
                if refresh_expires_at < datetime.now(timezone.utc):
                    tiktok_logger.warning(
                        f"TikTok refresh token expired for user {user_id}. "
                        f"Expired at: {refresh_expires_at}"
                    )
                    delete_oauth_token(user_id, "tiktok", db=db)
                    set_user_setting(user_id, "destinations", "tiktok_enabled", False, db=db)
                    raise Exception("TikTok refresh token has expired. Please reconnect your TikTok account.")
            except (ValueError, TypeError):
                pass  # If we can't parse, try refresh anyway
        
        # Perform the actual refresh per TikTok docs
        tiktok_logger.info(f"Refreshing TikTok token (user {user_id})")
        
        try:
            response = httpx.post(
                settings.TIKTOK_TOKEN_URL,
                data={
                    "client_key": settings.TIKTOK_CLIENT_KEY,
                    "client_secret": settings.TIKTOK_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0
            )
            
            # Parse error response
            if response.status_code != 200:
                error_data = {}
                try:
                    if response.text:
                        error_data = response.json()
                except Exception:
                    error_data = {"error": response.text[:200] if response.text else "Unknown error"}
                
                # Handle both string and dict error formats
                error_obj = error_data.get("error", {})
                if isinstance(error_obj, str):
                    error_code = "unknown"
                    error_msg = error_obj
                else:
                    error_code = error_obj.get("code", "unknown") if isinstance(error_obj, dict) else "unknown"
                    error_msg = error_obj.get("message", response.text[:200] if response.text else "Unknown error") if isinstance(error_obj, dict) else (response.text[:200] if response.text else "Unknown error")
                
                tiktok_logger.error(
                    f"Token refresh failed (user {user_id}): {error_code} - {error_msg}"
                )
                
                if error_code == "invalid_grant" or "invalid_grant" in str(error_msg).lower():
                    # Clear invalid refresh token immediately to prevent retry loops
                    tiktok_logger.warning(
                        f"TikTok refresh token is invalid (invalid_grant) for user {user_id}. "
                        f"Clearing token and disabling TikTok to prevent retry loops."
                    )
                    try:
                        delete_oauth_token(user_id, "tiktok", db=db)
                        set_user_setting(user_id, "destinations", "tiktok_enabled", False, db=db)
                        tiktok_logger.info(f"Cleared invalid TikTok token and disabled TikTok for user {user_id}")
                    except Exception as clear_err:
                        tiktok_logger.error(f"Failed to clear invalid token for user {user_id}: {clear_err}")
                    
                    raise Exception("TikTok refresh token is expired or invalid. Please reconnect your TikTok account.")
                
                raise Exception(f"Token refresh failed: {error_code} - {error_msg}")
            
            token_json = response.json()
            
            # Check for error in response body
            if "error" in token_json:
                error_obj = token_json.get("error", {})
                if isinstance(error_obj, str):
                    error_code = "unknown"
                    error_msg = error_obj
                else:
                    error_code = error_obj.get("code", "unknown") if isinstance(error_obj, dict) else "unknown"
                    error_msg = error_obj.get("message", "Unknown error") if isinstance(error_obj, dict) else "Unknown error"
                
                tiktok_logger.error(
                    f"Token refresh returned error (user {user_id}): {error_code} - {error_msg}"
                )
                
                if error_code == "invalid_grant" or "invalid_grant" in str(error_msg).lower():
                    # Clear invalid refresh token immediately to prevent retry loops
                    tiktok_logger.warning(
                        f"TikTok refresh token is invalid (invalid_grant) for user {user_id}. "
                        f"Clearing token and disabling TikTok to prevent retry loops."
                    )
                    try:
                        delete_oauth_token(user_id, "tiktok", db=db)
                        set_user_setting(user_id, "destinations", "tiktok_enabled", False, db=db)
                        tiktok_logger.info(f"Cleared invalid TikTok token and disabled TikTok for user {user_id}")
                    except Exception as clear_err:
                        tiktok_logger.error(f"Failed to clear invalid token for user {user_id}: {clear_err}")
                    
                    raise Exception(f"TikTok token refresh failed (invalid_grant): {error_msg}. Please reconnect your TikTok account.")
                
                raise Exception(f"Token refresh failed: {error_code} - {error_msg}")
            
            # Parse and save token response using DRY helper
            new_access_token = _parse_and_save_tiktok_token_response(
                user_id=user_id,
                token_json=token_json,
                db=db,
                preserve_account_info=True
            )
            
            tiktok_logger.info(f"Successfully refreshed token (user {user_id})")
            return new_access_token
            
        except Exception as e:
            # If it's already our custom exception, re-raise it
            if "expired or invalid" in str(e).lower() or "reconnect" in str(e).lower() or "invalid_grant" in str(e).lower():
                raise
            
            # For other exceptions, log and re-raise
            tiktok_logger.error(f"Exception during token refresh (user {user_id}): {str(e)}")
            raise Exception(f"Token refresh failed: {str(e)}")


def get_tiktok_creator_info(access_token: str):
    """Query TikTok creator info
    
    Args:
        access_token: Access token (decrypted)
        
    Returns:
        dict: Creator info data
        
    Raises:
        Exception: If API call fails
    """
    if not access_token or not access_token.strip():
        raise Exception("No TikTok access token or token is empty")
    
    response = httpx.post(
        TIKTOK_CREATOR_INFO_URL,
        headers={
            "Authorization": f"Bearer {access_token.strip()}",
            "Content-Type": "application/json; charset=UTF-8"
        },
        json={},
        timeout=30.0
    )
    
    if response.status_code != 200:
        error = response.json().get("error", {})
        raise Exception(
            f"Failed to query creator info: {error.get('code', 'unknown')} - "
            f"{error.get('message', response.text)}"
        )
    
    response_json = response.json()
    tiktok_logger.debug(f"TikTok creator_info API response: {response_json}")
    
    creator_info = response_json.get("data", {})
    tiktok_logger.debug(f"Extracted creator_info: {creator_info}")
    
    return creator_info


def _ensure_fresh_token(user_id: int, db: Session) -> Optional[str]:
    """Internal helper to ensure user has a fresh access token
    
    Automatically refreshes if needed using distributed locking.
    
    ROOT CAUSE FIX: For TikTok, check access token expiration (24 hours) separately
    from refresh token expiration (365 days). check_token_expiration only checks
    refresh token expiration for TikTok, so we need to check access token expiration here.
    
    Implements:
    - 30-minute grace period: Only refresh if token expires within 30 minutes
    - 30-second cooldown: Prevents thundering herd from multiple simultaneous requests
    """
    token_obj = get_oauth_token(user_id, "tiktok", db=db)
    if not token_obj:
        return None
    
    access_token = decrypt(token_obj.access_token)
    if not access_token:
        return None
    
    # ROOT CAUSE FIX: UI-Driven Sync Check - 30-second cooldown to prevent thundering herd
    if get_token_check_cooldown(user_id, "tiktok"):
        tiktok_logger.debug(f"Token check in cooldown, using cached token (user {user_id})")
        return access_token
    
    # ROOT CAUSE FIX: For TikTok, access tokens expire every 24 hours and must be refreshed
    now = datetime.now(timezone.utc)
    access_token_expired = False
    if token_obj.expires_at:
        # ROOT CAUSE FIX: 30-minute grace period - only refresh if token expires within 30 minutes
        buffer = timedelta(minutes=30)
        access_token_expired = token_obj.expires_at < (now + buffer)
    
    # Also check refresh token expiration (for connection status)
    token_expiry = check_token_expiration(token_obj)
    refresh_token_expired = token_expiry.get("expired", False)
    
    # Refresh if access token is expired/expiring OR refresh token is expired
    needs_refresh = access_token_expired or refresh_token_expired
    
    if not needs_refresh:
        # Set cooldown to prevent other requests from checking expiration unnecessarily
        set_token_check_cooldown(user_id, "tiktok", ttl=30)
        return access_token
    
    # Token needs refresh - set cooldown before attempting refresh
    set_token_check_cooldown(user_id, "tiktok", ttl=30)
    
    if not token_obj.refresh_token:
        tiktok_logger.warning(f"Token expired but no refresh token (user {user_id})")
        return None
    
    refresh_token = decrypt(token_obj.refresh_token)
    if not refresh_token:
        tiktok_logger.warning(f"Failed to decrypt refresh token (user {user_id})")
        return None
    
    # Refresh with distributed locking (via public API)
    try:
        new_access_token = refresh_tiktok_token(user_id, refresh_token, db)
        return new_access_token
    except Exception as e:
        tiktok_logger.warning(f"Token refresh failed (user {user_id}): {str(e)}")
        return None


def _fetch_creator_info_safe(access_token: str, user_id: int, db: Session = None) -> Optional[Dict]:
    """Internal helper to fetch creator info with error handling
    
    ROOT CAUSE FIX: Add retry logic to handle token invalidation race conditions.
    If the token is invalid (likely due to concurrent refresh), re-fetch from DB and retry once.
    
    Args:
        access_token: Access token to use (may be stale)
        user_id: User ID
        db: Database session (optional, will create if needed)
    
    Returns:
        Dict with creator info, or None on failure
    """
    should_close_db = False
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close_db = True
    
    try:
        # First attempt with provided token
        try:
            return get_tiktok_creator_info(access_token)
        except Exception as e:
            error_msg = str(e).lower()
            # Check if error is due to invalid token (race condition with concurrent refresh)
            is_token_error = (
                "access_token_invalid" in error_msg or
                "invalid" in error_msg and "token" in error_msg or
                "401" in error_msg or
                "unauthorized" in error_msg
            )
            
            if not is_token_error:
                # Not a token error, log and return None
                tiktok_logger.warning(f"Failed to fetch creator info (user {user_id}): {str(e)}")
                return None
            
            # ROOT CAUSE FIX: Token error detected - likely stale token due to concurrent refresh
            # Re-fetch fresh token from DB and retry once
            tiktok_logger.info(f"Token invalid during creator info fetch (user {user_id}), re-fetching from DB and retrying...")
            
            # Get fresh token from DB (will auto-refresh if needed)
            fresh_access_token = _ensure_fresh_token(user_id, db)
            if not fresh_access_token:
                tiktok_logger.warning(f"Could not get fresh token for retry (user {user_id})")
                return None
            
            # Retry with fresh token
            try:
                return get_tiktok_creator_info(fresh_access_token)
            except Exception as retry_error:
                tiktok_logger.warning(f"Retry failed to fetch creator info (user {user_id}): {str(retry_error)}")
                return None
    finally:
        if should_close_db:
            db.close()


def fetch_tiktok_publish_status(user_id: int, publish_id: str, db: Session = None) -> Optional[Dict[str, Any]]:
    """Fetch TikTok publish status for a given publish_id
    
    Args:
        user_id: User ID
        publish_id: TikTok publish_id from the upload response
        db: Database session
        
    Returns:
        Dictionary with status information, or None if error
    """
    try:
        # Get TikTok access token
        tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
        if not tiktok_token:
            tiktok_logger.warning(f"No TikTok token for user {user_id} when fetching status for publish_id {publish_id}")
            return None
        
        access_token = decrypt(tiktok_token.access_token)
        if not access_token:
            tiktok_logger.warning(f"Failed to decrypt TikTok token for user {user_id}")
            return None
        
        # Check if token needs refresh
        if tiktok_token.expires_at and tiktok_token.expires_at < datetime.now(timezone.utc):
            try:
                refresh_token = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                if refresh_token:
                    access_token = refresh_tiktok_token(user_id, refresh_token, db=db)
                else:
                    tiktok_logger.warning(f"No refresh token available for user {user_id}")
                    return None
            except Exception as refresh_err:
                tiktok_logger.error(f"Failed to refresh TikTok token for user {user_id}: {refresh_err}")
                return None
        
        # Call TikTok status API
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "publish_id": publish_id
        }
        
        response = httpx.post(
            TIKTOK_STATUS_URL,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        
        if response.status_code == 404:
            # ROOT CAUSE FIX: 404 typically means the publish_id is no longer valid for status checking.
            tiktok_logger.debug(
                f"TikTok status API returned 404 for publish_id {publish_id} (user {user_id}). "
                f"This usually means the video was already published and publish_id is no longer valid for status checking."
            )
            return None
        elif response.status_code != 200:
            tiktok_logger.warning(
                f"Failed to fetch TikTok status for publish_id {publish_id} (user {user_id}): "
                f"HTTP {response.status_code} - {response.text[:200]}"
            )
            return None
        
        data = response.json()
        
        # Check for errors in response
        if "error" in data:
            error_info = data["error"]
            tiktok_logger.warning(
                f"TikTok API error for publish_id {publish_id} (user {user_id}): "
                f"{error_info.get('code', 'unknown')} - {error_info.get('message', 'unknown error')}"
            )
            return None
        
        return data.get("data", {})
        
    except Exception as e:
        tiktok_logger.error(
            f"Exception fetching TikTok status for publish_id {publish_id} (user {user_id}): {e}",
            exc_info=True
        )
        return None


def map_privacy_level_to_tiktok(privacy_level, creator_info):
    """Map frontend privacy level to TikTok's format
    
    Handles both old format (public/private/friends) and new API format (PUBLIC_TO_EVERYONE/SELF_ONLY/etc)
    Raises exception if privacy_level is not set.
    """
    # Get available options from creator_info
    available_options = creator_info.get("privacy_level_options", [])
    
    if not privacy_level or str(privacy_level).strip() == '':
        raise Exception("Privacy level is required. Please select a privacy level in the video settings.")
    
    privacy_level_str = str(privacy_level).strip()
    
    # Check if it's already in TikTok API format (uppercase with underscores)
    if privacy_level_str in ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY", "FOLLOWER_OF_CREATOR"]:
        tiktok_privacy = privacy_level_str
    else:
        # Map old format to new format
        mapping = {
            "public": "PUBLIC_TO_EVERYONE",
            "private": "SELF_ONLY",
            "friends": "MUTUAL_FOLLOW_FRIENDS"
        }
        privacy_level_lower = privacy_level_str.lower()
        tiktok_privacy = mapping.get(privacy_level_lower)
        
        if not tiktok_privacy:
            raise Exception(f"Invalid privacy level: {privacy_level_str}. Must be one of: {list(mapping.keys())} or {['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY', 'FOLLOWER_OF_CREATOR']}")
    
    # Validate against available options
    if available_options:
        if tiktok_privacy not in available_options:
            raise Exception(f"Privacy level '{tiktok_privacy}' is not available for your account. Available options: {available_options}")
    
    return tiktok_privacy


# ============================================================================
# UPLOAD FUNCTIONS
# ============================================================================

# Note: The upload functions are very large (200+ lines each). 
# They will be added in a follow-up edit due to response size limits.
# For now, we include the function signatures and key logic.

# These functions need to be imported from app.main for Prometheus metrics:
# - successful_uploads_counter
# - failed_uploads_gauge
# We'll import them dynamically to avoid circular imports

def upload_video_to_youtube(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to YouTube - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        youtube_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            # Log with comprehensive context
            youtube_logger.error(
                f"❌ YouTube upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "youtube",
                    "error_type": "InsufficientTokens",
                }
            )
            
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Get YouTube credentials from database
    youtube_token = get_oauth_token(user_id, "youtube", db=db)
    if not youtube_token:
            error_msg = "No YouTube credentials"
            youtube_logger.error(
                f"❌ YouTube upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "youtube",
                    "error_type": "MissingCredentials",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Convert OAuth token to Google Credentials
    youtube_creds = oauth_token_to_credentials(youtube_token, db=db)
    if not youtube_creds:
        update_video(video_id, user_id, db=db, status="failed", error="Failed to convert YouTube token to credentials")
        youtube_logger.error("Failed to convert YouTube token to credentials")
        return
    
    # Check if refresh_token is present (required for token refresh)
    if not youtube_creds.refresh_token:
        error_msg = 'YouTube refresh token is missing. Please disconnect and reconnect YouTube.'
        update_video(video_id, user_id, db=db, status="failed", error=error_msg)
        youtube_logger.error(error_msg)
        return
    
    # Refresh token if expired (must be done before building YouTube client)
    if youtube_creds.expired:
        try:
            youtube_logger.debug("Refreshing expired YouTube token...")
            youtube_creds.refresh(GoogleRequest())
            
            # ROOT CAUSE FIX: Validate credentials after refresh
            if not youtube_creds.token:
                error_msg = 'Failed to refresh YouTube token: No access token returned after refresh. Please disconnect and reconnect YouTube.'
                update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                youtube_logger.error(error_msg)
                return
            
            # Save refreshed token back to database
            token_data = credentials_to_oauth_token_data(
                youtube_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
            )
            
            # ROOT CAUSE FIX: Additional validation (credentials_to_oauth_token_data now raises on None, but double-check)
            if not token_data.get("access_token"):
                error_msg = 'Failed to refresh YouTube token: No access token in token data. Please disconnect and reconnect YouTube.'
                update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                youtube_logger.error(error_msg)
                return
            
            save_oauth_token(
                user_id=user_id,
                platform="youtube",
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=token_data["expires_at"],
                extra_data=token_data["extra_data"],
                db=db
            )
            youtube_logger.debug("YouTube token refreshed successfully")
        except ValueError as ve:
            # ROOT CAUSE FIX: Handle validation errors from credentials_to_oauth_token_data
            error_msg = f'Failed to refresh YouTube token: {str(ve)}. Please disconnect and reconnect YouTube.'
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            youtube_logger.error(error_msg, exc_info=True)
            return
        except Exception as refresh_error:
            error_msg = f'Failed to refresh YouTube token: {str(refresh_error)}. Please disconnect and reconnect YouTube.'
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            youtube_logger.error(error_msg, exc_info=True)
            return
    
    # Get settings from database
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    youtube_logger.info(f"Starting upload for {video.filename}")
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        youtube_logger.debug("Building YouTube API client...")
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get video metadata
        # ROOT CAUSE FIX: Refresh video from database to ensure we have latest custom_settings
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get title using consistent priority logic (DRY - shared helper function)
        title = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=youtube_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='title_template'
        )
        
        # Enforce YouTube's 100 character limit for titles
        if len(title) > 100:
            title = title[:100]
        
        # Get description using consistent priority logic (DRY - shared helper function)
        description = get_video_description(
            video=video,
            custom_settings=custom_settings,
            destination_settings=youtube_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='description_template',
            default='Uploaded via Hopper'
        )
        
        # Get visibility and made_for_kids: per-video custom > destination settings
        visibility = custom_settings.get('visibility', youtube_settings.get('visibility', 'private'))
        made_for_kids = custom_settings.get('made_for_kids', youtube_settings.get('made_for_kids', False))
        
        # Get tags: per-video custom > template
        if 'tags' in custom_settings:
            tags_str = custom_settings['tags']
        else:
            tags_str = replace_template_placeholders(
                youtube_settings.get('tags_template', ''),
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Parse tags (comma-separated, strip whitespace, filter empty)
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
        
        snippet_body = {
            'title': title,
            'description': description,
            'categoryId': '22'
        }
        
        # Only add tags if there are any
        if tags:
            snippet_body['tags'] = tags
        
        youtube_logger.info(f"Preparing upload request - Title: {title[:50]}..., Visibility: {visibility}")
        # ROOT CAUSE FIX: Resolve path to absolute to ensure file is found
        video_path = Path(video.path).resolve()
        youtube_logger.debug(f"Video path: {video_path}")
        
        # Verify file exists before attempting upload
        if not video_path.exists():
            error_msg = f"Video file not found: {video_path}"
            youtube_logger.error(
                f"❌ YouTube upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Path: {video_path}",
                extra={
                    "context": {
                        "user_id": user_id,
                        "video_id": video_id,
                        "video_filename": video.filename,
                        "video_path": str(video_path),
                        "platform": "youtube",
                        "error_type": "FileNotFound",
                    }
                }
            )
            raise FileNotFoundError(error_msg)
        
        request = youtube.videos().insert(
            part='snippet,status',
            body={
                'snippet': snippet_body,
                'status': {
                    'privacyStatus': visibility,
                    'selfDeclaredMadeForKids': made_for_kids
                }
            },
            media_body=MediaFileUpload(str(video_path), resumable=True)
        )
        
        youtube_logger.info("Starting resumable upload...")
        response = None
        chunk_count = 0
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                set_upload_progress(user_id, video_id, progress)
                chunk_count += 1
                if chunk_count % 10 == 0 or progress == 100:  # Log every 10 chunks or at completion
                    youtube_logger.info(f"Upload progress: {progress}%")
        
        # Update video in database with success
        custom_settings = custom_settings.copy() if custom_settings else {}
        custom_settings['youtube_id'] = response['id']
        update_video(video_id, user_id, db=db, status="uploaded", custom_settings=custom_settings)
        set_upload_progress(user_id, video_id, 100)
        youtube_logger.info(f"Successfully uploaded {video.filename}, YouTube ID: {response['id']}")
        
        # Increment successful uploads counter
        successful_uploads_counter.inc()
        
        # Deduct tokens after successful upload (only if not already deducted)
        if video.file_size_bytes and video.tokens_consumed == 0:
            tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
            deduct_tokens(
                user_id=user_id,
                tokens=tokens_required,
                transaction_type='upload',
                video_id=video.id,
                metadata={
                    'filename': video.filename,
                    'platform': 'youtube',
                    'youtube_id': response['id'],
                    'file_size_bytes': video.file_size_bytes,
                    'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                },
                db=db
            )
            # Update tokens_consumed in video record to prevent double-charging
            update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            youtube_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            youtube_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
    
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Gather comprehensive context for troubleshooting
        context = {
            "user_id": user_id,
            "video_id": video_id,
            "video_filename": video.filename,
            "file_size_bytes": video.file_size_bytes,
            "file_size_mb": round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            "tokens_consumed": video.tokens_consumed,
            "platform": "youtube",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
        # Add video path if available
        try:
            video_path = Path(video.path).resolve() if video.path else None
            if video_path:
                context["video_path"] = str(video_path)
                context["file_exists"] = video_path.exists()
                if video_path.exists():
                    context["actual_file_size_bytes"] = video_path.stat().st_size
        except Exception:
            pass
        
        # Log comprehensive error details
        youtube_logger.error(
            f"❌ YouTube upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        # Update video status with detailed error
        detailed_error = f"YouTube upload failed: {error_type}: {error_msg}"
        update_video(video_id, user_id, db=db, status="failed", error=detailed_error)
        delete_upload_progress(user_id, video_id)
        
        # Increment failed uploads metric
        failed_uploads_gauge.inc()


def upload_video_to_tiktok(user_id: int, video_id: int, db: Session = None, session_id: str = None):
    """Upload a single video to TikTok - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        tiktok_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "tiktok",
                    "error_type": "InsufficientTokens",
                }
            )
            
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Get TikTok credentials from database
    tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
    if not tiktok_token:
            error_msg = "No TikTok credentials"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "MissingCredentials",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Decrypt access token
    access_token = decrypt(tiktok_token.access_token)
    if not access_token or not access_token.strip():
        error_msg = "TikTok: Access token is missing or invalid. Please reconnect your TikTok account."
        tiktok_logger.error(
            f"❌ TikTok token is empty or invalid - User {user_id}, Video {video_id} ({video.filename})",
            extra={
                "user_id": user_id,
                "video_id": video_id,
                "video_filename": video.filename,
                "platform": "tiktok",
                "error_type": "EmptyToken",
            }
        )
        update_video(video_id, user_id, db=db, status="failed", error=error_msg)
        failed_uploads_gauge.inc()
        return
    
    # Check if token is expired and refresh if needed
    token_expiry = check_token_expiration(tiktok_token)
    if token_expiry.get("expired", False) or token_expiry.get("expires_soon", False):
        refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
        if refresh_token_decrypted:
            try:
                tiktok_logger.info(f"TikTok token expired/expiring for user {user_id}, refreshing...")
                access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                if not tiktok_token:
                    raise Exception("Failed to retrieve token after refresh")
                tiktok_logger.info(f"Successfully refreshed TikTok token for user {user_id}")
            except Exception as refresh_error:
                error_msg = f"TikTok: Failed to refresh access token. Please reconnect your TikTok account. Error: {str(refresh_error)}"
                tiktok_logger.error(
                    f"❌ TikTok token refresh FAILED - User {user_id}, Video {video_id} ({video.filename}): {refresh_error}",
                    extra={
                        "user_id": user_id,
                        "video_id": video_id,
                        "video_filename": video.filename,
                        "platform": "tiktok",
                        "error_type": "TokenRefreshFailed",
                    },
                    exc_info=True
                )
                update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                failed_uploads_gauge.inc()
                return
        else:
            error_msg = "TikTok: Access token expired and no refresh token available. Please reconnect your TikTok account."
            tiktok_logger.error(
                f"❌ TikTok token expired with no refresh token - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "TokenExpiredNoRefresh",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Get settings from database
    tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        # Check rate limit (use user_id if session_id not provided)
        check_tiktok_rate_limit(session_id=session_id, user_id=user_id)
        
        # Get creator info (with automatic retry on token error)
        try:
            creator_info = get_tiktok_creator_info(access_token)
        except Exception as creator_info_error:
            error_msg = str(creator_info_error)
            # If token is invalid, try refreshing once more
            if "access_token_invalid" in error_msg.lower() or "invalid" in error_msg.lower():
                tiktok_logger.warning(f"Creator info query failed with token error, attempting refresh: {error_msg}")
                tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                if not tiktok_token:
                    error_msg = f"TikTok: No token found in database. Please reconnect your TikTok account."
                    tiktok_logger.error(
                        f"❌ TikTok token not found - User {user_id}, Video {video_id} ({video.filename})",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "platform": "tiktok",
                            "error_type": "TokenNotFound",
                        }
                    )
                    update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                    failed_uploads_gauge.inc()
                    return
                refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                if refresh_token_decrypted:
                    try:
                        access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                        tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                        if not tiktok_token:
                            raise Exception("Failed to retrieve token after refresh")
                        creator_info = get_tiktok_creator_info(access_token)
                        tiktok_logger.info(f"Successfully refreshed token and retried creator info query for user {user_id}")
                    except Exception as retry_error:
                        error_msg = f"TikTok: Failed to refresh access token after invalid token error. Please reconnect your TikTok account. Error: {str(retry_error)}"
                        tiktok_logger.error(
                            f"❌ TikTok token refresh FAILED after invalid token - User {user_id}, Video {video_id} ({video.filename}): {retry_error}",
                            extra={
                                "user_id": user_id,
                                "video_id": video_id,
                                "video_filename": video.filename,
                                "platform": "tiktok",
                                "error_type": "TokenRefreshFailedAfterInvalid",
                            },
                            exc_info=True
                        )
                        update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                        failed_uploads_gauge.inc()
                        return
                else:
                    error_msg = f"TikTok: Access token is invalid and no refresh token available. Please reconnect your TikTok account. Error: {error_msg}"
                    tiktok_logger.error(
                        f"❌ TikTok invalid token with no refresh token - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "platform": "tiktok",
                            "error_type": "InvalidTokenNoRefresh",
                        }
                    )
                    update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                    failed_uploads_gauge.inc()
                    return
            else:
                # Other error - re-raise
                raise
        
        # Check if creator can make more posts (TikTok UX requirement 1b)
        can_not_make_more_posts = creator_info.get("can_not_make_more_posts", False)
        if can_not_make_more_posts:
            error_msg = "TikTok: You cannot make more posts at this moment. Please try again later."
            tiktok_logger.warning(
                f"❌ TikTok upload BLOCKED - Creator cannot make more posts - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PostingLimitReached",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            raise Exception(error_msg)
        
        # Get video file
        stored_path = Path(video.path).resolve()
        fallback_path = (settings.UPLOAD_DIR / video.filename).resolve()
        
        if stored_path.exists():
            video_path = stored_path
        elif fallback_path.exists():
            video_path = fallback_path
            tiktok_logger.info(
                f"Using fallback path for TikTok upload - User {user_id}, Video {video_id} ({video.filename}): "
                f"Stored path not found: {stored_path}, using fallback: {fallback_path}"
            )
        else:
            error_msg = f"Video file not found at {stored_path} or {fallback_path}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Stored path: {stored_path} (exists: {stored_path.exists()}), "
                f"Fallback path: {fallback_path} (exists: {fallback_path.exists()})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "stored_path": str(stored_path),
                    "fallback_path": str(fallback_path),
                    "platform": "tiktok",
                    "error_type": "FileNotFound",
                }
            )
            raise FileNotFoundError(error_msg)
        
        video_size = video_path.stat().st_size
        if video_size == 0:
            error_msg = "Video file is empty"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Empty file - User {user_id}, Video {video_id} ({video.filename}): "
                f"File size: {video_size} bytes",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "video_path": str(video_path),
                    "file_size": video_size,
                    "platform": "tiktok",
                    "error_type": "EmptyFile",
                }
            )
            raise Exception(error_msg)
        
        # Validate video duration against max_video_post_duration_sec (TikTok UX requirement 1c)
        max_video_post_duration_sec = creator_info.get("max_video_post_duration_sec")
        if max_video_post_duration_sec:
            try:
                video_duration_seconds = get_video_duration(video_path)
                if video_duration_seconds > max_video_post_duration_sec:
                    error_msg = (
                        f"TikTok: Video duration ({video_duration_seconds:.1f}s) exceeds maximum allowed duration "
                        f"({max_video_post_duration_sec}s). Please use a shorter video."
                    )
                    tiktok_logger.warning(
                        f"❌ TikTok upload BLOCKED - Video duration too long - User {user_id}, Video {video_id} ({video.filename}): "
                        f"Duration: {video_duration_seconds:.1f}s, Max: {max_video_post_duration_sec}s",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "video_duration_seconds": video_duration_seconds,
                            "max_video_post_duration_sec": max_video_post_duration_sec,
                            "platform": "tiktok",
                            "error_type": "VideoDurationExceeded",
                        }
                    )
                    update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                    failed_uploads_gauge.inc()
                    raise Exception(error_msg)
                tiktok_logger.debug(f"Video duration validated: {video_duration_seconds:.1f}s <= {max_video_post_duration_sec}s")
            except Exception as duration_error:
                # If duration check fails (e.g., ffprobe not available), log warning but don't block upload
                if "exceeds maximum" in str(duration_error) or "exceeded" in str(duration_error).lower():
                    raise
                tiktok_logger.warning(
                    f"Could not validate video duration for user {user_id}, video {video_id}: {duration_error}. "
                    f"Upload will proceed, but duration validation is recommended."
                )
        
        # Prepare metadata
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get title using consistent priority logic
        title = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=tiktok_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='title_template'
        )
        
        title = (title or filename_no_ext)[:2200]  # TikTok limit
        
        # Get settings: per-video custom > destination settings
        privacy_level = custom_settings.get('privacy_level') or tiktok_settings.get('privacy_level')
        if not privacy_level:
            error_msg = "TikTok privacy level is required. Please set a privacy level in the video settings or TikTok destination settings."
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Privacy level not set - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PrivacyLevelRequired",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
        
        try:
            tiktok_privacy = map_privacy_level_to_tiktok(privacy_level, creator_info)
            tiktok_logger.debug(f"Using privacy_level: {tiktok_privacy} (from input: {privacy_level})")
        except Exception as privacy_error:
            error_msg = f"TikTok privacy level error: {str(privacy_error)}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Privacy level error - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PrivacyLevelError",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
        
        # Check creator_info for disabled interactions
        allow_comments_setting = custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', False))
        allow_duet_setting = custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', False))
        allow_stitch_setting = custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', False))
        
        comment_disabled = creator_info.get("disable_comment", False) or creator_info.get("comment_disabled", False)
        duet_disabled = creator_info.get("disable_duet", False) or creator_info.get("duet_disabled", False)
        stitch_disabled = creator_info.get("disable_stitch", False) or creator_info.get("stitch_disabled", False)
        
        allow_comments = allow_comments_setting and not comment_disabled
        allow_duet = allow_duet_setting and not duet_disabled
        allow_stitch = allow_stitch_setting and not stitch_disabled
        
        # Get commercial content disclosure settings
        commercial_content_disclosure = custom_settings.get('commercial_content_disclosure', tiktok_settings.get('commercial_content_disclosure', False))
        commercial_content_your_brand = custom_settings.get('commercial_content_your_brand', tiktok_settings.get('commercial_content_your_brand', False))
        commercial_content_branded = custom_settings.get('commercial_content_branded', tiktok_settings.get('commercial_content_branded', False))
        
        brand_organic_toggle = commercial_content_disclosure and commercial_content_your_brand
        brand_content_toggle = commercial_content_disclosure and commercial_content_branded
        
        tiktok_logger.info(f"Uploading {video.filename} ({video_size / (1024*1024):.2f} MB)")
        set_upload_progress(user_id, video_id, 5)
        
        # Determine upload method: prefer PULL_FROM_URL, fallback to FILE_UPLOAD
        use_pull_from_url = True
        video_url = None
        upload_method = None
        
        stored_path = Path(video.path).resolve()
        fallback_path = (settings.UPLOAD_DIR / video.filename).resolve()
        file_exists = stored_path.exists() or fallback_path.exists()
        
        if use_pull_from_url and file_exists:
            # Generate secure access token for video file (valid for 1 hour)
            video_access_token = generate_video_access_token(video_id, user_id, expires_in_hours=1)
            video_url = f"{settings.BACKEND_URL.rstrip('/')}/api/videos/{video_id}/file?token={video_access_token}"
            upload_method = "PULL_FROM_URL"
            actual_path = stored_path if stored_path.exists() else fallback_path
            tiktok_logger.info(
                f"TikTok upload method: PULL_FROM_URL (URL) - User {user_id}, Video {video_id} ({video.filename}), "
                f"file exists at: {actual_path}"
            )
        else:
            if use_pull_from_url and not file_exists:
                tiktok_logger.warning(
                    f"TikTok upload method: PULL_FROM_URL (URL) skipped - file not found, falling back to FILE_UPLOAD (file) - "
                    f"User {user_id}, Video {video_id} ({video.filename}). "
                    f"Stored path: {stored_path} (exists: {stored_path.exists()}), "
                    f"Fallback path: {fallback_path} (exists: {fallback_path.exists()})"
                )
            use_pull_from_url = False
            upload_method = "FILE_UPLOAD"
            tiktok_logger.info(
                f"TikTok upload method: FILE_UPLOAD (file) - User {user_id}, Video {video_id} ({video.filename})"
            )
        
        # Step 1: Initialize upload
        init_response = None
        try:
            if use_pull_from_url and video_url:
                source_info = {
                    "source": "PULL_FROM_URL",
                    "video_url": video_url
                }
            else:
                source_info = {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
                }
            
            init_response = httpx.post(
                TIKTOK_INIT_UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {access_token.strip()}",
                    "Content-Type": "application/json; charset=UTF-8"
                },
                json={
                    "post_info": {
                        "title": title,
                        "privacy_level": tiktok_privacy,
                        "disable_duet": not allow_duet,
                        "disable_comment": not allow_comments,
                        "disable_stitch": not allow_stitch,
                        "brand_organic_toggle": brand_organic_toggle,
                        "brand_content_toggle": brand_content_toggle
                    },
                    "source_info": source_info
                },
                timeout=30.0
            )
        except Exception as init_error:
            # If PULL_FROM_URL fails, fallback to FILE_UPLOAD
            if use_pull_from_url and video_url:
                tiktok_logger.warning(
                    f"TikTok upload method changed: PULL_FROM_URL (URL) failed, falling back to FILE_UPLOAD (file) - "
                    f"User {user_id}, Video {video_id} ({video.filename}): {init_error}"
                )
                use_pull_from_url = False
                upload_method = "FILE_UPLOAD"
                source_info = {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
                }
                try:
                    init_response = httpx.post(
                        TIKTOK_INIT_UPLOAD_URL,
                        headers={
                            "Authorization": f"Bearer {access_token.strip()}",
                            "Content-Type": "application/json; charset=UTF-8"
                        },
                        json={
                            "post_info": {
                                "title": title,
                                "privacy_level": tiktok_privacy,
                                "disable_duet": not allow_duet,
                                "disable_comment": not allow_comments,
                                "disable_stitch": not allow_stitch,
                                "brand_organic_toggle": brand_organic_toggle,
                                "brand_content_toggle": brand_content_toggle
                            },
                            "source_info": source_info
                        },
                        timeout=30.0
                    )
                except Exception as retry_error:
                    raise init_error
            else:
                raise
        
        # Check if token error and retry with refresh
        if init_response.status_code != 200:
            try:
                response_data = init_response.json()
                error = response_data.get("error", {})
                error_code = error.get('code', '')
                error_message = error.get('message', '')
                
                # If token is invalid, try refreshing once more
                if "access_token_invalid" in error_code.lower() or "access_token_invalid" in error_message.lower() or "invalid" in error_message.lower():
                    tiktok_logger.warning(f"Init upload failed with token error, attempting refresh: {error_code} - {error_message}")
                    tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                    if not tiktok_token:
                        error_msg = f"TikTok: No token found in database. Please reconnect your TikTok account."
                        tiktok_logger.error(
                            f"❌ TikTok token not found - User {user_id}, Video {video_id} ({video.filename})",
                            extra={
                                "user_id": user_id,
                                "video_id": video_id,
                                "video_filename": video.filename,
                                "platform": "tiktok",
                                "error_type": "TokenNotFound",
                            }
                        )
                        update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                        failed_uploads_gauge.inc()
                        return
                    refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                    if refresh_token_decrypted:
                        try:
                            access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                            tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                            if not tiktok_token:
                                raise Exception("Failed to retrieve token after refresh")
                            # Retry init upload with new token
                            if use_pull_from_url and video_url:
                                retry_source_info = {
                                    "source": "PULL_FROM_URL",
                                    "video_url": video_url
                                }
                            else:
                                retry_source_info = {
                                    "source": "FILE_UPLOAD",
                                    "video_size": video_size,
                                    "chunk_size": video_size,
                                    "total_chunk_count": 1
                                }
                            
                            init_response = httpx.post(
                                TIKTOK_INIT_UPLOAD_URL,
                                headers={
                                    "Authorization": f"Bearer {access_token.strip()}",
                                    "Content-Type": "application/json; charset=UTF-8"
                                },
                                json={
                                    "post_info": {
                                        "title": title,
                                        "privacy_level": tiktok_privacy,
                                        "disable_duet": not allow_duet,
                                        "disable_comment": not allow_comments,
                                        "disable_stitch": not allow_stitch,
                                        "brand_organic_toggle": brand_organic_toggle,
                                        "brand_content_toggle": brand_content_toggle
                                    },
                                    "source_info": retry_source_info
                                },
                                timeout=30.0
                            )
                            tiktok_logger.info(f"Successfully refreshed token and retried init upload for user {user_id}")
                        except Exception as retry_error:
                            error_msg = f"TikTok: Failed to refresh access token during upload. Please reconnect your TikTok account. Error: {str(retry_error)}"
                            tiktok_logger.error(
                                f"❌ TikTok token refresh FAILED during upload - User {user_id}, Video {video_id} ({video.filename}): {retry_error}",
                                extra={
                                    "user_id": user_id,
                                    "video_id": video_id,
                                    "video_filename": video.filename,
                                    "platform": "tiktok",
                                    "error_type": "TokenRefreshFailedDuringUpload",
                                },
                                exc_info=True
                            )
                            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                            failed_uploads_gauge.inc()
                            return
            except:
                pass
        
        if init_response.status_code != 200:
            import json as json_module
            error_context = {
                "user_id": user_id,
                "video_id": video_id,
                "video_filename": video.filename,
                "platform": "tiktok",
                "http_status": init_response.status_code,
                "stage": "init_upload",
            }
            
            try:
                response_data = init_response.json()
                error_context["response_data"] = json_module.dumps(response_data)
                error = response_data.get("error", {})
                error_code = error.get('code', '')
                error_message = error.get('message', 'Unknown error')
                error_context["error_code"] = error_code
                error_context["error_message"] = error_message
                
                if error_code == "unaudited_client_can_only_post_to_private_accounts":
                    user_friendly_error = (
                        "TikTok app is not audited. Unaudited apps can only post to private accounts. "
                        "Please set your TikTok privacy level to 'private' in settings, or wait for app audit completion."
                    )
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Unaudited client limitation - User {user_id}, Video {video_id} ({video.filename}): "
                        f"{user_friendly_error}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                
                tiktok_logger.error(
                    f"❌ TikTok upload FAILED - Init error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {init_response.status_code} - {error_message}",
                    extra=error_context
                )
                tiktok_logger.error(f"Full response: {json_module.dumps(response_data, indent=2)}")
                raise Exception(f"Init failed: {error_message}")
            except Exception as parse_error:
                error_context["raw_response"] = init_response.text
                error_context["parse_error"] = str(parse_error)
                tiktok_logger.error(
                    f"❌ TikTok upload FAILED - Init error (parse failed) - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {init_response.status_code}",
                    extra=error_context
                )
                tiktok_logger.error(f"Raw response text: {init_response.text}")
                raise Exception(f"Init failed: {init_response.status_code} - {init_response.text}")
        
        init_data = init_response.json()
        publish_id = init_data["data"]["publish_id"]
        
        tiktok_logger.info(f"Initialized, publish_id: {publish_id}")
        set_upload_progress(user_id, video_id, 10)
        
        # Step 2: Upload video file (only for FILE_UPLOAD method)
        if not use_pull_from_url:
            upload_url = init_data["data"].get("upload_url")
            if not upload_url:
                raise Exception("TikTok did not return upload_url for FILE_UPLOAD method")
            
            tiktok_logger.info(
                f"TikTok uploading video file using FILE_UPLOAD (file) method - "
                f"User {user_id}, Video {video_id} ({video.filename})"
            )
            
            file_ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
            content_type = {'mp4': 'video/mp4', 'mov': 'video/quicktime', 'webm': 'video/webm'}.get(file_ext, 'video/mp4')
            
            with open(video_path, 'rb') as f:
                upload_response = httpx.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                        "Content-Type": content_type
                    },
                    content=f.read(),
                    timeout=300.0
                )
            
            if upload_response.status_code not in [200, 201]:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "http_status": upload_response.status_code,
                    "stage": "file_upload",
                    "publish_id": publish_id if 'publish_id' in locals() else None,
                    "video_size": video_size if 'video_size' in locals() else None,
                }
                
                try:
                    response_data = upload_response.json()
                    error_context["response_data"] = json_module.dumps(response_data)
                    error = response_data.get("error", {})
                    error_msg = error.get("message", upload_response.text)
                    error_context["error_code"] = error.get('code')
                    error_context["error_message"] = error_msg
                    
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - File upload error - User {user_id}, Video {video_id} ({video.filename}): "
                        f"HTTP {upload_response.status_code} - {error_msg}",
                        extra=error_context
                    )
                    tiktok_logger.error(f"Full upload response: {json_module.dumps(response_data, indent=2)}")
                except Exception as parse_error:
                    error_context["raw_response"] = upload_response.text
                    error_context["parse_error"] = str(parse_error)
                    error_msg = upload_response.text
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - File upload error (parse failed) - User {user_id}, Video {video_id} ({video.filename}): "
                        f"HTTP {upload_response.status_code}",
                        extra=error_context
                    )
                    tiktok_logger.error(f"Raw upload response: {upload_response.text}")
                raise Exception(f"Upload failed: {upload_response.status_code} - {error_msg}")
            
            tiktok_logger.info("File upload completed")
        else:
            # PULL_FROM_URL method: TikTok will download the file automatically
            tiktok_logger.info(
                f"TikTok using PULL_FROM_URL (URL) method - TikTok will download the file automatically - "
                f"User {user_id}, Video {video_id} ({video.filename})"
            )
            set_upload_progress(user_id, video_id, 50)
        
        # Success - update video in database
        custom_settings = custom_settings.copy() if custom_settings else {}
        custom_settings['tiktok_publish_id'] = publish_id
        update_video(video_id, user_id, db=db, status="uploaded", custom_settings=custom_settings)
        set_upload_progress(user_id, video_id, 100)
        final_method = upload_method if 'upload_method' in locals() else ("PULL_FROM_URL" if use_pull_from_url else "FILE_UPLOAD")
        tiktok_logger.info(
            f"TikTok upload successful using {final_method} method - "
            f"User {user_id}, Video {video_id} ({video.filename}), publish_id: {publish_id}"
        )
        
        # Increment successful uploads counter
        successful_uploads_counter.inc()
        
        # Deduct tokens after successful upload (only if not already deducted)
        if video.file_size_bytes and video.tokens_consumed == 0:
            tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
            deduct_tokens(
                user_id=user_id,
                tokens=tokens_required,
                transaction_type='upload',
                video_id=video.id,
                metadata={
                    'filename': video.filename,
                    'platform': 'tiktok',
                    'tiktok_publish_id': publish_id,
                    'file_size_bytes': video.file_size_bytes,
                    'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                },
                db=db
            )
            # Update tokens_consumed in video record to prevent double-charging
            update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            tiktok_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            tiktok_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
    
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        context = {
            "user_id": user_id,
            "video_id": video_id,
            "video_filename": video.filename,
            "file_size_bytes": video.file_size_bytes,
            "file_size_mb": round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            "tokens_consumed": video.tokens_consumed,
            "platform": "tiktok",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
        try:
            video_path = Path(video.path).resolve() if video.path else None
            if video_path:
                context["video_path"] = str(video_path)
                context["file_exists"] = video_path.exists()
                if video_path.exists():
                    context["actual_file_size_bytes"] = video_path.stat().st_size
        except Exception:
            pass
        
        try:
            balance_info = get_token_balance(user_id, db)
            if balance_info:
                context["tokens_remaining"] = balance_info.get('tokens_remaining', 0)
                context["tokens_used_this_period"] = balance_info.get('tokens_used_this_period', 0)
        except Exception:
            pass
        
        try:
            if 'publish_id' in locals():
                context["tiktok_publish_id"] = publish_id
            if 'upload_url' in locals():
                context["tiktok_upload_url"] = upload_url
        except Exception:
            pass
        
        tiktok_logger.error(
            f"❌ TikTok upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        detailed_error = f"TikTok upload failed: {error_type}: {error_msg}"
        update_video(video_id, user_id, db=db, status="failed", error=detailed_error)
        delete_upload_progress(user_id, video_id)
        
        failed_uploads_gauge.inc()


async def upload_video_to_instagram(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to Instagram - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        instagram_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            instagram_logger.error(
                f"❌ Instagram upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "instagram",
                    "error_type": "InsufficientTokens",
                }
            )
            
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Get Instagram credentials from database
    instagram_token = get_oauth_token(user_id, "instagram", db=db)
    if not instagram_token:
            error_msg = "No Instagram credentials"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "error_type": "MissingCredentials",
                }
            )
            update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            failed_uploads_gauge.inc()
            return
    
    # Decrypt access token
    access_token = decrypt(instagram_token.access_token)
    if not access_token:
        update_video(video_id, user_id, db=db, status="failed", error="Failed to decrypt Instagram token")
        instagram_logger.error("Failed to decrypt Instagram token")
        return
    
    # Get business account ID from extra_data
    extra_data = instagram_token.extra_data or {}
    business_account_id = extra_data.get("business_account_id")
    if not business_account_id:
        update_video(video_id, user_id, db=db, status="failed", error="No Instagram Business Account ID. Please reconnect your Instagram account.")
        instagram_logger.error("No Instagram Business Account ID")
        return
    
    # Get settings from database
    instagram_settings = get_user_settings(user_id, "instagram", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    instagram_logger.info(f"Starting upload for {video.filename}")
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        # Get video file
        video_path = Path(video.path).resolve()
        if not video_path.exists():
            error_msg = f"Video file not found: {video_path}"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Path: {video_path}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "video_path": str(video_path),
                    "platform": "instagram",
                    "error_type": "FileNotFound",
                }
            )
            raise FileNotFoundError(error_msg)
        
        # Prepare caption
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get caption using consistent priority logic
        caption = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=instagram_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='caption_template'
        )
        
        caption = (caption or filename_no_ext)[:2200]
        
        # Get settings: per-video custom > destination settings
        location_id = custom_settings.get('location_id', instagram_settings.get('location_id', ''))
        
        instagram_logger.info(f"Uploading {video.filename} to Instagram")
        set_upload_progress(user_id, video_id, 10)
        
        # Read video file
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        video_size = len(video_data)
        set_upload_progress(user_id, video_id, 20)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Step 1: Create resumable upload container
            container_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{business_account_id}/media"
            container_params = {
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption
            }
            
            if location_id:
                container_params["location_id"] = location_id
            
            container_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Creating resumable upload container for {video.filename}")
            
            container_response = await client.post(
                container_url,
                json=container_params,
                headers=container_headers
            )
            
            if container_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": container_response.status_code,
                    "stage": "create_container",
                    "business_account_id": business_account_id,
                }
                
                error_data = container_response.json() if container_response.headers.get('content-type', '').startswith('application/json') else container_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(container_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                    
                    if error_obj.get('code') == 190:
                        error_msg = "Instagram access token is invalid or expired. Please reconnect your Instagram account."
                        instagram_logger.error(
                            f"❌ Instagram upload FAILED - Token expired - User {user_id}, Video {video_id} ({video.filename}): "
                            f"HTTP {container_response.status_code} - {error_msg}",
                            extra=error_context
                        )
                        raise Exception(error_msg)
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Container creation error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {container_response.status_code}",
                    extra=error_context
                )
                raise Exception(f"Failed to create resumable upload container: {error_data}")
            
            container_result = container_response.json()
            container_id = container_result.get('id')
            
            if not container_id:
                raise Exception(f"No container ID in response: {container_result}")
            
            instagram_logger.info(f"Created container {container_id}")
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_container_id'] = container_id
            update_video(video_id, user_id, db=db, custom_settings=custom_settings)
            set_upload_progress(user_id, video_id, 40)
            
            # Step 2: Upload video to rupload.facebook.com
            upload_url = f"https://rupload.facebook.com/ig-api-upload/v21.0/{container_id}"
            upload_headers = {
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(video_size)
            }
            
            instagram_logger.info(f"Uploading video data ({video_size} bytes) to rupload.facebook.com")
            
            upload_response = await client.post(
                upload_url,
                headers=upload_headers,
                content=video_data
            )
            
            if upload_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": upload_response.status_code,
                    "stage": "upload_video_data",
                    "container_id": container_id if 'container_id' in locals() else None,
                    "video_size": video_size if 'video_size' in locals() else None,
                }
                
                error_data = upload_response.json() if upload_response.headers.get('content-type', '').startswith('application/json') else upload_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(upload_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Video upload error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {upload_response.status_code}",
                    extra=error_context
                )
                instagram_logger.error(f"Failed to upload video: {error_data}")
                raise Exception(f"Failed to upload video data: {error_data}")
            
            upload_result = upload_response.json()
            if not upload_result.get('success'):
                raise Exception(f"Upload failed: {upload_result}")
            
            instagram_logger.info(f"Video uploaded successfully")
            set_upload_progress(user_id, video_id, 70)
            
            # Step 3: Wait for Instagram to process the video and check status
            instagram_logger.info(f"Waiting for Instagram to process video")
            await asyncio.sleep(5)
            
            # Check container status
            status_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{container_id}"
            status_params = {
                "fields": "status_code"
            }
            status_headers = {
                "Authorization": f"Bearer {access_token.strip()}"
            }
            
            for attempt in range(5):  # Check up to 5 times
                status_response = await client.get(status_url, params=status_params, headers=status_headers)
                if status_response.status_code == 200:
                    status_result = status_response.json()
                    status_code = status_result.get('status_code')
                    instagram_logger.info(f"Container status (attempt {attempt + 1}): {status_code}")
                    
                    if status_code == 'FINISHED':
                        break
                    elif status_code == 'ERROR':
                        raise Exception(f"Container processing failed")
                    elif status_code == 'EXPIRED':
                        raise Exception(f"Container expired")
                
                if attempt < 4:
                    await asyncio.sleep(60)  # Wait 60 seconds before checking again
            
            set_upload_progress(user_id, video_id, 85)
            
            # Step 4: Publish the container
            publish_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{business_account_id}/media_publish"
            publish_params = {
                "creation_id": container_id
            }
            publish_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Publishing container {container_id}")
            
            publish_response = await client.post(publish_url, json=publish_params, headers=publish_headers)
            
            if publish_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": publish_response.status_code,
                    "stage": "publish_media",
                    "container_id": container_id if 'container_id' in locals() else None,
                }
                
                error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else publish_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(publish_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Publish error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {publish_response.status_code}",
                    extra=error_context
                )
                instagram_logger.error(f"Failed to publish: {error_data}")
                raise Exception(f"Failed to publish media: {error_data}")
            
            publish_result = publish_response.json()
            media_id = publish_result.get('id')
            
            if not media_id:
                raise Exception(f"No media ID in publish response: {publish_result}")
            
            instagram_logger.info(f"Published to Instagram: {media_id}")
            
            # Update video in database with success
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_id'] = media_id
            update_video(video_id, user_id, db=db, status="completed", custom_settings=custom_settings)
            set_upload_progress(user_id, video_id, 100)
            
            # Increment successful uploads counter
            successful_uploads_counter.inc()
            
            # Deduct tokens after successful upload (only if not already deducted)
            if video.file_size_bytes and video.tokens_consumed == 0:
                tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
                deduct_tokens(
                    user_id=user_id,
                    tokens=tokens_required,
                    transaction_type='upload',
                    video_id=video.id,
                    metadata={
                        'filename': video.filename,
                        'platform': 'instagram',
                        'instagram_id': media_id,
                        'file_size_bytes': video.file_size_bytes,
                        'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                    },
                    db=db
                )
                # Update tokens_consumed in video record to prevent double-charging
                update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
                instagram_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
            else:
                instagram_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
            
            # Clean up progress after a delay
            await asyncio.sleep(2)
            delete_upload_progress(user_id, video_id)
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        context = {
            "user_id": user_id,
            "video_id": video_id,
            "video_filename": video.filename,
            "file_size_bytes": video.file_size_bytes,
            "file_size_mb": round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            "tokens_consumed": video.tokens_consumed,
            "platform": "instagram",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
        try:
            video_path = Path(video.path).resolve() if video.path else None
            if video_path:
                context["video_path"] = str(video_path)
                context["file_exists"] = video_path.exists()
                if video_path.exists():
                    context["actual_file_size_bytes"] = video_path.stat().st_size
        except Exception:
            pass
        
        try:
            balance_info = get_token_balance(user_id, db)
            if balance_info:
                context["tokens_remaining"] = balance_info.get('tokens_remaining', 0)
                context["tokens_used_this_period"] = balance_info.get('tokens_used_this_period', 0)
        except Exception:
            pass
        
        try:
            if 'container_id' in locals():
                context["instagram_container_id"] = container_id
            if 'business_account_id' in locals():
                context["instagram_business_account_id"] = business_account_id
            if 'video_size' in locals():
                context["uploaded_video_size"] = video_size
        except Exception:
            pass
        
        instagram_logger.error(
            f"❌ Instagram upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        detailed_error = f"Instagram upload failed: {error_type}: {error_msg}"
        update_video(video_id, user_id, db=db, status="failed", error=detailed_error)
        delete_upload_progress(user_id, video_id)
        
        failed_uploads_gauge.inc()


# Destination upload functions registry
DESTINATION_UPLOADERS = {
    "youtube": upload_video_to_youtube,
    "tiktok": upload_video_to_tiktok,
    "instagram": upload_video_to_instagram,
}
