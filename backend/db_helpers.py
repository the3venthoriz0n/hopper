"""Database helper functions for user data management"""
from sqlalchemy.orm import Session
from models import SessionLocal, User, Video, Setting, OAuthToken
from typing import Optional, List, Dict, Any
import json
import os
import logging
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from encryption import encrypt, decrypt
import redis_client

logger = logging.getLogger(__name__)


def get_user_settings(user_id: int, category: str = "global", db: Session = None) -> Dict[str, Any]:
    """Get user settings by category (global, youtube, tiktok, instagram)
    Uses Redis caching with 5 minute TTL.
    
    Args:
        user_id: User ID
        category: Settings category
        db: Database session (if None, creates its own - for backward compatibility)
    """
    # Try to get from cache first
    cached = redis_client.get_cached_settings(user_id, category)
    if cached is not None:
        return cached
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        settings = db.query(Setting).filter(
            Setting.user_id == user_id,
            Setting.category == category
        ).all()
        
        # Convert to dict
        settings_dict = {}
        for setting in settings:
            try:
                # Try to parse as JSON first
                settings_dict[setting.key] = json.loads(setting.value)
            except (json.JSONDecodeError, TypeError):
                # If not JSON, use as string
                settings_dict[setting.key] = setting.value
        
        # Return defaults if no settings found
        if category == "global":
            defaults = {
                "title_template": "{filename}",
                "description_template": "Uploaded via Hopper",
                "wordbank": [],
                "upload_immediately": True,
                "schedule_mode": "spaced",
                "schedule_interval_value": 1,
                "schedule_interval_unit": "hours",
                "schedule_start_time": "",
                "allow_duplicates": False,
                "upload_first_immediately": True
            }
            result = {**defaults, **settings_dict}
        elif category == "youtube":
            defaults = {
                "visibility": "private",
                "made_for_kids": False,
                "title_template": "",
                "description_template": "",
                "tags_template": ""
            }
            result = {**defaults, **settings_dict}
        elif category == "tiktok":
            defaults = {
                "privacy_level": "private",
                "allow_comments": True,
                "allow_duet": True,
                "allow_stitch": True,
                "title_template": "",
                "description_template": ""
            }
            result = {**defaults, **settings_dict}
        elif category == "instagram":
            defaults = {
                "caption_template": "",
                "location_id": "",
                "disable_comments": False,
                "disable_likes": False
            }
            result = {**defaults, **settings_dict}
        else:
            result = settings_dict
        
        # Cache the result
        redis_client.set_cached_settings(user_id, category, result)
        return result
    finally:
        if should_close:
            db.close()


def get_all_user_settings(user_id: int, db: Session = None) -> Dict[str, Dict[str, Any]]:
    """Get all user settings for all categories in a single query - optimized to prevent N+1
    Uses Redis caching with 5 minute TTL.
    
    Args:
        user_id: User ID
        db: Database session (if None, creates its own - for backward compatibility)
    """
    # Try to get from cache first
    cached = redis_client.get_cached_settings(user_id, "all")
    if cached is not None:
        return cached
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Load all settings for this user in one query
        all_settings = db.query(Setting).filter(
            Setting.user_id == user_id
        ).all()
        
        # Group by category
        settings_by_category = {}
        for setting in all_settings:
            if setting.category not in settings_by_category:
                settings_by_category[setting.category] = {}
            
            try:
                # Try to parse as JSON first
                settings_by_category[setting.category][setting.key] = json.loads(setting.value)
            except (json.JSONDecodeError, TypeError):
                # If not JSON, use as string
                settings_by_category[setting.category][setting.key] = setting.value
        
        # Apply defaults for each category
        result = {}
        
        # Global settings
        global_defaults = {
            "title_template": "{filename}",
            "description_template": "Uploaded via Hopper",
            "wordbank": [],
            "upload_immediately": True,
            "schedule_mode": "spaced",
            "schedule_interval_value": 1,
            "schedule_interval_unit": "hours",
            "schedule_start_time": "",
            "allow_duplicates": False
        }
        result["global"] = {**global_defaults, **settings_by_category.get("global", {})}
        
        # YouTube settings
        youtube_defaults = {
            "visibility": "private",
            "made_for_kids": False,
            "title_template": "",
            "description_template": "",
            "tags_template": ""
        }
        result["youtube"] = {**youtube_defaults, **settings_by_category.get("youtube", {})}
        
        # TikTok settings
        tiktok_defaults = {
            "privacy_level": "private",
            "allow_comments": True,
            "allow_duet": True,
            "allow_stitch": True,
            "title_template": "",
            "description_template": ""
        }
        result["tiktok"] = {**tiktok_defaults, **settings_by_category.get("tiktok", {})}
        
        # Instagram settings
        instagram_defaults = {
            "caption_template": "",
            "location_id": "",
            "disable_comments": False,
            "disable_likes": False
        }
        result["instagram"] = {**instagram_defaults, **settings_by_category.get("instagram", {})}
        
        # Destinations settings (no defaults, just return what's there)
        result["destinations"] = settings_by_category.get("destinations", {})
        
        # Cache the result
        redis_client.set_cached_settings(user_id, "all", result)
        return result
    finally:
        if should_close:
            db.close()


def set_user_setting(user_id: int, category: str, key: str, value: Any, db: Session = None) -> None:
    """Set a user setting
    Invalidates Redis cache for this user's settings.
    
    Args:
        user_id: User ID
        category: Settings category
        key: Setting key
        value: Setting value
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Convert value to JSON string if it's not a string
        if not isinstance(value, str):
            value_str = json.dumps(value)
        else:
            value_str = value
        
        # Check if setting exists
        setting = db.query(Setting).filter(
            Setting.user_id == user_id,
            Setting.category == category,
            Setting.key == key
        ).first()
        
        if setting:
            setting.value = value_str
        else:
            setting = Setting(
                user_id=user_id,
                category=category,
                key=key,
                value=value_str
            )
            db.add(setting)
        
        db.commit()
        
        # Invalidate cache for this category and all_settings
        redis_client.invalidate_settings_cache(user_id, category)
    finally:
        if should_close:
            db.close()


def get_user_videos(user_id: int, db: Session = None) -> List[Video]:
    """Get all videos for a user
    
    Args:
        user_id: User ID
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        return db.query(Video).filter(Video.user_id == user_id).order_by(Video.id).all()
    finally:
        if should_close:
            db.close()


def get_all_scheduled_videos(db: Session = None) -> Dict[int, List[Video]]:
    """Get all scheduled videos across all users, grouped by user_id
    Optimized for scheduler task - single query instead of N queries.
    
    ROOT CAUSE FIX: Also includes videos in "uploading" status with scheduled_time.
    This ensures videos that were uploading when server restarted are retried.
    
    Args:
        db: Database session (if None, creates its own - for backward compatibility)
    
    Returns:
        Dictionary mapping user_id to list of scheduled videos
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # ROOT CAUSE FIX: Include both "scheduled" and "uploading" videos with scheduled_time
        # This ensures:
        # 1. Videos scheduled for future upload are included
        # 2. Videos that were uploading when server restarted are retried
        scheduled_videos = db.query(Video).filter(
            Video.status.in_(['scheduled', 'uploading']),
            Video.scheduled_time.isnot(None)
        ).order_by(Video.scheduled_time).all()
        
        # Group by user_id
        videos_by_user = {}
        for video in scheduled_videos:
            if video.user_id not in videos_by_user:
                videos_by_user[video.user_id] = []
            videos_by_user[video.user_id].append(video)
        
        return videos_by_user
    finally:
        if should_close:
            db.close()


def add_user_video(user_id: int, filename: str, path: str, generated_title: str = None, file_size_bytes: int = None, tokens_consumed: int = None, db: Session = None) -> Video:
    """Add a video to user's queue
    
    Args:
        user_id: User ID
        filename: Video filename
        path: Video file path
        generated_title: Generated title (optional)
        file_size_bytes: File size in bytes (optional)
        tokens_consumed: Tokens consumed for this upload (optional)
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        video = Video(
            user_id=user_id,
            filename=filename,
            path=path,
            status="pending",
            generated_title=generated_title,
            file_size_bytes=file_size_bytes,
            tokens_consumed=tokens_consumed
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video
    finally:
        db.close()


def update_video(video_id: int, user_id: int, db: Session = None, **kwargs) -> Optional[Video]:
    """Update a video
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session (if None, creates its own - for backward compatibility)
        **kwargs: Fields to update (IDs like youtube_id, tiktok_id, instagram_id are stored in custom_settings)
    """
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
            return None
        
        # IDs that should be stored in custom_settings
        id_fields = ['youtube_id', 'tiktok_id', 'tiktok_publish_id', 'instagram_id', 'instagram_container_id']
        
        # Track if we need to flag custom_settings as modified
        custom_settings_modified = False
        
        for key, value in kwargs.items():
            if hasattr(video, key):
                # Direct attribute exists, set it
                setattr(video, key, value)
            elif key in id_fields:
                # Store in custom_settings
                if video.custom_settings is None:
                    video.custom_settings = {}
                    custom_settings_modified = True
                elif key not in video.custom_settings or video.custom_settings[key] != value:
                    custom_settings_modified = True
                video.custom_settings[key] = value
        
        # SQLAlchemy doesn't detect in-place changes to JSON fields, so we need to flag it
        if custom_settings_modified:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(video, "custom_settings")
        
        db.commit()
        db.refresh(video)
        return video
    finally:
        if should_close:
            db.close()


def delete_video(video_id: int, user_id: int, db: Session = None) -> bool:
    """Delete a video
    
    Args:
        video_id: Video ID
        user_id: User ID
        db: Database session (if None, creates its own - for backward compatibility)
    """
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
            return False
        
        db.delete(video)
        db.commit()
        return True
    finally:
        db.close()


def get_oauth_token(user_id: int, platform: str, db: Session = None) -> Optional[OAuthToken]:
    """Get OAuth token for a platform
    Uses Redis caching with 1 minute TTL.
    
    Args:
        user_id: User ID
        platform: Platform name (youtube, tiktok, instagram)
        db: Database session (if None, creates its own - for backward compatibility)
    """
    # Try to get from cache first
    cached = redis_client.get_cached_oauth_token(user_id, platform)
    if cached is not None:
        # Reconstruct OAuthToken object from cached data
        # Note: We can't fully reconstruct the object, so we'll query DB but cache the result
        # Actually, for OAuthToken objects, it's better to cache the token ID and query if needed
        # But for simplicity, we'll just cache a flag and still query - the cache helps reduce DB load
        pass
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        token = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        ).first()
        
        # Cache token existence (store minimal data to avoid serialization issues)
        if token:
            # Cache token metadata (not the actual encrypted tokens)
            token_data = {
                "id": token.id,
                "platform": token.platform,
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "extra_data": token.extra_data
            }
            redis_client.set_cached_oauth_token(user_id, platform, token_data)
        else:
            # Cache None result to avoid repeated DB queries
            redis_client.set_cached_oauth_token(user_id, platform, {"id": None})
        
        return token
    finally:
        if should_close:
            db.close()


def check_token_expiration(token: Optional[OAuthToken]) -> Dict[str, Any]:
    """Check if an OAuth token is expired or about to expire
    
    Returns:
        Dict with:
            - expired: bool - True if token is expired
            - expires_soon: bool - True if token expires within 24 hours
            - expires_at: Optional[datetime] - Expiration time
            - status: str - 'valid', 'expires_soon', or 'expired'
    """
    if not token:
        return {
            "expired": True,
            "expires_soon": False,
            "expires_at": None,
            "status": "expired"
        }
    
    now = datetime.now(timezone.utc)
    
    # If no expiration time, assume it's valid (some tokens don't expire)
    if not token.expires_at:
        return {
            "expired": False,
            "expires_soon": False,
            "expires_at": None,
            "status": "valid"
        }
    
    # Check if expired
    is_expired = token.expires_at < now
    
    # Check if expires within 24 hours
    time_until_expiry = token.expires_at - now
    expires_soon = not is_expired and time_until_expiry.total_seconds() < 86400  # 24 hours
    
    status = "expired" if is_expired else ("expires_soon" if expires_soon else "valid")
    
    return {
        "expired": is_expired,
        "expires_soon": expires_soon,
        "expires_at": token.expires_at,
        "status": status
    }


def get_all_oauth_tokens(user_id: int, db: Session = None) -> Dict[str, Optional[OAuthToken]]:
    """Get all OAuth tokens for a user in a single query - optimized to prevent N+1
    
    Args:
        user_id: User ID
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Load all OAuth tokens for this user in one query
        all_tokens = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id
        ).all()
        
        # Create a dictionary keyed by platform
        tokens_by_platform = {}
        for token in all_tokens:
            tokens_by_platform[token.platform] = token
        
        # Return dict with all platforms (None if not found)
        result = {
            "youtube": tokens_by_platform.get("youtube"),
            "tiktok": tokens_by_platform.get("tiktok"),
            "instagram": tokens_by_platform.get("instagram")
        }
        
        # Cache which platforms have tokens (metadata only)
        cache_data = {
            "youtube": bool(result["youtube"]),
            "tiktok": bool(result["tiktok"]),
            "instagram": bool(result["instagram"])
        }
        redis_client.set_cached_all_oauth_tokens(user_id, cache_data)
        
        return result
    finally:
        if should_close:
            db.close()


def save_oauth_token(user_id: int, platform: str, access_token: str, 
                      refresh_token: str = None, expires_at: datetime = None,
                      extra_data: Dict = None, db: Session = None) -> OAuthToken:
    """Save or update OAuth token (tokens are encrypted)
    
    Args:
        user_id: User ID
        platform: Platform name
        access_token: Access token (will be encrypted)
        refresh_token: Refresh token (will be encrypted, optional)
        expires_at: Token expiration time (optional)
        extra_data: Additional token data (optional)
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        token = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        ).first()
        
        # Encrypt tokens before storing
        encrypted_access = encrypt(access_token) if access_token else ""
        encrypted_refresh = encrypt(refresh_token) if refresh_token else None
        
        if token:
            token.access_token = encrypted_access
            token.refresh_token = encrypted_refresh
            token.expires_at = expires_at
            token.extra_data = extra_data or {}
            token.updated_at = datetime.now(timezone.utc)
        else:
            token = OAuthToken(
                user_id=user_id,
                platform=platform,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                expires_at=expires_at,
                extra_data=extra_data or {}
            )
            db.add(token)
        
        db.commit()
        db.refresh(token)
        
        # Invalidate cache for this platform and all_tokens
        redis_client.invalidate_oauth_token_cache(user_id, platform)
        
        return token
    finally:
        if should_close:
            db.close()


def delete_oauth_token(user_id: int, platform: str, db: Session = None) -> bool:
    """Delete OAuth token
    
    Args:
        user_id: User ID
        platform: Platform name
        db: Database session (if None, creates its own - for backward compatibility)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        token = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        ).first()
        
        if not token:
            return False
        
        db.delete(token)
        db.commit()
        
        # Invalidate cache for this platform and all_tokens
        redis_client.invalidate_oauth_token_cache(user_id, platform)
        
        return True
    finally:
        if should_close:
            db.close()


def oauth_token_to_credentials(token: OAuthToken, db: Session = None) -> Optional[Credentials]:
    """Convert OAuthToken to Google Credentials object (decrypts tokens)
    
    Ensures client_id and client_secret are always present in extra_data for token refresh.
    """
    if not token:
        return None
    
    try:
        # Decrypt tokens
        access_token = decrypt(token.access_token)
        refresh_token = decrypt(token.refresh_token) if token.refresh_token else None
        
        if not access_token:
            logger.warning(f"Failed to decrypt access token for user {token.user_id if hasattr(token, 'user_id') else 'unknown'}, platform {token.platform if hasattr(token, 'platform') else 'unknown'}. Token may be corrupted or encrypted with different key.")
            return None
        
        # Parse extra_data to get client info
        extra_data = token.extra_data or {}
        
        # Get client_id and client_secret from extra_data or environment
        client_id = extra_data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID")
        client_secret = extra_data.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error(f"Missing client_id or client_secret. extra_data: {extra_data}")
            return None
        
        # Ensure client_id and client_secret are saved in extra_data for future refreshes
        # This fixes tokens that were saved before these fields were stored
        needs_update = False
        if extra_data.get("client_id") != client_id:
            extra_data["client_id"] = client_id
            needs_update = True
        if extra_data.get("client_secret") != client_secret:
            extra_data["client_secret"] = client_secret
            needs_update = True
        
        # Update token in database if extra_data changed
        if needs_update:
            should_close = False
            if db is None:
                db = SessionLocal()
                should_close = True
            try:
                token.extra_data = extra_data
                db.commit()
                logger.debug(f"Updated OAuth token extra_data with client_id/client_secret for user {token.user_id}, platform {token.platform}")
            except Exception as update_error:
                logger.warning(f"Failed to update token extra_data: {update_error}")
            finally:
                if should_close:
                    db.close()
        
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=extra_data.get("scopes", [])
        )
        
        if token.expires_at:
            creds.expiry = token.expires_at
        
        return creds
    except Exception as e:
        logger.error(f"Error converting OAuth token to credentials: {e}", exc_info=True)
        return None


def credentials_to_oauth_token_data(creds: Credentials, client_id: str = None, 
                                     client_secret: str = None) -> Dict[str, Any]:
    """Convert Google Credentials to OAuth token data"""
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expires_at": creds.expiry if creds.expiry else None,
        "extra_data": {
            "client_id": client_id or getattr(creds, "client_id", None),
            "client_secret": client_secret or getattr(creds, "client_secret", None),
            "scopes": creds.scopes if hasattr(creds, "scopes") else []
        }
    }


def delete_user_account(user_id: int, db: Session = None) -> Dict[str, Any]:
    """Delete user account and all associated data
    
    This function performs a complete data deletion:
    - Deletes all OAuth tokens
    - Deletes all settings
    - Deletes all videos (database records only, files handled separately)
    - Deletes user account
    - Returns list of video file paths for caller to clean up
    
    Args:
        user_id: User ID to delete
        db: Database session (if None, creates its own)
        
    Returns:
        Dictionary with deletion statistics and file paths to clean up
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Get user first to verify it exists
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {
                "success": False,
                "error": "User not found",
                "stats": {}
            }
        
        # Collect statistics
        stats = {
            "videos_deleted": 0,
            "settings_deleted": 0,
            "oauth_tokens_deleted": 0,
            "user_email": user.email
        }
        
        # Collect video file paths before deletion (for cleanup)
        videos = db.query(Video).filter(Video.user_id == user_id).all()
        video_file_paths = [v.path for v in videos]
        stats["videos_deleted"] = len(videos)
        
        # Count settings and OAuth tokens
        settings = db.query(Setting).filter(Setting.user_id == user_id).all()
        stats["settings_deleted"] = len(settings)
        
        oauth_tokens = db.query(OAuthToken).filter(OAuthToken.user_id == user_id).all()
        stats["oauth_tokens_deleted"] = len(oauth_tokens)
        
        # Delete user (cascade will handle related records due to foreign key constraints)
        db.delete(user)
        db.commit()
        
        # Invalidate all caches for this user
        redis_client.invalidate_all_user_caches(user_id)
        
        logger.info(f"Deleted user account {user_id} ({user.email}): {stats}")
        
        return {
            "success": True,
            "stats": stats,
            "video_file_paths": video_file_paths
        }
    except Exception as e:
        logger.error(f"Error deleting user account {user_id}: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "stats": {}
        }
    finally:
        if should_close:
            db.close()