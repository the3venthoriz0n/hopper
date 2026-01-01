"""OAuth API routes for Google, YouTube, TikTok, and Instagram authentication"""
import json
import logging
from urllib.parse import quote
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_auth, require_csrf_new, set_auth_cookie
from app.db.session import SessionLocal, get_db
from app.services.auth_service import (
    initiate_google_oauth_login, complete_google_oauth_login
)
from app.services.platform_service import (
    get_tiktok_account_info, get_youtube_account_info, get_youtube_videos,
    get_instagram_account_info
)
from app.services.oauth_service import (
    initiate_youtube_oauth_flow, complete_youtube_oauth_flow,
    initiate_tiktok_oauth_flow, complete_tiktok_oauth_flow,
    initiate_instagram_oauth_flow, complete_instagram_oauth_flow,
    disconnect_platform,
    get_tiktok_music_usage_confirmed, confirm_tiktok_music_usage
)

# Loggers
logger = logging.getLogger(__name__)
youtube_logger = logging.getLogger("youtube")
tiktok_logger = logging.getLogger("tiktok")
instagram_logger = logging.getLogger("instagram")

router = APIRouter(prefix="/api/auth", tags=["oauth"])


# ============================================================================
# GOOGLE OAUTH LOGIN ENDPOINTS (for user authentication)
# ============================================================================

@router.get("/google/login")
def auth_google_login(request: Request):
    """Start Google OAuth login flow (for user authentication, not YouTube)"""
    try:
        return initiate_google_oauth_login(request)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/google/login/callback")
def auth_google_login_callback(code: str, state: str, request: Request, response: Response):
    """Google OAuth login callback - creates or logs in user"""
    db = SessionLocal()
    try:
        result, session_id, is_new = complete_google_oauth_login(code, state, request, db)
        
        # Create redirect response (send user to the main app shell)
        redirect_response = RedirectResponse(url=result["redirect_url"])
        
        # Set session cookie on the redirect response
        set_auth_cookie(redirect_response, session_id, request)
        
        return redirect_response
    except ValueError as e:
        # Redirect to login page with error instead of app page
        frontend_redirect = f"{settings.FRONTEND_URL}/login?error=google_login_failed&reason={str(e)}"
        return RedirectResponse(url=frontend_redirect)
    except Exception as e:
        logger.error(f"Google login error: {e}", exc_info=True)
        # Redirect to login page with error instead of app page
        frontend_redirect = f"{settings.FRONTEND_URL}/login?error=google_login_failed"
        return RedirectResponse(url=frontend_redirect)
    finally:
        db.close()


# ============================================================================
# OAUTH ENDPOINTS (YouTube, TikTok, Instagram)
# ============================================================================

@router.get("/youtube")
def auth_youtube(request: Request, user_id: int = Depends(require_auth)):
    """Start YouTube OAuth - requires authentication"""
    try:
        return initiate_youtube_oauth_flow(user_id, request)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/youtube/callback")
def auth_youtube_callback(code: str, state: str, request: Request, response: Response, db: Session = Depends(get_db)):
    """OAuth callback - stores credentials in database"""
    try:
        result = complete_youtube_oauth_flow(code, state, request, db)
        return RedirectResponse(result["redirect_url"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        youtube_logger.error(f"YouTube OAuth callback error: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/youtube/account")
def get_youtube_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube account information (channel name/email)"""
    return get_youtube_account_info(user_id, db)


@router.post("/youtube/disconnect")
def disconnect_youtube(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect YouTube account"""
    return disconnect_platform(user_id, "youtube", db)


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
    try:
        return initiate_tiktok_oauth_flow(user_id)
    except ValueError as e:
        raise HTTPException(500, str(e))


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
    
    try:
        result = await complete_tiktok_oauth_flow(code, state, db)
        return RedirectResponse(result["redirect_url"])
    except ValueError as e:
        tiktok_logger.error(f"TikTok OAuth callback error: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=tiktok_auth_failed")
    except Exception as e:
        tiktok_logger.error(f"Callback exception: {e}", exc_info=True)
        return RedirectResponse(f"{settings.FRONTEND_URL}/app?error=tiktok_auth_failed")


@router.post("/tiktok/music-usage-confirmed")
def confirm_tiktok_music_usage_route(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Mark that user has confirmed TikTok music usage"""
    return confirm_tiktok_music_usage(user_id, db)


@router.get("/tiktok/music-usage-confirmed")
def get_tiktok_music_usage_confirmed_route(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Check if user has confirmed TikTok music usage"""
    return get_tiktok_music_usage_confirmed(user_id, db)


@router.post("/tiktok/disconnect")
def disconnect_tiktok(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect TikTok account"""
    return disconnect_platform(user_id, "tiktok", db)


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

@router.get("/instagram")
def auth_instagram(request: Request, user_id: int = Depends(require_auth)):
    """Initiate Instagram OAuth flow via Facebook Login for Business - requires authentication"""
    try:
        return initiate_instagram_oauth_flow(user_id)
    except ValueError as e:
        raise HTTPException(500, str(e))


@router.get("/instagram/callback")
async def auth_instagram_callback(
    request: Request,
    response: Response,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db)
):
    """Handle Instagram OAuth callback (Instagram Login)"""
    
    instagram_logger.info("Received Instagram callback")
    instagram_logger.debug(f"Callback query params: code={'present' if code else 'MISSING'}, state={state}, error={error}")
    
    if error:
        error_msg = f"Instagram OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        instagram_logger.error(error_msg)
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=instagram_auth_failed&reason={error}")
    
    try:
        result = await complete_instagram_oauth_flow(code, state, db)
        status_param = quote(json.dumps(result.get("instagram", {})))
        redirect_url = f"{settings.FRONTEND_URL}/app?connected=instagram&status={status_param}"
        return RedirectResponse(redirect_url)
    except ValueError as e:
        instagram_logger.error(f"Instagram OAuth error: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}?error=instagram_auth_failed&reason={str(e)}")
    except Exception as e:
        instagram_logger.error(f"Callback exception: {str(e)}", exc_info=True)
        return RedirectResponse(f"{settings.FRONTEND_URL}/app?error=instagram_auth_failed")


@router.get("/instagram/account")
async def get_instagram_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram account information (username)"""
    return await get_instagram_account_info(user_id, db)


@router.post("/instagram/disconnect")
def disconnect_instagram(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect Instagram account"""
    return disconnect_platform(user_id, "instagram", db)
