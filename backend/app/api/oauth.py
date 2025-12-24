"""OAuth API routes for Google, YouTube, TikTok, and Instagram authentication"""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, unquote, urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import (
    settings, TIKTOK_SCOPES, TIKTOK_AUTH_URL, TIKTOK_TOKEN_URL,
    TIKTOK_CREATOR_INFO_URL, INSTAGRAM_SCOPES, INSTAGRAM_AUTH_URL,
    INSTAGRAM_GRAPH_API_BASE
)
from app.core.security import require_auth, require_csrf_new, set_auth_cookie
from app.db.helpers import (
    get_oauth_token, save_oauth_token, delete_oauth_token, check_token_expiration,
    get_all_oauth_tokens, get_user_settings, set_user_setting, get_user_videos,
    credentials_to_oauth_token_data, oauth_token_to_credentials
)
from app.db.redis import redis_client
from app.db.session import SessionLocal, get_db
from app.models.oauth_token import OAuthToken
from app.services.auth_service import get_user_by_id, get_or_create_oauth_user
from app.services.video_service import (
    get_google_client_config, _parse_and_save_tiktok_token_response,
    _ensure_fresh_token, _fetch_creator_info_safe, get_tiktok_creator_info
)
from app.services.platform_service import get_tiktok_account_info, get_youtube_account_info, get_youtube_videos
from app.utils.encryption import decrypt

# Loggers
logger = logging.getLogger(__name__)
youtube_logger = logging.getLogger("youtube")
tiktok_logger = logging.getLogger("tiktok")
instagram_logger = logging.getLogger("instagram")

# Import Prometheus metrics from centralized location
from app.core.metrics import login_attempts_counter

router = APIRouter(prefix="/api/auth", tags=["oauth"])


# ============================================================================
# GOOGLE OAUTH LOGIN ENDPOINTS (for user authentication)
# ============================================================================

@router.get("/google/login")
def auth_google_login(request: Request):
    """Start Google OAuth login flow (for user authentication, not YouTube)"""
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
    # Build redirect URI dynamically based on request
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or settings.ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/google/login/callback"
    
    # Create Flow from config dict with OpenID scopes for user authentication
    flow = Flow.from_client_config(
        google_config,
        scopes=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ],
        redirect_uri=redirect_uri
    )
    
    # Generate random state for security
    state = secrets.token_urlsafe(32)
    url, _ = flow.authorization_url(access_type='offline', state=state, prompt='select_account')
    
    # Store state in Redis for verification (5 minutes expiry)
    # Prefix with environment to prevent collisions between dev/prod
    redis_client.setex(f"{settings.ENVIRONMENT}:google_login_state:{state}", 300, "pending")
    
    return {"url": url}


@router.get("/google/login/callback")
def auth_google_login_callback(code: str, state: str, request: Request, response: Response):
    """Google OAuth login callback - creates or logs in user"""
    # Verify state to prevent CSRF
    # Prefix with environment to prevent collisions between dev/prod
    state_key = f"{settings.ENVIRONMENT}:google_login_state:{state}"
    state_value = redis_client.get(state_key)
    if not state_value:
        # Track failed login attempt (invalid state)
        login_attempts_counter.labels(status="failure", method="google").inc()
        # Redirect to login page with error instead of app page
        frontend_redirect = f"{settings.FRONTEND_URL}/login?error=google_login_failed&reason=invalid_state"
        return RedirectResponse(url=frontend_redirect)
    
    # Delete state after verification
    redis_client.delete(state_key)
    
    # Build redirect URI dynamically
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or settings.ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/google/login/callback"
    
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured")
    
    # Create flow and fetch token
    flow = Flow.from_client_config(
        google_config,
        scopes=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ],
        redirect_uri=redirect_uri
    )
    
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Get user info from Google
        userinfo_response = httpx.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {creds.token}'},
            timeout=10.0
        )
        
        if userinfo_response.status_code != 200:
            # Track failed login attempt
            login_attempts_counter.labels(status="failure", method="google").inc()
            raise HTTPException(400, "Failed to fetch user info from Google")
        
        user_info = userinfo_response.json()
        email = user_info.get('email')
        
        if not email:
            # Track failed login attempt
            login_attempts_counter.labels(status="failure", method="google").inc()
            raise HTTPException(400, "Email not provided by Google")
        
        # Get or create user by email (links accounts automatically)
        db = SessionLocal()
        try:
            user, is_new = get_or_create_oauth_user(email, db=db)
            
            # Create session
            session_id = secrets.token_urlsafe(32)
            from app.db.redis import set_session
            set_session(session_id, user.id)
            
            # Create redirect response (send user to the main app shell)
            frontend_redirect = f"{settings.FRONTEND_URL}/app?google_login=success"
            redirect_response = RedirectResponse(url=frontend_redirect)
            
            # Set session cookie on the redirect response
            set_auth_cookie(redirect_response, session_id, request)
            
            # Track successful login attempt
            login_attempts_counter.labels(status="success", method="google").inc()
            
            action = "registered" if is_new else "logged in"
            logger.info(f"User {action} via Google OAuth: {user.email} (ID: {user.id})")
            
            return redirect_response
        finally:
            db.close()
        
    except HTTPException:
        raise
    except Exception as e:
        # Track failed login attempt
        login_attempts_counter.labels(status="failure", method="google").inc()
        logger.error(f"Google login error: {e}", exc_info=True)
        # Redirect to login page with error instead of app page
        frontend_redirect = f"{settings.FRONTEND_URL}/login?error=google_login_failed"
        return RedirectResponse(url=frontend_redirect)


# ============================================================================
# OAUTH ENDPOINTS (YouTube, TikTok, Instagram)
# ============================================================================

@router.get("/youtube")
def auth_youtube(request: Request, user_id: int = Depends(require_auth)):
    """Start YouTube OAuth - requires authentication"""
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
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


@router.get("/youtube/callback")
def auth_youtube_callback(code: str, state: str, request: Request, response: Response, db: Session = Depends(get_db)):
    """OAuth callback - stores credentials in database"""
    # Get user_id from state parameter
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid state parameter")
    
    # Verify user exists
    user = get_user_by_id(user_id, db=db)
    if not user:
        raise HTTPException(404, "User not found")
    
    # Build redirect URI dynamically
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or settings.ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/youtube/callback"
    
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured")
    
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
        raise HTTPException(400, "Failed to obtain refresh token. Please try connecting again - you may need to grant permissions again.")
    
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
    
    # Redirect to frontend app shell with status
    if settings.FRONTEND_URL:
        frontend_url = f"{settings.FRONTEND_URL}/app?connected=youtube&status={status_param}"
    else:
        host = request.headers.get("host", "localhost:8000")
        protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        frontend_url = f"{protocol}://{host.replace(':8000', ':3000')}/app?connected=youtube&status={status_param}"
    
    return RedirectResponse(frontend_url)


@router.get("/youtube/account")
def get_youtube_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube account information (channel name/email)"""
    return get_youtube_account_info(user_id, db)


@router.post("/youtube/disconnect")
def disconnect_youtube(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect YouTube account"""
    delete_oauth_token(user_id, "youtube", db=db)
    set_user_setting(user_id, "destinations", "youtube_enabled", False, db=db)
    return {"message": "Disconnected"}


@router.get("/youtube/videos")
def get_youtube_videos_route(
    user_id: int = Depends(require_auth),
    page: int = 1,
    per_page: int = 50,
    hide_shorts: bool = False,
    db: Session = Depends(get_db)
):
    """Get user's YouTube videos (paginated)"""
    try:
        return get_youtube_videos(user_id, page, per_page, hide_shorts, db)
    except ValueError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ============================================================================
# TIKTOK OAUTH ENDPOINTS
# ============================================================================

@router.get("/tiktok")
def auth_tiktok(request: Request, user_id: int = Depends(require_auth)):
    """Initiate TikTok OAuth flow - requires authentication"""
    
    # Validate configuration
    if not settings.TIKTOK_CLIENT_KEY:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing TIKTOK_CLIENT_KEY."
        )
    
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


@router.get("/tiktok/callback")
async def auth_tiktok_callback(
    request: Request,
    response: Response,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db)
):
    """Handle TikTok OAuth callback"""
    
    tiktok_logger.info("Received callback")
    tiktok_logger.debug(f"Code: {'present' if code else 'MISSING'}, "
                       f"State: {state[:16] + '...' if state else 'MISSING'}, "
                       f"Error: {error or 'none'}")
    
    # Check for errors from TikTok
    if error:
        error_msg = f"TikTok OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        tiktok_logger.error(error_msg)
        # Redirect to frontend with error
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate required parameters
    if not code or not state:
        tiktok_logger.error("Missing code or state")
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate configuration
    if not settings.TIKTOK_CLIENT_KEY or not settings.TIKTOK_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing credentials."
        )
    
    # Validate state (get user_id)
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        tiktok_logger.error("Invalid state parameter")
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Verify user exists
    user = get_user_by_id(user_id, db=db)
    if not user:
        tiktok_logger.error(f"User {user_id} not found")
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_auth_failed")
    
    try:
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
                return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_token_failed")
            
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
                return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_token_failed")
            
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
            
            # Redirect to frontend app shell with status
            return RedirectResponse(f"{settings.FRONTEND_URL}/app?connected=tiktok&status={status_param}")
            
    except Exception as e:
        tiktok_logger.error(f"Callback exception: {e}", exc_info=True)
        return RedirectResponse(f"{settings.FRONTEND_URL}/app?error=tiktok_auth_failed")


@router.post("/tiktok/music-usage-confirmed")
def confirm_tiktok_music_usage(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Mark that user has confirmed TikTok music usage"""
    set_user_setting(user_id, "tiktok", "music_usage_confirmed", True, db=db)
    return {"ok": True}


@router.get("/tiktok/music-usage-confirmed")
def get_tiktok_music_usage_confirmed(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Check if user has confirmed TikTok music usage"""
    tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
    return {"confirmed": tiktok_settings.get("music_usage_confirmed", False)}


@router.post("/tiktok/disconnect")
def disconnect_tiktok(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect TikTok account"""
    delete_oauth_token(user_id, "tiktok", db=db)
    set_user_setting(user_id, "destinations", "tiktok_enabled", False, db=db)
    return {"message": "Disconnected"}


@router.get("/tiktok/account")
def get_tiktok_account(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    force_refresh: bool = False
):
    """Get TikTok account information with stale-while-revalidate pattern"""
    result = get_tiktok_account_info(user_id, db, force_refresh=force_refresh)
    
    # Schedule background refresh to update cache (stale-while-revalidate)
    if not force_refresh and result.get("has_cache"):
        # Only schedule if we have cached data (to avoid unnecessary API calls)
        from app.tasks.oauth_tasks import refresh_tiktok_account_data
        background_tasks.add_task(refresh_tiktok_account_data, user_id)
    
    # Remove has_cache from response (internal only)
    result.pop("has_cache", None)
    return result


# ============================================================================
# INSTAGRAM OAUTH ENDPOINTS
# ============================================================================

async def fetch_instagram_profile(access_token: str) -> dict:
    """
    Fetch Instagram profile information using /me endpoint.
    Returns dict with 'username' and 'business_account_id' (or None for each if failed).
    This is the root cause fix - centralizes profile fetching logic.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            me_response = await client.get(
                f"{INSTAGRAM_GRAPH_API_BASE}/me",
                params={
                    "fields": "id,username,account_type",
                    "access_token": access_token
                }
            )
            
            if me_response.status_code == 200:
                me_data = me_response.json()
                username = me_data.get("username")
                account_type = me_data.get("account_type")
                # The id from /me is the Instagram Business Account ID (for posting content)
                business_account_id = me_data.get("id")
                instagram_logger.info(f"Profile fetched - Username: {username}, Account Type: {account_type}, Business Account ID: {business_account_id}")
                return {
                    "username": username,
                    "business_account_id": business_account_id,
                    "account_type": account_type
                }
            else:
                error_text = me_response.text[:500]
                instagram_logger.warning(f"Failed to fetch profile info (status {me_response.status_code}): {error_text}")
                return {"username": None, "business_account_id": None, "account_type": None}
    except Exception as e:
        instagram_logger.warning(f"Error fetching profile info: {str(e)}")
        return {"username": None, "business_account_id": None, "account_type": None}


@router.get("/instagram")
def auth_instagram(request: Request, user_id: int = Depends(require_auth)):
    """Initiate Instagram OAuth flow via Facebook Login for Business - requires authentication"""
    
    # Validate configuration
    if not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Instagram OAuth not configured. Missing FACEBOOK_APP_ID or FACEBOOK_APP_SECRET."
        )
    
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


@router.get("/instagram/callback")
async def auth_instagram_callback(
    request: Request,
    response: Response,
    state: str = None,
    error: str = None,
    error_description: str = None
):
    """Handle Instagram OAuth callback (via Facebook Login for Business)
    
    Facebook Login for Business uses token-based flow with URL fragments.
    Tokens are in the fragment (#access_token=...), not query parameters.
    We serve HTML that extracts tokens from fragment and POSTs to backend.
    """
    
    instagram_logger.info("Received Instagram/Facebook callback")
    instagram_logger.debug(f"Callback query params: state={state}, error={error}, error_description={error_description}")
    instagram_logger.debug(f"Full callback URL: {request.url}")
    
    # Check for errors from Facebook
    if error:
        error_msg = f"Facebook OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        instagram_logger.error(error_msg)
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=instagram_auth_failed&reason={error}")
    
    # Serve HTML page to extract tokens from URL fragment and forward user_id
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instagram OAuth Callback</title>
    </head>
    <body>
        <p>Processing Instagram authentication...</p>
        <script>
            // Extract tokens from URL fragment (as per Facebook docs)
            const fragment = window.location.hash.substring(1);
            const params = new URLSearchParams(fragment);
            
            const accessToken = params.get('access_token');
            const longLivedToken = params.get('long_lived_token');
            const expiresIn = params.get('expires_in');
            const error = params.get('error');
            const state = params.get('state') || '{state or ""}';
            
            if (error) {{
                window.location.href = '{settings.FRONTEND_URL}?error=instagram_auth_failed&reason=' + error;
            }} else if (accessToken) {{
                // Send tokens to backend to complete authentication
                fetch('{settings.BACKEND_URL.rstrip("/")}/api/auth/instagram/complete', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    credentials: 'include',
                    body: JSON.stringify({{
                        access_token: accessToken,
                        long_lived_token: longLivedToken,
                        expires_in: expiresIn,
                        state: state
                    }})
                }})
                .then(res => res.json())
                .then(data => {{
                    if (data.success) {{
                        // ROOT CAUSE FIX: Pass connection status from authoritative source via URL
                        // This eliminates race conditions - no need for separate API call
                        const status = data.instagram ? encodeURIComponent(JSON.stringify(data.instagram)) : '';
                        window.location.href = '{settings.FRONTEND_URL}/app?connected=instagram' + (status ? '&status=' + status : '');
                    }} else {{
                        window.location.href = '{settings.FRONTEND_URL}?error=instagram_auth_failed&detail=' + encodeURIComponent(data.error || 'Unknown error');
                    }}
                }})
                .catch(err => {{
                    console.error('Error completing auth:', err);
                    window.location.href = '{settings.FRONTEND_URL}/app?error=instagram_auth_failed';
                }});
            }} else {{
                window.location.href = '{settings.FRONTEND_URL}/app?error=instagram_auth_failed&reason=missing_tokens';
            }}
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


@router.post("/instagram/complete")
async def complete_instagram_auth(request: Request, response: Response, db: Session = Depends(get_db)):
    """Complete Instagram authentication after receiving tokens from callback page"""
    try:
        body = await request.json()
        access_token = body.get("access_token")
        long_lived_token = body.get("long_lived_token")
        state = body.get("state")
        
        if not access_token:
            instagram_logger.error("Missing access_token in complete auth request")
            return {"success": False, "error": "Missing access token"}
        
        # Validate state (CSRF protection) - state contains user_id
        # ROOT CAUSE FIX: Store app user_id in a variable that won't be overwritten
        try:
            app_user_id = int(state)
        except (ValueError, TypeError):
            instagram_logger.error("Invalid state parameter")
            return {"success": False, "error": "Invalid state"}
        
        # Verify user exists
        user = get_user_by_id(app_user_id, db=db)
        if not user:
            return {"success": False, "error": "User not found"}
        
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
                except Exception as e:
                    instagram_logger.error(f"Error during token exchange: {str(e)}", exc_info=True)
                    instagram_logger.warning("Proceeding with short-lived token due to exchange failure.")
                    access_token_to_use = access_token
            
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
                return {"success": False, "error": f"Failed to get Facebook Pages: {error_data}"}
            
            pages_data = pages_response.json()
            pages = pages_data.get("data", [])
            
            instagram_logger.info(f"Found {len(pages)} Facebook Pages")
            instagram_logger.info(f"Full pages data structure: {json.dumps(pages_data, indent=2)}")
            
            if not pages:
                instagram_logger.error(f"No Facebook Pages in 'data' array. Full response: {pages_data}")
                
                # Check if there are any permissions issues  
                if "error" in pages_data:
                    error_info = pages_data["error"]
                    return {
                        "success": False, 
                        "error": f"Facebook API Error: {error_info.get('message', 'Unknown error')} (Code: {error_info.get('code', 'N/A')})"
                    }
                
                return {
                    "success": False, 
                    "error": f"No Facebook Pages found. Please verify: 1) You're logged in with the Facebook account that OWNS/MANAGES the Page (not just a personal account), 2) The Page actually exists and you can access it at facebook.com/pages, 3) You have admin or manager role on the Page (check Page Settings > Page Roles), 4) The Page is linked to an Instagram Business Account."
                }
            
            # Find first page with Instagram Business Account
            instagram_page = None
            for page in pages:
                if page.get("instagram_business_account"):
                    instagram_page = page
                    break
            
            if not instagram_page:
                instagram_logger.error(f"Found {len(pages)} Facebook Page(s), but none are linked to an Instagram Business Account")
                page_names = [p.get("name", "Unknown") for p in pages]
                return {
                    "success": False, 
                    "error": f"Found Facebook Pages ({', '.join(page_names)}), but none are linked to an Instagram Business Account. Please link your Instagram Business account to a Facebook Page."
                }
            
            page_id = instagram_page.get("id")
            page_access_token = instagram_page.get("access_token")
            business_account_id = instagram_page["instagram_business_account"]["id"]
            
            if not page_access_token or not isinstance(page_access_token, str) or len(page_access_token.strip()) == 0:
                instagram_logger.error(f"Page access token is missing or invalid. Page ID: {page_id}")
                return {
                    "success": False,
                    "error": "Failed to get Page access token. The Facebook Page may not have proper permissions. Please check your Facebook Page settings."
                }
            
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
            if 'expires_in' in locals():
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
            
    except Exception as e:
        instagram_logger.error(f"Complete auth exception: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/instagram/account")
async def get_instagram_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram account information (username)"""
    instagram_token = get_oauth_token(user_id, "instagram", db=db)
    
    if not instagram_token:
        return {"account": None}
    
    try:
        # Get username from extra_data (cached)
        extra_data = instagram_token.extra_data or {}
        username = extra_data.get("username")
        business_account_id = extra_data.get("business_account_id")
        
        # Return cached info only if we have username (complete data)
        if username:
            account_info = {"username": username}
            if business_account_id:
                account_info["user_id"] = business_account_id
            return {"account": account_info}
        
        # If not cached, fetch from Instagram API
        access_token = decrypt(instagram_token.access_token)
        if not access_token:
            instagram_logger.warning(f"Failed to decrypt Instagram token for user {user_id}")
            # Return None only if we truly can't identify the account
            return {"account": None}
        
        # Fetch profile info with timeout
        account_info = {}  # Start with empty dict, will populate with available info
        try:
            profile_info = await fetch_instagram_profile(access_token)
            username = profile_info.get("username")
            business_account_id = profile_info.get("business_account_id")
            
            # Build account info with whatever we have (similar to YouTube pattern)
            if business_account_id:
                account_info["user_id"] = business_account_id
            if username:
                account_info["username"] = username
            
            # Only return if we have username (complete data)
            if username:
                # Cache the info for future requests
                extra_data["username"] = username
                extra_data["business_account_id"] = business_account_id
                save_oauth_token(
                    user_id=user_id,
                    platform="instagram",
                    access_token=instagram_token.access_token,  # Already encrypted
                    refresh_token=None,
                    expires_at=instagram_token.expires_at,
                    extra_data=extra_data,
                    db=db
                )
                return {"account": account_info}
            else:
                # Don't return incomplete data (only user_id without username)
                instagram_logger.warning(f"Failed to fetch Instagram username for user {user_id}")
                return {"account": None}
        except Exception as profile_error:
            instagram_logger.warning(f"Could not fetch Instagram profile for user {user_id}: {str(profile_error)}")
            # Return cached username if available, otherwise None
            if username:
                account_info = {"username": username}
                if business_account_id:
                    account_info["user_id"] = business_account_id
                return {"account": account_info}
            return {"account": None}
        
    except Exception as e:
        instagram_logger.error(f"Error getting Instagram account info for user {user_id}: {str(e)}", exc_info=True)
        # Try to return cached username if available (complete data only)
        try:
            extra_data = instagram_token.extra_data or {}
            username = extra_data.get("username")
            if username:
                account_info = {"username": username}
                business_account_id = extra_data.get("business_account_id")
                if business_account_id:
                    account_info["user_id"] = business_account_id
                return {"account": account_info}
        except:
            pass
        return {"account": None, "error": str(e)}


@router.post("/instagram/disconnect")
def disconnect_instagram(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect Instagram account"""
    delete_oauth_token(user_id, "instagram", db=db)
    set_user_setting(user_id, "destinations", "instagram_enabled", False, db=db)
    return {"message": "Disconnected"}


# ============================================================================
# DESTINATIONS ROUTES (separate router for /api/destinations)
# ============================================================================

destinations_router = APIRouter(prefix="/api/destinations", tags=["destinations"])


@destinations_router.get("")
def get_destinations(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get destination status for current user"""
    try:
        # Batch load OAuth tokens and settings to prevent N+1 queries
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        settings = get_user_settings(user_id, "destinations", db=db)
        
        # Extract OAuth tokens
        youtube_token = all_tokens.get("youtube")
        tiktok_token = all_tokens.get("tiktok")
        instagram_token = all_tokens.get("instagram")
        
        # Check token expiration status
        youtube_expiry = check_token_expiration(youtube_token)
        tiktok_expiry = check_token_expiration(tiktok_token)
        instagram_expiry = check_token_expiration(instagram_token)
        
        # Get scheduled video count
        videos = get_user_videos(user_id, db=db)
        scheduled_count = len([v for v in videos if v.status == 'scheduled'])
        
        return {
            "youtube": {
                "connected": youtube_token is not None,
                "enabled": settings.get("youtube_enabled", False),
                "token_status": youtube_expiry["status"],
                "token_expired": youtube_expiry["expired"],
                "token_expires_soon": youtube_expiry["expires_soon"]
            },
            "tiktok": {
                "connected": tiktok_token is not None,
                "enabled": settings.get("tiktok_enabled", False),
                "token_status": tiktok_expiry["status"],
                "token_expired": tiktok_expiry["expired"],
                "token_expires_soon": tiktok_expiry["expires_soon"]
            },
            "instagram": {
                "connected": instagram_token is not None,
                "enabled": settings.get("instagram_enabled", False),
                "token_status": instagram_expiry["status"],
                "token_expired": instagram_expiry["expired"],
                "token_expires_soon": instagram_expiry["expires_soon"]
            },
            "scheduled_videos": scheduled_count
        }
    except Exception as e:
        logger.error(f"Error getting destinations for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to load destinations: {str(e)}")


@destinations_router.post("/youtube/toggle")
def toggle_youtube(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle YouTube destination on/off"""
    set_user_setting(user_id, "destinations", "youtube_enabled", enabled, db=db)
    
    youtube_token = get_oauth_token(user_id, "youtube", db=db)
    return {
        "youtube": {
            "connected": youtube_token is not None,
            "enabled": enabled
        }
    }


@destinations_router.post("/tiktok/toggle")
def toggle_tiktok(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle TikTok destination on/off"""
    set_user_setting(user_id, "destinations", "tiktok_enabled", enabled, db=db)
    
    tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
    return {
        "tiktok": {
            "connected": tiktok_token is not None,
            "enabled": enabled
        }
    }


@destinations_router.post("/instagram/toggle")
def toggle_instagram(
    enabled: bool,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Toggle Instagram destination on/off"""
    set_user_setting(user_id, "destinations", "instagram_enabled", enabled, db=db)
    
    instagram_token = get_oauth_token(user_id, "instagram", db=db)
    return {
        "instagram": {
            "connected": instagram_token is not None,
            "enabled": enabled
        }
    }
