"""OAuth service - Orchestration of OAuth flows for YouTube, TikTok, and Instagram"""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import quote, unquote, urlencode

import httpx
from fastapi import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import (
    settings, TIKTOK_SCOPES, TIKTOK_AUTH_URL, TIKTOK_TOKEN_URL,
    TIKTOK_CREATOR_INFO_URL, INSTAGRAM_SCOPES, INSTAGRAM_AUTH_URL,
    INSTAGRAM_GRAPH_API_BASE
)
from app.db.helpers import (
    get_oauth_token, save_oauth_token, delete_oauth_token,
    get_user_settings, set_user_setting,
    credentials_to_oauth_token_data
)
from app.db.redis import redis_client
from app.services.auth_service import get_user_by_id
from app.services.video.helpers import get_google_client_config
from app.services.video.platforms.tiktok_api import _parse_and_save_tiktok_token_response

# Loggers
logger = logging.getLogger(__name__)
youtube_logger = logging.getLogger("youtube")
tiktok_logger = logging.getLogger("tiktok")
instagram_logger = logging.getLogger("instagram")


# ============================================================================
# YOUTUBE OAUTH FLOW
# ============================================================================

def initiate_youtube_oauth_flow(user_id: int, request: Request) -> Dict[str, str]:
    """Initiate YouTube OAuth flow - build redirect URI and authorization URL"""
    google_config = get_google_client_config()
    if not google_config:
        raise ValueError("Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
    # Build redirect URI dynamically based on request
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or settings.ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/youtube/callback"
    
    # Create Flow from config dict
    flow = Flow.from_client_config(
        google_config,
        scopes=[
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube.readonly'
        ],
        redirect_uri=redirect_uri
    )
    
    # Store user_id in state parameter
    # ROOT CAUSE FIX: Add prompt='consent' to force Google to always return refresh_token
    # Without this, Google only returns refresh_token on first authorization
    url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=str(user_id)
    )
    return {"url": url}


def complete_youtube_oauth_flow(code: str, state: str, request: Request, db: Session) -> Dict[str, any]:
    """Complete YouTube OAuth flow - exchange code, validate refresh_token, fetch account info, save token"""
    # Get user_id from state parameter
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        raise ValueError("Invalid state parameter")
    
    # Verify user exists
    user = get_user_by_id(user_id, db=db)
    if not user:
        raise ValueError("User not found")
    
    # Build redirect URI dynamically
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or settings.ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/youtube/callback"
    
    google_config = get_google_client_config()
    if not google_config:
        raise ValueError("Google OAuth credentials not configured")
    
    # Create flow and fetch token
    flow = Flow.from_client_config(
        google_config,
        scopes=[
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube.readonly'
        ],
        redirect_uri=redirect_uri
    )
    
    flow.fetch_token(code=code)
    flow_creds = flow.credentials
    
    # ROOT CAUSE FIX: Validate refresh_token is present
    # Google only returns refresh_token with access_type='offline' and prompt='consent'
    if not flow_creds.refresh_token:
        youtube_logger.error(f"YouTube OAuth did not return refresh_token for user {user_id}. This usually means the OAuth consent screen needs to be shown again.")
        raise ValueError("Failed to obtain refresh token. Please try connecting again - you may need to grant permissions again.")
    
    # Create complete Credentials object
    creds = Credentials(
        token=flow_creds.token,
        refresh_token=flow_creds.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=flow_creds.scopes
    )
    
    # ROOT CAUSE FIX: Fetch and cache account info immediately during OAuth
    # This prevents "Loading account..." from showing on refresh when there are API issues
    token_data = credentials_to_oauth_token_data(creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET)
    extra_data = token_data["extra_data"]
    
    try:
        # Get channel info to cache channel_name
        youtube = build('youtube', 'v3', credentials=creds)
        channels_response = youtube.channels().list(part='snippet', mine=True).execute()
        
        if channels_response.get('items') and len(channels_response['items']) > 0:
            channel = channels_response['items'][0]
            extra_data["channel_name"] = channel['snippet']['title']
            extra_data["channel_id"] = channel['id']
            youtube_logger.info(f"Cached YouTube channel info during OAuth: {extra_data['channel_name']}")
        
        # Get email from userinfo
        try:
            with httpx.Client(timeout=5.0) as client:
                userinfo_response = client.get(
                    'https://www.googleapis.com/oauth2/v2/userinfo',
                    headers={'Authorization': f'Bearer {creds.token}'}
                )
                if userinfo_response.status_code == 200:
                    userinfo = userinfo_response.json()
                    extra_data["email"] = userinfo.get('email')
                    youtube_logger.info(f"Cached YouTube email during OAuth: {extra_data.get('email')}")
        except Exception as email_error:
            youtube_logger.warning(f"Could not fetch email during OAuth: {email_error}, will try later")
    except Exception as fetch_error:
        youtube_logger.warning(f"Could not fetch channel info during OAuth: {fetch_error}, will try later")
    
    # Save OAuth token to database (encrypted) with cached account info
    save_oauth_token(
        user_id=user_id,
        platform="youtube",
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
        extra_data=extra_data,
        db=db
    )
    
    # Enable YouTube destination by default
    set_user_setting(user_id, "destinations", "youtube_enabled", True, db=db)
    
    youtube_logger.info(f"YouTube OAuth completed for user {user_id}")
    
    # ROOT CAUSE FIX: Return connection status directly from authoritative source
    # This eliminates race conditions - no need for separate API call
    youtube_status = {"connected": True, "enabled": True}
    status_param = quote(json.dumps(youtube_status))
    
    # Build redirect URL
    if settings.FRONTEND_URL:
        frontend_url = f"{settings.FRONTEND_URL}/app?connected=youtube&status={status_param}"
    else:
        host = request.headers.get("host", "localhost:8000")
        protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        frontend_url = f"{protocol}://{host.replace(':8000', ':3000')}/app?connected=youtube&status={status_param}"
    
    return {"redirect_url": frontend_url, "status": youtube_status}


# ============================================================================
# TIKTOK OAUTH FLOW
# ============================================================================

def initiate_tiktok_oauth_flow(user_id: int) -> Dict[str, str]:
    """Initiate TikTok OAuth flow - build authorization URL"""
    # Validate configuration
    if not settings.TIKTOK_CLIENT_KEY:
        raise ValueError("TikTok OAuth not configured. Missing TIKTOK_CLIENT_KEY.")
    
    # Build redirect URI (must match TikTok Developer Portal exactly)
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
    
    # Build scope string (comma-separated, no spaces)
    scope_string = ",".join(TIKTOK_SCOPES)
    
    # Build authorization URL with proper encoding
    params = {
        "client_key": settings.TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": scope_string,
        "redirect_uri": redirect_uri,
        "state": str(user_id),  # Pass user_id in state
    }
    
    query_string = urlencode(params, doseq=False)
    auth_url = f"{TIKTOK_AUTH_URL}?{query_string}"
    
    # Debug logging
    tiktok_logger.info(f"Initiating auth flow for user {user_id}")
    tiktok_logger.debug(f"Client Key: {settings.TIKTOK_CLIENT_KEY[:4]}...{settings.TIKTOK_CLIENT_KEY[-4:]}, "
                       f"Redirect URI: {redirect_uri}, Scope: {scope_string}")
    
    return {"url": auth_url}


async def complete_tiktok_oauth_flow(code: str, state: str, db: Session) -> Dict[str, any]:
    """Complete TikTok OAuth flow - exchange code, parse and save token, fetch account info"""
    # Validate required parameters
    if not code or not state:
        raise ValueError("Missing code or state")
    
    # Validate configuration
    if not settings.TIKTOK_CLIENT_KEY or not settings.TIKTOK_CLIENT_SECRET:
        raise ValueError("TikTok OAuth not configured. Missing credentials.")
    
    # Validate state (get user_id)
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        raise ValueError("Invalid state parameter")
    
    # Verify user exists
    user = get_user_by_id(user_id, db=db)
    if not user:
        raise ValueError("User not found")
    
    # Exchange authorization code for access token
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
    decoded_code = unquote(code) if code else None
    
    token_data = {
        "client_key": settings.TIKTOK_CLIENT_KEY,
        "client_secret": settings.TIKTOK_CLIENT_SECRET,
        "code": decoded_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    
    tiktok_logger.debug(f"Exchanging code for token for user {user_id}")
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            TIKTOK_TOKEN_URL,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if token_response.status_code != 200:
            error_text = token_response.text
            tiktok_logger.error(f"Token exchange failed: {error_text[:500]}")
            raise ValueError(f"Token exchange failed: {error_text[:500]}")
        
        token_json = token_response.json()
        
        # Log full OAuth response keys for debugging (mask sensitive values)
        response_keys = list(token_json.keys())
        has_refresh_token = "refresh_token" in token_json
        tiktok_logger.info(
            f"TikTok OAuth response for user {user_id}: "
            f"keys={response_keys}, has_refresh_token={has_refresh_token}, "
            f"has_access_token={'access_token' in token_json}, "
            f"has_open_id={'open_id' in token_json}"
        )
        
        if "access_token" not in token_json:
            tiktok_logger.error("No access_token in response")
            raise ValueError("No access_token in response")
        
        tiktok_logger.info(f"Token exchange successful for user {user_id} - Open ID: {token_json.get('open_id', 'N/A')}")
        
        # Log refresh token presence for debugging
        refresh_token = token_json.get("refresh_token")
        if not refresh_token:
            tiktok_logger.warning(
                f"TikTok OAuth did not return refresh_token for user {user_id}. "
                f"Response keys: {response_keys}. Token refresh will not be possible."
            )
        else:
            tiktok_logger.info(f"TikTok OAuth returned refresh_token for user {user_id} (length: {len(refresh_token)})")
        
        # Parse and save token response using DRY helper
        # This follows TikTok OAuth docs and ensures proper token storage
        access_token = _parse_and_save_tiktok_token_response(
            user_id=user_id,
            token_json=token_json,
            db=db,
            preserve_account_info=False  # Don't preserve on initial OAuth
        )
        
        # Fetch account info immediately and cache it
        # This prevents "Loading account..." from showing on refresh when token expires
        try:
            creator_info_response = await client.post(
                TIKTOK_CREATOR_INFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token.strip()}",  # Strip whitespace
                    "Content-Type": "application/json; charset=UTF-8"
                },
                json={},
                timeout=5.0
            )
            
            if creator_info_response.status_code == 200:
                creator_data = creator_info_response.json()
                creator_info = creator_data.get("data", {})
                
                # Update extra_data with account info
                token = get_oauth_token(user_id, "tiktok", db=db)
                if token:
                    extra_data = token.extra_data or {}
                    
                    # Cache display_name and username
                    if "creator_nickname" in creator_info:
                        extra_data["display_name"] = creator_info["creator_nickname"]
                    elif "display_name" in creator_info:
                        extra_data["display_name"] = creator_info["display_name"]
                    
                    if "creator_username" in creator_info:
                        extra_data["username"] = creator_info["creator_username"]
                    elif "username" in creator_info:
                        extra_data["username"] = creator_info["username"]
                    
                    if "creator_avatar_url" in creator_info:
                        extra_data["avatar_url"] = creator_info["creator_avatar_url"]
                    elif "avatar_url" in creator_info:
                        extra_data["avatar_url"] = creator_info["avatar_url"]
                    
                    # Cache full creator_info for privacy_level_options and interaction settings
                    extra_data["creator_info"] = creator_info
                    
                    # Update token with account info
                    token.extra_data = extra_data
                    db.commit()
                    
                    tiktok_logger.info(f"Cached TikTok account info during OAuth: {extra_data.get('display_name')} (@{extra_data.get('username')})")
            else:
                tiktok_logger.warning(f"Could not fetch creator info during OAuth (status {creator_info_response.status_code}), will try later")
        except Exception as fetch_error:
            tiktok_logger.warning(f"Could not fetch creator info during OAuth: {fetch_error}, will try later")
        
        # Enable TikTok destination
        set_user_setting(user_id, "destinations", "tiktok_enabled", True, db=db)
        
        tiktok_logger.info(f"TikTok OAuth completed for user {user_id}")
        
        # ROOT CAUSE FIX: Return connection status directly from authoritative source
        # This eliminates race conditions - no need for separate API call
        tiktok_status = {"connected": True, "enabled": True}
        status_param = quote(json.dumps(tiktok_status))
        
        # Build redirect URL
        redirect_url = f"{settings.FRONTEND_URL}/app?connected=tiktok&status={status_param}"
        
        return {"redirect_url": redirect_url, "status": tiktok_status}


# ============================================================================
# INSTAGRAM OAUTH FLOW
# ============================================================================

def initiate_instagram_oauth_flow(user_id: int) -> Dict[str, str]:
    """Initiate Instagram OAuth flow via Instagram Login - build authorization URL"""
    if not settings.INSTAGRAM_APP_ID or not settings.INSTAGRAM_APP_SECRET:
        raise ValueError("Instagram OAuth not configured. Missing INSTAGRAM_APP_ID or INSTAGRAM_APP_SECRET.")
    
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/instagram/callback"
    
    scope_string = ",".join(INSTAGRAM_SCOPES)
    
    params = {
        "client_id": settings.INSTAGRAM_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": scope_string,
        "response_type": "code",
        "state": str(user_id)
    }
    
    query_string = urlencode(params, doseq=False)
    auth_url = f"{INSTAGRAM_AUTH_URL}?{query_string}"
    
    instagram_logger.info(f"Initiating Instagram auth flow for user {user_id}")
    instagram_logger.info(f"Redirect URI: {redirect_uri}")
    instagram_logger.info(f"Scopes: {scope_string}")
    instagram_logger.info(f"Instagram App ID: {settings.INSTAGRAM_APP_ID[:8]}...")
    instagram_logger.debug(f"Full auth URL: {auth_url}")
    
    return {"url": auth_url}


async def complete_instagram_oauth_flow(code: str, state: str, db: Session) -> Dict[str, any]:
    """Complete Instagram OAuth flow - exchange code for token, get account info, save token"""
    if not code:
        raise ValueError("Missing authorization code")
    
    try:
        app_user_id = int(state)
    except (ValueError, TypeError):
        raise ValueError("Invalid state parameter")
    
    user = get_user_by_id(app_user_id, db=db)
    if not user:
        raise ValueError("User not found")
    
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/instagram/callback"
    
    async with httpx.AsyncClient() as client:
        # Step 1: Exchange authorization code for short-lived access token
        token_url = "https://api.instagram.com/oauth/access_token"
        token_data = {
            "client_id": settings.INSTAGRAM_APP_ID,
            "client_secret": settings.INSTAGRAM_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code
        }
        
        instagram_logger.info(f"Exchanging authorization code for short-lived token for user {app_user_id}")
        
        token_response = await client.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            error_data = token_response.json() if token_response.headers.get('content-type', '').startswith('application/json') else token_response.text
            instagram_logger.error(f"Token exchange failed: {error_data}")
            raise ValueError(f"Failed to exchange authorization code: {error_data}")
        
        token_json = token_response.json()
        
        # Instagram API can return two formats:
        # 1. Documented format: {"data": [{"access_token": "...", "user_id": "...", "permissions": "..."}]}
        # 2. Actual format: {"access_token": "...", "user_id": ..., "permissions": [...]}
        # Handle both for compatibility
        
        if "data" in token_json:
            # Nested format (documented)
            data = token_json.get("data", [])
            if not data or len(data) == 0:
                raise ValueError(f"No token data in response: {token_json}")
            token_data = data[0]
        else:
            # Flat format (actual API response)
            token_data = token_json
        
        short_lived_token = token_data.get("access_token")
        instagram_user_id = token_data.get("user_id")
        permissions = token_data.get("permissions", "")
        
        # Handle permissions as either string or list
        if isinstance(permissions, list):
            permissions = ",".join(permissions)
        
        if not short_lived_token:
            raise ValueError("No access token in response")
        
        instagram_logger.info(f"Received short-lived token for Instagram user {instagram_user_id}")
        instagram_logger.info(f"Granted permissions: {permissions}")
        
        # Step 2: Exchange short-lived token for long-lived token (60 days)
        instagram_logger.info("Exchanging short-lived token for long-lived token...")
        
        long_lived_url = "https://graph.instagram.com/access_token"
        long_lived_params = {
            "grant_type": "ig_exchange_token",
            "client_secret": settings.INSTAGRAM_APP_SECRET,
            "access_token": short_lived_token
        }
        
        long_lived_response = await client.get(long_lived_url, params=long_lived_params)
        
        if long_lived_response.status_code != 200:
            error_data = long_lived_response.json() if long_lived_response.headers.get('content-type', '').startswith('application/json') else long_lived_response.text
            instagram_logger.error(f"Long-lived token exchange failed: {error_data}")
            raise ValueError(f"Failed to get long-lived token: {error_data}")
        
        long_lived_json = long_lived_response.json()
        access_token = long_lived_json.get("access_token")
        expires_in = long_lived_json.get("expires_in")
        token_type = long_lived_json.get("token_type")
        
        instagram_logger.info(f"Successfully obtained long-lived token (expires in {expires_in}s / {expires_in // 86400} days)")
        
        # Step 3: Get Instagram account info using long-lived token
        me_url = f"{INSTAGRAM_GRAPH_API_BASE}/me"
        me_params = {
            "fields": "id,username,account_type",
            "access_token": access_token
        }
        
        instagram_logger.info("Fetching Instagram Business Account info")
        me_response = await client.get(me_url, params=me_params)
        
        if me_response.status_code != 200:
            error_data = me_response.json() if me_response.headers.get('content-type', '').startswith('application/json') else me_response.text
            instagram_logger.error(f"Failed to get Instagram account info: {error_data}")
            raise ValueError(f"Failed to get Instagram account info: {error_data}")
        
        me_data = me_response.json()
        business_account_id = me_data.get("id")
        username = me_data.get("username", "Unknown")
        account_type = me_data.get("account_type")
        
        instagram_logger.info(f"Instagram Account: @{username}, Type: {account_type}, ID: {business_account_id}")
        
        expires_at = None
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        
        save_oauth_token(
            user_id=app_user_id,
            platform="instagram",
            access_token=access_token,
            refresh_token=None,
            expires_at=expires_at,
            extra_data={
                "business_account_id": business_account_id,
                "username": username,
                "account_type": account_type,
                "instagram_user_id": instagram_user_id
            },
            db=db
        )
        
        set_user_setting(app_user_id, "destinations", "instagram_enabled", True, db=db)
        
        instagram_logger.info(f"Instagram connected successfully for user {app_user_id}")
        
        return {
            "success": True,
            "instagram": {
                "connected": True,
                "enabled": True
            }
        }


# ============================================================================
# PLATFORM DISCONNECTION
# ============================================================================

def disconnect_platform(user_id: int, platform: str, db: Session) -> Dict[str, str]:
    """Disconnect a platform OAuth account and disable destination"""
    delete_oauth_token(user_id, platform, db=db)
    set_user_setting(user_id, "destinations", f"{platform}_enabled", False, db=db)
    return {"message": "Disconnected"}


# ============================================================================
# TIKTOK MUSIC USAGE
# ============================================================================

def get_tiktok_music_usage_confirmed(user_id: int, db: Session) -> Dict[str, bool]:
    """Check if user has confirmed TikTok music usage"""
    tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
    return {"confirmed": tiktok_settings.get("music_usage_confirmed", False)}


def confirm_tiktok_music_usage(user_id: int, db: Session) -> Dict[str, bool]:
    """Mark that user has confirmed TikTok music usage"""
    set_user_setting(user_id, "tiktok", "music_usage_confirmed", True, db=db)
    return {"ok": True}

