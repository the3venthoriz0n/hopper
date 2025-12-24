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
from app.services.video_service import (
    get_google_client_config, _parse_and_save_tiktok_token_response
)

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
    """Initiate Instagram OAuth flow via Facebook Login for Business - build authorization URL"""
    # Validate configuration
    if not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        raise ValueError("Instagram OAuth not configured. Missing FACEBOOK_APP_ID or FACEBOOK_APP_SECRET.")
    
    # Build redirect URI
    redirect_uri = f"{settings.BACKEND_URL.rstrip('/')}/api/auth/instagram/callback"
    
    # Build scope string (comma-separated for Facebook)
    scope_string = ",".join(INSTAGRAM_SCOPES)
    
    # Build Facebook Login for Business authorization URL
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": scope_string,
        "response_type": "token",  # Required for Facebook Login for Business
        "display": "page",  # Required for Business Login
        "extras": '{"setup":{"channel":"IG_API_ONBOARDING"}}',  # Required for Business Login onboarding
        "state": str(user_id)  # Pass user_id in state for CSRF protection
    }
    
    query_string = urlencode(params, doseq=False)
    auth_url = f"{INSTAGRAM_AUTH_URL}?{query_string}"
    
    instagram_logger.info(f"Initiating Instagram auth flow for user {user_id}")
    instagram_logger.info(f"Redirect URI: {redirect_uri}")
    instagram_logger.info(f"Scopes: {scope_string}")
    instagram_logger.info(f"Facebook App ID: {settings.FACEBOOK_APP_ID[:8]}...")
    instagram_logger.debug(f"Full auth URL: {auth_url}")
    
    return {"url": auth_url}


async def complete_instagram_oauth_flow(access_token: str, long_lived_token: Optional[str], state: str, db: Session) -> Dict[str, any]:
    """Complete Instagram OAuth flow - exchange for long-lived token, fetch Facebook Pages, find Instagram Business Account, save token"""
    if not access_token:
        raise ValueError("Missing access token")
    
    # Validate state (CSRF protection) - state contains user_id
    # ROOT CAUSE FIX: Store app user_id in a variable that won't be overwritten
    try:
        app_user_id = int(state)
    except (ValueError, TypeError):
        raise ValueError("Invalid state parameter")
    
    # Verify user exists
    user = get_user_by_id(app_user_id, db=db)
    if not user:
        raise ValueError("User not found")
    
    # Exchange short-lived token for long-lived token if needed
    async with httpx.AsyncClient() as client:
        access_token_to_use = long_lived_token if long_lived_token else access_token
        
        # If we don't have a long-lived token, exchange the short-lived one
        if not long_lived_token:
            instagram_logger.info("Exchanging short-lived token for long-lived token...")
            try:
                exchange_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/oauth/access_token"
                exchange_params = {
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.FACEBOOK_APP_ID,
                    "client_secret": settings.FACEBOOK_APP_SECRET,
                    "fb_exchange_token": access_token
                }
                exchange_response = await client.get(exchange_url, params=exchange_params)
                exchange_response.raise_for_status()
                exchange_data = exchange_response.json()
                access_token_to_use = exchange_data.get("access_token")
                expires_in = exchange_data.get("expires_in")
                instagram_logger.info(f"Successfully exchanged for long-lived token (expires in {expires_in}s)")
            except httpx.HTTPStatusError as e:
                error_detail = e.response.json() if e.response.headers.get('content-type', '').startswith('application/json') else e.response.text
                instagram_logger.error(f"Failed to exchange token for long-lived: {error_detail}", exc_info=True)
                # Fallback to short-lived token if exchange fails
                instagram_logger.warning("Proceeding with short-lived token due to exchange failure.")
                access_token_to_use = access_token
                expires_in = None
            except Exception as e:
                instagram_logger.error(f"Error during token exchange: {str(e)}", exc_info=True)
                instagram_logger.warning("Proceeding with short-lived token due to exchange failure.")
                access_token_to_use = access_token
                expires_in = None
        else:
            expires_in = None
        
        instagram_logger.info(f"Using access token: {access_token_to_use[:20]}...")
        
        # Get Facebook Pages the user manages (Step 4 from docs)
        pages_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/me/accounts"
        pages_params = {
            "fields": "id,name,access_token,instagram_business_account",
            "access_token": access_token_to_use
        }
        
        instagram_logger.info("Fetching Facebook Pages")
        instagram_logger.debug(f"Request URL: {pages_url}")
        instagram_logger.debug(f"Request params: fields={pages_params['fields']}")
        instagram_logger.debug(f"Using access token: {access_token_to_use[:20]}...")
        
        pages_response = await client.get(pages_url, params=pages_params)
        
        instagram_logger.debug(f"Response status: {pages_response.status_code}")
        instagram_logger.info(f"FULL Response body: {pages_response.text}")
        instagram_logger.info(f"Response headers: {dict(pages_response.headers)}")
        
        if pages_response.status_code != 200:
            error_data = pages_response.json() if pages_response.headers.get('content-type', '').startswith('application/json') else pages_response.text
            instagram_logger.error(f"Failed to get Facebook pages: {error_data}")
            raise ValueError(f"Failed to get Facebook Pages: {error_data}")
        
        pages_data = pages_response.json()
        pages = pages_data.get("data", [])
        
        instagram_logger.info(f"Found {len(pages)} Facebook Pages")
        instagram_logger.info(f"Full pages data structure: {json.dumps(pages_data, indent=2)}")
        
        if not pages:
            instagram_logger.error(f"No Facebook Pages in 'data' array. Full response: {pages_data}")
            
            # Check if there are any permissions issues  
            if "error" in pages_data:
                error_info = pages_data["error"]
                raise ValueError(f"Facebook API Error: {error_info.get('message', 'Unknown error')} (Code: {error_info.get('code', 'N/A')})")
            
            raise ValueError(
                "No Facebook Pages found. Please verify: 1) You're logged in with the Facebook account that OWNS/MANAGES the Page (not just a personal account), "
                "2) The Page actually exists and you can access it at facebook.com/pages, "
                "3) You have admin or manager role on the Page (check Page Settings > Page Roles), "
                "4) The Page is linked to an Instagram Business Account."
            )
        
        # Find first page with Instagram Business Account
        instagram_page = None
        for page in pages:
            if page.get("instagram_business_account"):
                instagram_page = page
                break
        
        if not instagram_page:
            instagram_logger.error(f"Found {len(pages)} Facebook Page(s), but none are linked to an Instagram Business Account")
            page_names = [p.get("name", "Unknown") for p in pages]
            raise ValueError(
                f"Found Facebook Pages ({', '.join(page_names)}), but none are linked to an Instagram Business Account. "
                "Please link your Instagram Business account to a Facebook Page."
            )
        
        page_id = instagram_page.get("id")
        page_access_token = instagram_page.get("access_token")
        business_account_id = instagram_page["instagram_business_account"]["id"]
        
        if not page_access_token or not isinstance(page_access_token, str) or len(page_access_token.strip()) == 0:
            instagram_logger.error(f"Page access token is missing or invalid. Page ID: {page_id}")
            raise ValueError(
                "Failed to get Page access token. The Facebook Page may not have proper permissions. "
                "Please check your Facebook Page settings."
            )
        
        instagram_logger.info(f"Using Facebook Page ID: {page_id}, Instagram Business Account: {business_account_id}")
        instagram_logger.debug(f"Page access token: {page_access_token[:20]}... (length: {len(page_access_token)})")
        
        # Get Instagram username
        username_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{business_account_id}"
        username_params = {
            "fields": "username",
            "access_token": page_access_token
        }
        
        username_response = await client.get(username_url, params=username_params)
        username = "Unknown"
        if username_response.status_code == 200:
            username_data = username_response.json()
            username = username_data.get("username", "Unknown")
        
        instagram_logger.info(f"Instagram Username: @{username} for user {app_user_id}")
        
        # Calculate expiry (Instagram tokens are long-lived)
        expires_at = None
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        
        # Store in database (encrypted)
        # ROOT CAUSE FIX: Use app_user_id (from state), not facebook_user_id
        save_oauth_token(
            user_id=app_user_id,
            platform="instagram",
            access_token=page_access_token,
            refresh_token=None,  # Instagram doesn't use refresh tokens
            expires_at=expires_at,
            extra_data={
                "user_access_token": access_token_to_use,
                "page_id": page_id,
                "business_account_id": business_account_id,
                "username": username
            },
            db=db
        )
        
        # Enable Instagram destination
        set_user_setting(app_user_id, "destinations", "instagram_enabled", True, db=db)
        
        instagram_logger.info(f"Instagram connected successfully for user {app_user_id}")
        
        # ROOT CAUSE FIX: Return connection status directly from the authoritative source
        # This eliminates the need for a separate API call and prevents race conditions
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

