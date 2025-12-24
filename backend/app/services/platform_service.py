"""Platform-specific services for OAuth account management"""
import logging
import re
from typing import Dict, Optional, List
from sqlalchemy.orm import Session
import httpx

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.config import settings
from app.db.helpers import (
    get_oauth_token, check_token_expiration, oauth_token_to_credentials,
    credentials_to_oauth_token_data, save_oauth_token
)
from app.services.video_service import _ensure_fresh_token, _fetch_creator_info_safe
from app.utils.encryption import decrypt

tiktok_logger = logging.getLogger("tiktok")
youtube_logger = logging.getLogger("youtube")


def get_tiktok_account_info(
    user_id: int,
    db: Session,
    force_refresh: bool = False
) -> Dict:
    """Get TikTok account information with stale-while-revalidate pattern
    
    Strategy:
    1. Ensure token is fresh (with distributed locking)
    2. Always fetch privacy_level_options synchronously (critical for UI)
    3. Use cached data for other fields (fast response)
    4. Extract and update display_name/username from fresh creator_info
    
    Args:
        user_id: User ID
        db: Database session
        force_refresh: If True, force synchronous refresh (skip background task)
    
    Returns:
        Dict with account, creator_info, token_status, token_expired, token_expires_soon, has_cache
    """
    token_obj = get_oauth_token(user_id, "tiktok", db=db)
    
    if not token_obj:
        return {
            "account": None,
            "creator_info": None,
            "token_status": "missing",
            "token_expired": True,
            "token_expires_soon": False,
            "has_cache": False
        }
    
    # Get token status
    token_expiry = check_token_expiration(token_obj)
    token_status = token_expiry.get("status", "valid")
    token_expired = token_expiry.get("expired", False)
    token_expires_soon = token_expiry.get("expires_soon", False)
    
    # Get cached data
    extra_data = token_obj.extra_data or {}
    cached_account = {
        "open_id": extra_data.get("open_id"),
        "display_name": extra_data.get("display_name"),
        "username": extra_data.get("username"),
        "avatar_url": extra_data.get("avatar_url")
    }
    cached_creator_info = extra_data.get("creator_info")
    has_cache = (
        (cached_account.get("display_name") or cached_account.get("username")) and 
        cached_creator_info
    )
    
    # Ensure token is fresh (with distributed locking)
    access_token = _ensure_fresh_token(user_id, db)
    if not access_token:
        # Token refresh failed - return cached data if available
        if has_cache:
            tiktok_logger.warning(f"Token refresh failed, returning cached account data (user {user_id})")
            return {
                "account": cached_account,
                "creator_info": cached_creator_info,
                "token_status": token_status,
                "token_expired": token_expired,
                "token_expires_soon": token_expires_soon,
                "has_cache": has_cache
            }
        return {
            "account": None,
            "creator_info": None,
            "token_status": "expired",
            "token_expired": True,
            "token_expires_soon": False,
            "has_cache": False
        }
    
    # Always fetch privacy_level_options synchronously (critical for UI)
    # This ensures the UI always has the latest privacy options
    try:
        fresh_creator_info = _fetch_creator_info_safe(access_token, user_id, db=db)
        if fresh_creator_info:
            # ROOT CAUSE FIX: Extract and update display_name/username synchronously
            # This ensures account info is available immediately, not just in background task
            fresh_display_name = (
                fresh_creator_info.get("creator_nickname") or 
                fresh_creator_info.get("display_name")
            )
            fresh_username = (
                fresh_creator_info.get("creator_username") or 
                fresh_creator_info.get("username")
            )
            fresh_avatar_url = (
                fresh_creator_info.get("creator_avatar_url") or 
                fresh_creator_info.get("avatar_url")
            )
            
            # Update cached_account for immediate return if we have new data
            if fresh_display_name or fresh_username:
                cached_account = {
                    "open_id": extra_data.get("open_id"),
                    "display_name": fresh_display_name or cached_account.get("display_name"),
                    "username": fresh_username or cached_account.get("username"),
                    "avatar_url": fresh_avatar_url or cached_account.get("avatar_url")
                }
            
            # Update cache with fresh privacy_level_options and account info
            account_updated = False
            privacy_updated = False
            
            # Check if privacy options changed
            if not cached_creator_info or cached_creator_info.get("privacy_level_options") != fresh_creator_info.get("privacy_level_options"):
                privacy_updated = True
            
            # Check if account info changed
            if fresh_display_name and extra_data.get("display_name") != fresh_display_name:
                extra_data["display_name"] = fresh_display_name
                account_updated = True
            if fresh_username and extra_data.get("username") != fresh_username:
                extra_data["username"] = fresh_username
                account_updated = True
            if fresh_avatar_url and extra_data.get("avatar_url") != fresh_avatar_url:
                extra_data["avatar_url"] = fresh_avatar_url
                account_updated = True
            
            # Update cache if anything changed
            if privacy_updated or account_updated:
                extra_data["creator_info"] = fresh_creator_info
                token_obj.extra_data = extra_data
                db.commit()
                if account_updated:
                    tiktok_logger.info(
                        f"Updated TikTok account info synchronously (user {user_id}): "
                        f"{fresh_display_name} (@{fresh_username})"
                    )
                if privacy_updated:
                    tiktok_logger.debug(f"Updated privacy_level_options from API (user {user_id})")
            
            # Use fresh creator_info for response
            creator_info = fresh_creator_info
        else:
            # API call failed, use cached data
            creator_info = cached_creator_info
    except Exception as e:
        tiktok_logger.warning(f"Failed to fetch creator info (user {user_id}): {str(e)}")
        creator_info = cached_creator_info
    
    return {
        "account": cached_account,
        "creator_info": creator_info,
        "token_status": token_status,
        "token_expired": token_expired,
        "token_expires_soon": token_expires_soon,
        "has_cache": has_cache
    }


def extract_tiktok_account_from_creator_info(creator_info: Dict, open_id: Optional[str] = None) -> Dict:
    """Extract account fields from TikTok creator_info response
    
    Args:
        creator_info: Creator info dict from TikTok API
        open_id: Optional open_id to include in account dict
    
    Returns:
        Dict with open_id, display_name, username, avatar_url
    """
    return {
        "open_id": open_id,
        "display_name": (
            creator_info.get("creator_nickname") or 
            creator_info.get("display_name")
        ),
        "username": (
            creator_info.get("creator_username") or 
            creator_info.get("username")
        ),
        "avatar_url": (
            creator_info.get("creator_avatar_url") or 
            creator_info.get("avatar_url")
        ),
    }


def get_youtube_account_info(
    user_id: int,
    db: Session
) -> Dict:
    """Get YouTube account information (channel name/email)
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with 'account' key containing account info or None
    """
    youtube_token = get_oauth_token(user_id, "youtube", db=db)
    
    if not youtube_token:
        return {"account": None}
    
    try:
        # Check for cached account info in extra_data first (prevents "Loading account..." on refresh)
        extra_data = youtube_token.extra_data or {}
        cached_channel_name = extra_data.get("channel_name")
        cached_email = extra_data.get("email")
        cached_channel_id = extra_data.get("channel_id")
        
        # If we have cached account info with channel_name or email, return it immediately
        if cached_channel_name or cached_email:
            account_info = {}
            if cached_channel_name:
                account_info["channel_name"] = cached_channel_name
            if cached_channel_id:
                account_info["channel_id"] = cached_channel_id
            if cached_email:
                account_info["email"] = cached_email
            youtube_logger.debug(f"Returning cached YouTube account info for user {user_id}")
            return {"account": account_info}
        
        # Convert to Credentials object (automatically decrypts)
        youtube_creds = oauth_token_to_credentials(youtube_token, db=db)
        if not youtube_creds:
            # If credentials can't be converted (e.g., decryption failed), 
            # the token is likely corrupted or encrypted with a different key
            # Return None so user can reconnect
            youtube_logger.warning(f"Could not convert YouTube token to credentials for user {user_id}. Token may need to be refreshed or reconnected.")
            return {"account": None}
        
        # Refresh token if needed
        if youtube_creds.expired and youtube_creds.refresh_token:
            try:
                youtube_creds.refresh(GoogleRequest())
                # Save refreshed token back to database
                token_data = credentials_to_oauth_token_data(
                    youtube_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
                )
                save_oauth_token(
                    user_id=user_id,
                    platform="youtube",
                    access_token=token_data["access_token"],
                    refresh_token=token_data["refresh_token"],
                    expires_at=token_data["expires_at"],
                    extra_data=token_data["extra_data"],
                    db=db
                )
            except Exception as refresh_error:
                youtube_logger.warning(f"Token refresh failed for user {user_id}: {str(refresh_error)}")
        
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get channel info with timeout
        account_info = None
        try:
            channels_response = youtube.channels().list(
                part='snippet',
                mine=True
            ).execute()
            
            if channels_response.get('items') and len(channels_response['items']) > 0:
                channel = channels_response['items'][0]
                account_info = {
                    "channel_name": channel['snippet']['title'],
                    "channel_id": channel['id'],
                    "thumbnail": channel['snippet'].get('thumbnails', {}).get('default', {}).get('url')
                }
        except Exception as channel_error:
            youtube_logger.warning(f"Could not fetch channel info for user {user_id}: {str(channel_error)}")
            # Continue without channel info, try to get email
        
        # Get email from Google OAuth2 userinfo with timeout
        try:
            if youtube_creds.expired and youtube_creds.refresh_token:
                youtube_creds.refresh(GoogleRequest())
            
            with httpx.Client(timeout=5.0) as client:
                userinfo_response = client.get(
                    'https://www.googleapis.com/oauth2/v2/userinfo',
                    headers={'Authorization': f'Bearer {youtube_creds.token}'}
                )
                if userinfo_response.status_code == 200:
                    userinfo = userinfo_response.json()
                    if account_info:
                        account_info['email'] = userinfo.get('email')
                    else:
                        account_info = {'email': userinfo.get('email')}
                elif userinfo_response.status_code == 401:
                    youtube_logger.warning(f"Userinfo request unauthorized for user {user_id}, token may need refresh")
        except Exception as e:
            youtube_logger.debug(f"Could not fetch email for user {user_id}: {str(e)}")
            # Email is optional, continue without it
        
        # Cache the account info for future requests (if we have channel_name or email)
        if account_info and (account_info.get("channel_name") or account_info.get("email")):
            extra_data["channel_name"] = account_info.get("channel_name")
            extra_data["channel_id"] = account_info.get("channel_id")
            extra_data["email"] = account_info.get("email")
            
            # Save updated extra_data back to database
            token_data = credentials_to_oauth_token_data(
                youtube_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
            )
            save_oauth_token(
                user_id=user_id,
                platform="youtube",
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=token_data["expires_at"],
                extra_data=extra_data,
                db=db
            )
        
        return {"account": account_info}
    except Exception as e:
        youtube_logger.error(f"Error getting YouTube account info for user {user_id}: {str(e)}", exc_info=True)
        # Try to return cached account info even on exception
        try:
            extra_data = youtube_token.extra_data or {}
            cached_channel_name = extra_data.get("channel_name")
            cached_email = extra_data.get("email")
            if cached_channel_name or cached_email:
                account_info = {}
                if cached_channel_name:
                    account_info["channel_name"] = cached_channel_name
                if extra_data.get("channel_id"):
                    account_info["channel_id"] = extra_data["channel_id"]
                if cached_email:
                    account_info["email"] = cached_email
                return {"account": account_info}
        except:
            pass
        return {"account": None, "error": str(e)}


def get_youtube_videos(
    user_id: int,
    page: int = 1,
    per_page: int = 50,
    hide_shorts: bool = False,
    db: Session = None
) -> Dict:
    """Get user's YouTube videos (paginated)
    
    Args:
        user_id: User ID
        page: Page number (1-indexed)
        per_page: Videos per page
        hide_shorts: Whether to hide YouTube Shorts (< 60 seconds)
        db: Database session
    
    Returns:
        Dict with 'videos', 'total', 'page', 'per_page', 'total_pages'
    
    Raises:
        ValueError: If YouTube not connected
        Exception: For API errors
    """
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        youtube_token = get_oauth_token(user_id, "youtube", db=db)
        
        if not youtube_token:
            raise ValueError("YouTube not connected")
        
        # Decrypt and build credentials
        youtube_creds = Credentials(
            token=decrypt(youtube_token.access_token),
            refresh_token=decrypt(youtube_token.refresh_token) if youtube_token.refresh_token else None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET
        )
        
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get channel ID first
        channels_response = youtube.channels().list(
            part='contentDetails',
            mine=True
        ).execute()
        
        if not channels_response.get('items'):
            return {
                "videos": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0
            }
        
        channel_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Get videos from uploads playlist
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Fetch more than needed to filter shorts
        fetch_count = per_page * 2 if hide_shorts else per_page
        max_results = min(fetch_count + offset, 50)  # YouTube API max is 50 per request
        
        playlist_items = []
        next_page_token = None
        fetched = 0
        
        # Fetch in batches if needed
        while fetched < offset + fetch_count:
            request_count = min(50, offset + fetch_count - fetched)
            
            playlist_response = youtube.playlistItems().list(
                part='contentDetails',
                playlistId=channel_id,
                maxResults=request_count,
                pageToken=next_page_token
            ).execute()
            
            playlist_items.extend(playlist_response.get('items', []))
            fetched += len(playlist_response.get('items', []))
            next_page_token = playlist_response.get('nextPageToken')
            
            if not next_page_token or fetched >= offset + fetch_count:
                break
        
        # Get video IDs
        video_ids = [item['contentDetails']['videoId'] for item in playlist_items[offset:offset + fetch_count]]
        
        if not video_ids:
            return {
                "videos": [],
                "total": len(playlist_items),
                "page": page,
                "per_page": per_page,
                "total_pages": (len(playlist_items) + per_page - 1) // per_page
            }
        
        # Get video details (title, duration, category)
        videos_response = youtube.videos().list(
            part='snippet,contentDetails,status',
            id=','.join(video_ids)
        ).execute()
        
        videos = []
        for video in videos_response.get('items', []):
            video_id = video['id']
            snippet = video['snippet']
            
            # Parse duration (ISO 8601 format: PT1H2M10S)
            duration_str = video['contentDetails']['duration']
            duration_seconds = 0
            if duration_str:
                # Parse PT1H2M10S format
                hours = re.search(r'(\d+)H', duration_str)
                minutes = re.search(r'(\d+)M', duration_str)
                seconds = re.search(r'(\d+)S', duration_str)
                duration_seconds = (int(hours.group(1)) * 3600 if hours else 0) + \
                                 (int(minutes.group(1)) * 60 if minutes else 0) + \
                                 (int(seconds.group(1)) if seconds else 0)
            
            # Check if it's a short (category 15 is "People & Blogs" but shorts are typically < 60 seconds)
            # YouTube Shorts are videos < 60 seconds
            is_short = duration_seconds > 0 and duration_seconds < 60
            
            # Also check category - category 15 might indicate shorts, but duration is more reliable
            category_id = snippet.get('categoryId', '')
            
            if hide_shorts and is_short:
                continue
            
            videos.append({
                "id": video_id,
                "title": snippet.get('title', 'Untitled'),
                "duration_seconds": duration_seconds,
                "is_short": is_short,
                "category_id": category_id,
                "thumbnail": snippet.get('thumbnails', {}).get('default', {}).get('url', ''),
                "published_at": snippet.get('publishedAt', '')
            })
        
        # Limit to per_page
        videos = videos[:per_page]
        
        # Calculate total (approximate - we'd need to fetch all to get exact count)
        total = len(playlist_items)
        
        return {
            "videos": videos,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
    except ValueError:
        raise
    except Exception as e:
        youtube_logger.error(f"Error fetching YouTube videos: {str(e)}", exc_info=True)
        raise Exception(f"Error fetching videos: {str(e)}")
    finally:
        if should_close:
            db.close()

