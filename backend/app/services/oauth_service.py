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
from app.db.redis import get_redis_client
from app.services.auth_service import get_user_by_id
from app.services.video.helpers import get_google_client_config
from app.services.video.platforms.tiktok_api import _parse_and_save_tiktok_token_response
from app.utils.encryption import decrypt

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
    # ROOT CAUSE FIX: Add prompt='select_account consent' to force Google to show account selection
    # and always return refresh_token. Without this, Google only returns refresh_token on first authorization
    url, state = flow.authorization_url(
        access_type='offline',
        prompt='select_account consent',
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
        "force_login": "1",  # Force account selection on reconnect
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
        
        # Step 2.5: Validate permissions - ensure required scopes are granted
        required_permissions = set(INSTAGRAM_SCOPES)
        
        # Parse permissions from initial token response (already converted to string if it was a list)
        granted_permissions_set = set(p.strip() for p in permissions.split(",") if p.strip()) if permissions else set()
        
        instagram_logger.info(f"Required permissions: {required_permissions}")
        instagram_logger.info(f"Granted permissions: {granted_permissions_set}")
        
        # Check if all required permissions are granted
        missing_permissions = required_permissions - granted_permissions_set
        if missing_permissions:
            error_msg = f"Missing required Instagram permissions: {missing_permissions}. Granted: {granted_permissions_set}"
            instagram_logger.error(f"Permission validation failed for user {app_user_id}: {error_msg}")
            raise ValueError(error_msg)
        
        # Additional validation: Verify token works and has correct permissions via API call
        # This will be done in Step 3 when we fetch account info, but we can also verify permissions endpoint
        try:
            permissions_url = f"{INSTAGRAM_GRAPH_API_BASE}/me/permissions"
            permissions_params = {"access_token": access_token}
            permissions_response = await client.get(permissions_url, params=permissions_params)
            
            if permissions_response.status_code == 200:
                permissions_data = permissions_response.json()
                instagram_logger.debug(f"Instagram permissions API response: {permissions_data}")
            else:
                # Permissions endpoint may not be available, but token should still work
                instagram_logger.debug(f"Could not verify permissions via API (status {permissions_response.status_code}), but token exchange succeeded")
        except Exception as perm_error:
            # Permissions check is best-effort, don't fail OAuth if it errors
            instagram_logger.debug(f"Could not verify permissions via API: {perm_error}, but token exchange succeeded")
        
        instagram_logger.info(f"Permission validation passed for user {app_user_id}")
        
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
# TOKEN REVOCATION HELPERS
# ============================================================================

async def revoke_youtube_token(access_token: str) -> bool:
    """Revoke YouTube/Google OAuth token with the provider
    
    Args:
        access_token: The access token to revoke (decrypted)
        
    Returns:
        True if revocation succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": access_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if response.status_code == 200:
                youtube_logger.info("Successfully revoked YouTube token with provider")
                return True
            else:
                youtube_logger.warning(f"YouTube token revocation returned status {response.status_code}: {response.text[:200]}")
                return False
    except Exception as e:
        youtube_logger.warning(f"Failed to revoke YouTube token with provider: {e}")
        return False


async def revoke_tiktok_token(access_token: str) -> bool:
    """Revoke TikTok OAuth token with the provider
    
    Args:
        access_token: The access token to revoke (decrypted)
        
    Returns:
        True if revocation succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # TikTok uses form-encoded data, not JSON, and requires client credentials
            response = await client.post(
                "https://open.tiktokapis.com/v2/oauth/revoke/",
                data={
                    "client_key": settings.TIKTOK_CLIENT_KEY,
                    "client_secret": settings.TIKTOK_CLIENT_SECRET,
                    "token": access_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=5.0
            )
            if response.status_code == 200:
                tiktok_logger.info("Successfully revoked TikTok token with provider")
                return True
            else:
                tiktok_logger.warning(f"TikTok token revocation returned status {response.status_code}: {response.text[:200]}")
                return False
    except Exception as e:
        tiktok_logger.warning(f"Failed to revoke TikTok token with provider: {e}")
        return False


async def revoke_instagram_token(access_token: str, user_id: str) -> bool:
    """Revoke Instagram OAuth token with the provider
    
    Args:
        access_token: The access token to revoke (decrypted)
        user_id: The Instagram user ID (business_account_id from extra_data)
        
    Returns:
        True if revocation succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Instagram uses DELETE method to revoke permissions
            url = f"{INSTAGRAM_GRAPH_API_BASE}/{user_id}/permissions"
            response = await client.delete(
                url,
                params={"access_token": access_token}
            )
            if response.status_code == 200:
                instagram_logger.info(f"Successfully revoked Instagram token with provider for user {user_id}")
                return True
            else:
                # Check if error indicates token is already invalid/expired
                error_text = response.text[:500] if response.text else ""
                error_json = None
                try:
                    if response.headers.get('content-type', '').startswith('application/json'):
                        error_json = response.json()
                except:
                    pass
                
                # Handle expected expired/invalid token errors gracefully
                if response.status_code == 400:
                    error_message = ""
                    if error_json and isinstance(error_json, dict):
                        error_obj = error_json.get('error', {})
                        error_message = error_obj.get('message', '')
                        error_code = error_obj.get('code')
                        
                        # Token already invalid/expired - this is expected, don't log as error
                        if error_code == 190 or "not authorized" in error_message.lower() or "invalid" in error_message.lower():
                            instagram_logger.debug(f"Instagram token already invalid/expired for user {user_id}, skipping revocation (expected)")
                            return True  # Consider this success since token is already invalid
                    
                    # Other 400 errors - log as warning but don't fail
                    instagram_logger.debug(f"Instagram token revocation returned 400: {error_text}")
                    return True  # Still consider success - token may already be invalid
                else:
                    # Unexpected errors (network, API changes, etc.) - log as warning
                    instagram_logger.warning(f"Instagram token revocation returned status {response.status_code}: {error_text}")
                    return False
    except Exception as e:
        # Network errors or other exceptions - log but don't fail
        instagram_logger.debug(f"Failed to revoke Instagram token with provider (token may already be invalid): {e}")
        return False


# ============================================================================
# PLATFORM DISCONNECTION
# ============================================================================

async def disconnect_platform(user_id: int, platform: str, db: Session) -> Dict[str, str]:
    """Disconnect a platform OAuth account and disable destination
    
    Revokes the token with the OAuth provider before deleting from our database
    to ensure users can choose a different account on next connect.
    """
    # Get token before deletion so we can revoke it
    token = get_oauth_token(user_id, platform, db=db)
    
    if token:
        try:
            # Check if token is expired before attempting revocation
            from app.db.helpers import check_token_expiration
            token_expiry = check_token_expiration(token)
            is_expired = token_expiry.get("expired", False)
            
            if is_expired:
                # Token is already expired - skip revocation (it's already invalid)
                logger.debug(f"Token for user {user_id}, platform {platform} is expired, skipping revocation")
            else:
                # Decrypt access token for revocation
                access_token = decrypt(token.access_token)
                
                if access_token:
                    # Revoke token with OAuth provider (best-effort, don't fail if it errors)
                    if platform == "youtube":
                        await revoke_youtube_token(access_token)
                    elif platform == "tiktok":
                        await revoke_tiktok_token(access_token)
                    elif platform == "instagram":
                        # Get Instagram user ID from extra_data
                        extra_data = token.extra_data or {}
                        instagram_user_id = extra_data.get("business_account_id") or extra_data.get("instagram_user_id")
                        if instagram_user_id:
                            await revoke_instagram_token(access_token, str(instagram_user_id))
                        else:
                            instagram_logger.debug(f"Could not find Instagram user ID in extra_data for user {user_id}, skipping revocation")
        except ValueError as e:
            # Decryption failed - log but continue with deletion
            logger.debug(f"Failed to decrypt token for revocation (user {user_id}, platform {platform}): {e}")
        except Exception as e:
            # Any other error during revocation - log but continue
            logger.debug(f"Error during token revocation (user {user_id}, platform {platform}): {e}")
    
    # Delete token from our database and disable destination
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

