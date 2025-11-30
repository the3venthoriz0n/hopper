"""Database helper functions for user data management"""
from sqlalchemy.orm import Session
from models import SessionLocal, User, Video, Setting, OAuthToken
from typing import Optional, List, Dict, Any
import json
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from encryption import encrypt, decrypt


def get_user_settings(user_id: int, category: str = "global") -> Dict[str, Any]:
    """Get user settings by category (global, youtube, tiktok, instagram)"""
    db = SessionLocal()
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
                "allow_duplicates": False
            }
            return {**defaults, **settings_dict}
        elif category == "youtube":
            defaults = {
                "visibility": "private",
                "made_for_kids": False,
                "title_template": "",
                "description_template": "",
                "tags_template": ""
            }
            return {**defaults, **settings_dict}
        elif category == "tiktok":
            defaults = {
                "privacy_level": "private",
                "allow_comments": True,
                "allow_duet": True,
                "allow_stitch": True,
                "title_template": "",
                "description_template": ""
            }
            return {**defaults, **settings_dict}
        elif category == "instagram":
            defaults = {
                "caption_template": "",
                "location_id": "",
                "disable_comments": False,
                "disable_likes": False
            }
            return {**defaults, **settings_dict}
        
        return settings_dict
    finally:
        db.close()


def set_user_setting(user_id: int, category: str, key: str, value: Any) -> None:
    """Set a user setting"""
    db = SessionLocal()
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
    finally:
        db.close()


def get_user_videos(user_id: int) -> List[Video]:
    """Get all videos for a user"""
    db = SessionLocal()
    try:
        return db.query(Video).filter(Video.user_id == user_id).order_by(Video.id).all()
    finally:
        db.close()


def add_user_video(user_id: int, filename: str, path: str, generated_title: str = None) -> Video:
    """Add a video to user's queue"""
    db = SessionLocal()
    try:
        video = Video(
            user_id=user_id,
            filename=filename,
            path=path,
            status="pending",
            generated_title=generated_title
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video
    finally:
        db.close()


def update_video(video_id: int, user_id: int, **kwargs) -> Optional[Video]:
    """Update a video"""
    db = SessionLocal()
    try:
        video = db.query(Video).filter(
            Video.id == video_id,
            Video.user_id == user_id
        ).first()
        
        if not video:
            return None
        
        for key, value in kwargs.items():
            if hasattr(video, key):
                setattr(video, key, value)
        
        db.commit()
        db.refresh(video)
        return video
    finally:
        db.close()


def delete_video(video_id: int, user_id: int) -> bool:
    """Delete a video"""
    db = SessionLocal()
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


def get_oauth_token(user_id: int, platform: str) -> Optional[OAuthToken]:
    """Get OAuth token for a platform"""
    db = SessionLocal()
    try:
        return db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        ).first()
    finally:
        db.close()


def save_oauth_token(user_id: int, platform: str, access_token: str, 
                      refresh_token: str = None, expires_at: datetime = None,
                      extra_data: Dict = None) -> OAuthToken:
    """Save or update OAuth token (tokens are encrypted)"""
    db = SessionLocal()
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
        return token
    finally:
        db.close()


def delete_oauth_token(user_id: int, platform: str) -> bool:
    """Delete OAuth token"""
    db = SessionLocal()
    try:
        token = db.query(OAuthToken).filter(
            OAuthToken.user_id == user_id,
            OAuthToken.platform == platform
        ).first()
        
        if not token:
            return False
        
        db.delete(token)
        db.commit()
        return True
    finally:
        db.close()


def oauth_token_to_credentials(token: OAuthToken) -> Optional[Credentials]:
    """Convert OAuthToken to Google Credentials object (decrypts tokens)"""
    if not token:
        return None
    
    try:
        # Decrypt tokens
        access_token = decrypt(token.access_token)
        refresh_token = decrypt(token.refresh_token) if token.refresh_token else None
        
        if not access_token:
            return None
        
        # Parse extra_data to get client info
        extra_data = token.extra_data or {}
        
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=extra_data.get("client_id"),
            client_secret=extra_data.get("client_secret"),
            scopes=extra_data.get("scopes", [])
        )
        
        if token.expires_at:
            creds.expiry = token.expires_at
        
        return creds
    except Exception:
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
