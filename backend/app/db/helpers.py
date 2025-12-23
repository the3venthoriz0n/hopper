"""Database helper functions for user data management"""
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials

from app.models.user import User
from app.models.video import Video
from app.models.setting import Setting
from app.models.oauth_token import OAuthToken
from app.db.session import SessionLocal
from app.utils.encryption import encrypt, decrypt
from app.db.redis import (
    get_cached_settings, set_cached_settings, invalidate_settings_cache,
    get_cached_oauth_token, set_cached_oauth_token, invalidate_oauth_token_cache,
    redis_client
)
from app.core.config import settings

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
    cached = get_cached_settings(user_id, category)
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
                # Parse as JSON (booleans, numbers, lists, etc. are properly deserialized)
                settings_dict[setting.key] = json.loads(setting.value)
            except (json.JSONDecodeError, TypeError):
                # If not JSON, use as string (legacy data)
                settings_dict[setting.key] = setting.value
        
        # Cache the result
        set_cached_settings(user_id, category, settings_dict)
        
        return settings_dict
    finally:
        if should_close:
            db.close()


def set_user_setting(user_id: int, category: str, key: str, value: Any, db: Session = None) -> None:
    """Set a user setting (creates or updates)
    
    Args:
        user_id: User ID
        category: Settings category
        key: Setting key
        value: Setting value (will be JSON-encoded if not a string)
        db: Database session (if None, creates its own)
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Check if setting exists
        setting = db.query(Setting).filter(
            Setting.user_id == user_id,
            Setting.category == category,
            Setting.key == key
        ).first()
        
        # Convert value to JSON string if needed
        if isinstance(value, str):
            value_str = value
        else:
            value_str = json.dumps(value)
        
        if setting:
            # Update existing
            setting.value = value_str
        else:
            # Create new
            setting = Setting(
                user_id=user_id,
                category=category,
                key=key,
                value=value_str
            )
            db.add(setting)
        
        db.commit()
        
        # Invalidate cache
        invalidate_settings_cache(user_id, category)
    finally:
        if should_close:
            db.close()


def get_user_videos(user_id: int, db: Session = None) -> List[Video]:
    """Get all videos for a user"""
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        return db.query(Video).filter(Video.user_id == user_id).order_by(Video.created_at.desc()).all()
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
    cached = get_cached_settings(user_id, "all")
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
                # Parse as JSON (booleans, numbers, lists, etc. are properly deserialized)
                settings_by_category[setting.category][setting.key] = json.loads(setting.value)
            except (json.JSONDecodeError, TypeError):
                # If not JSON, use as string (legacy data)
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
        # Normalize boolean settings (handle legacy string values - one-time conversion)
        boolean_keys = ["allow_duplicates", "upload_immediately", "upload_first_immediately"]
        for key in boolean_keys:
            if key in result["global"] and isinstance(result["global"][key], str):
                # Convert legacy string to boolean and update in database
                result["global"][key] = result["global"][key].lower() in ("true", "1", "yes")
                set_user_setting(user_id, "global", key, result["global"][key], db=db)
        
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
            "privacy_level": "",
            "allow_comments": False,
            "allow_duet": False,
            "allow_stitch": False,
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
        set_cached_settings(user_id, "all", result)
        return result
    finally:
        if should_close:
            db.close()


def get_all_oauth_tokens(user_id: int, db: Session = None) -> Dict[str, Optional[OAuthToken]]:
    """Get all OAuth tokens for a user, decrypted
    Uses Redis caching with 1 minute TTL.
    
    Returns:
        Dict mapping platform name to OAuthToken object (or None if not connected)
    """
    # Try cache first
    cached = get_cached_oauth_token(user_id, "all")
    if cached is not None:
        # Reconstruct OAuthToken objects from cached data
        # This is a simplified version - full implementation would properly deserialize
        return cached
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        tokens = db.query(OAuthToken).filter(OAuthToken.user_id == user_id).all()
        
        # Build dict by platform
        tokens_dict = {}
        for token in tokens:
            # Decrypt tokens
            try:
                token.access_token = decrypt(token.access_token) if token.access_token else None
                token.refresh_token = decrypt(token.refresh_token) if token.refresh_token else None
            except Exception as e:
                logger.warning(f"Failed to decrypt token for user {user_id}, platform {token.platform}: {e}")
            
            tokens_dict[token.platform] = token
        
        # Cache the result (serialize for caching)
        cache_data = {platform: {
            'id': token.id,
            'platform': token.platform,
            'expires_at': token.expires_at.isoformat() if token.expires_at else None,
        } for platform, token in tokens_dict.items() if token}
        set_cached_oauth_token(user_id, "all", cache_data)
        
        return tokens_dict
    finally:
        if should_close:
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
    cached = get_cached_oauth_token(user_id, platform)
    if cached is not None:
        # Reconstruct OAuthToken object from cached data
        # This is a simplified version - full implementation would properly deserialize
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
        
        if token:
            # Decrypt tokens
            try:
                token.access_token = decrypt(token.access_token) if token.access_token else None
                token.refresh_token = decrypt(token.refresh_token) if token.refresh_token else None
            except Exception as e:
                logger.warning(f"Failed to decrypt token for user {user_id}, platform {platform}: {e}")
                return None
        
        return token
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
            # ROOT CAUSE FIX: Only update refresh_token if a new one is provided
            # If refresh_token parameter is None, preserve the existing refresh_token
            if encrypted_refresh is not None:
                token.refresh_token = encrypted_refresh
            token.expires_at = expires_at
            # ROOT CAUSE FIX: Merge extra_data instead of replacing to preserve legacy data
            if extra_data:
                existing_extra_data = token.extra_data or {}
                merged_extra_data = {**existing_extra_data, **extra_data}
                token.extra_data = merged_extra_data
            elif token.extra_data is None:
                token.extra_data = {}
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
        invalidate_oauth_token_cache(user_id, platform)
        
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
        invalidate_oauth_token_cache(user_id, platform)
        
        return True
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
    
    # For TikTok: Always check refresh token expiration, ignore access token expiration
    if token.platform == "tiktok" and token.refresh_token and token.extra_data:
        refresh_expires_at = None
        if token.extra_data.get("refresh_expires_at"):
            try:
                refresh_expires_at = datetime.fromisoformat(token.extra_data["refresh_expires_at"])
            except (ValueError, TypeError):
                pass
        
        if not refresh_expires_at:
            refresh_expires_in = token.extra_data.get("refresh_expires_in")
            if refresh_expires_in and token.updated_at:
                refresh_expires_at = token.updated_at + timedelta(seconds=int(refresh_expires_in))
        
        if refresh_expires_at:
            if refresh_expires_at < now:
                return {
                    "expired": True,
                    "expires_soon": False,
                    "expires_at": refresh_expires_at,
                    "status": "expired"
                }
            
            time_until_refresh_expiry = refresh_expires_at - now
            expires_soon = time_until_refresh_expiry.total_seconds() < 2592000  # 30 days
            status = "expires_soon" if expires_soon else "valid"
            return {
                "expired": False,
                "expires_soon": expires_soon,
                "expires_at": refresh_expires_at,
                "status": status
            }
        
        return {
            "expired": False,
            "expires_soon": False,
            "expires_at": None,
            "status": "valid"
        }
    
    # For tokens with refresh tokens (non-TikTok), check refresh token expiration
    if token.refresh_token and token.extra_data:
        refresh_expires_in = token.extra_data.get("refresh_expires_in")
        if refresh_expires_in:
            refresh_expires_at = token.updated_at + timedelta(seconds=int(refresh_expires_in)) if token.updated_at else None
            if refresh_expires_at:
                if token.extra_data and token.extra_data.get("refresh_failed"):
                    return {
                        "expired": False,
                        "expires_soon": True,
                        "expires_at": token.expires_at,
                        "status": "expires_soon"
                    }
                
                if refresh_expires_at < now:
                    return {
                        "expired": True,
                        "expires_soon": False,
                        "expires_at": refresh_expires_at,
                        "status": "expired"
                    }
                time_until_refresh_expiry = refresh_expires_at - now
                expires_soon = time_until_refresh_expiry.total_seconds() < 604800  # 7 days
                status = "expires_soon" if expires_soon else "valid"
                return {
                    "expired": False,
                    "expires_soon": expires_soon,
                    "expires_at": refresh_expires_at,
                    "status": status
                }
    
    # For tokens without refresh tokens, check access token expiration
    if not token.expires_at:
        return {
            "expired": False,
            "expires_soon": False,
            "expires_at": None,
            "status": "valid"
        }
    
    is_expired = token.expires_at < now
    
    if is_expired:
        return {
            "expired": True,
            "expires_soon": False,
            "expires_at": token.expires_at,
            "status": "expired"
        }
    
    time_until_expiry = token.expires_at - now
    if token.platform == "tiktok":
        return {
            "expired": False,
            "expires_soon": False,
            "expires_at": token.expires_at,
            "status": "valid"
        }
    else:
        expires_soon = time_until_expiry.total_seconds() < 86400  # 24 hours
    
    status = "expired" if is_expired else ("expires_soon" if expires_soon else "valid")
    
    return {
        "expired": is_expired,
        "expires_soon": expires_soon,
        "expires_at": token.expires_at,
        "status": status
    }


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
        
        # Get client_id and client_secret from extra_data or settings
        client_id = extra_data.get("client_id") or settings.GOOGLE_CLIENT_ID
        client_secret = extra_data.get("client_secret") or settings.GOOGLE_CLIENT_SECRET
        
        if not client_id or not client_secret:
            logger.error(f"Missing client_id or client_secret. extra_data: {extra_data}")
            return None
        
        # Ensure client_id and client_secret are saved in extra_data for future refreshes
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


def add_user_video(user_id: int, filename: str, path: str, generated_title: str = None, generated_description: str = None, file_size_bytes: int = None, tokens_consumed: int = None, db: Session = None) -> Video:
    """Add a video to user's queue
    
    Args:
        user_id: User ID
        filename: Video filename
        path: Video file path
        generated_title: Generated title (optional)
        generated_description: Generated description (optional) - prevents re-randomization
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
            generated_description=generated_description,
            file_size_bytes=file_size_bytes,
            tokens_consumed=tokens_consumed
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video
    finally:
        if should_close:
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
            if key == "custom_settings":
                # custom_settings is being set directly - always flag as modified
                setattr(video, key, value)
                custom_settings_modified = True
            elif hasattr(video, key):
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

