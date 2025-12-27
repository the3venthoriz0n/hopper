"""TikTok API client - token management, API calls, rate limiting"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import httpx
from sqlalchemy.orm import Session

from app.core.config import (
    settings, TIKTOK_CREATOR_INFO_URL, TIKTOK_STATUS_URL,
    TIKTOK_RATE_LIMIT_REQUESTS, TIKTOK_RATE_LIMIT_WINDOW
)
from app.db.helpers import (
    get_oauth_token, check_token_expiration, save_oauth_token,
    delete_oauth_token, set_user_setting
)
from app.db.redis import (
    increment_rate_limit, get_token_check_cooldown, set_token_check_cooldown,
    redis_client
)
from app.utils.encryption import decrypt
from app.services.video.config import TOKEN_REFRESH_LOCK_TIMEOUT

tiktok_logger = logging.getLogger("tiktok")


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
        content_type = response.headers.get("content-type", "unknown")
        response_text = response.text[:500] if response.text else "(empty response)"
        
        try:
            error = response.json().get("error", {})
            error_code = error.get("code", "unknown")
            error_message = error.get("message", response_text)
            raise Exception(
                f"Failed to query creator info (HTTP {response.status_code}): "
                f"{error_code} - {error_message}"
            )
        except json.JSONDecodeError:
            raise Exception(
                f"Failed to query creator info (HTTP {response.status_code}): "
                f"Non-JSON response. Content-Type: {content_type}, "
                f"Response: {response_text}"
            )
    
    if not response.text or not response.text.strip():
        raise Exception(
            f"Failed to query creator info (HTTP {response.status_code}): "
            f"Empty response body from TikTok API"
        )
    
    try:
        response_json = response.json()
    except json.JSONDecodeError as e:
        content_type = response.headers.get("content-type", "unknown")
        response_preview = response.text[:500] if response.text else "(empty)"
        raise Exception(
            f"Failed to parse creator info response (HTTP {response.status_code}): "
            f"Invalid JSON. Content-Type: {content_type}, "
            f"Response preview: {response_preview}, "
            f"JSON error: {str(e)}"
        )
    
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

