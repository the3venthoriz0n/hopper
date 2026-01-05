"""Security dependencies, middleware, and rate limiting"""
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, Header, HTTPException, Request, Response
from app.db.redis import get_session, get_csrf_token, set_csrf_token, set_user_activity, check_rate_limit as redis_check_rate_limit
from app.core.config import settings

security_logger = logging.getLogger("security")
api_access_logger = logging.getLogger("api_access")


def require_auth(request: Request) -> int:
    """Dependency: Require authentication, return user_id
    
    Note: Rate limiting is handled in middleware, not here, to avoid duplication.
    """
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        raise HTTPException(401, "Not authenticated. Please log in.")
    
    user_id = get_session(session_id)
    if not user_id:
        raise HTTPException(401, "Session expired. Please log in again.")
    
    # Track user activity (heartbeat) - simple and extensible
    # This updates the activity key with TTL, so we can count active users
    try:
        set_user_activity(user_id)
    except Exception:
        # Never let activity tracking break authentication
        pass
    
    return user_id


async def require_csrf_new(
    request: Request,
    user_id: int = Depends(require_auth),
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token")  # Explicitly map the header name
) -> int:
    session_id = request.cookies.get("session_id")
    
    # 1. Try to get token from FastAPI's header injection
    csrf_token = x_csrf_token
    
    # 2. Fallback: Manually check headers if alias failed
    if not csrf_token:
        csrf_token = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")

    # 3. Fallback: Form data
    if not csrf_token:
        try:
            form_data = await request.form()
            csrf_token = form_data.get("csrf_token")
        except: pass

    # DEBUG LOG (Temporary)
    # print(f"DEBUG: Session: {session_id}, Received: {csrf_token}")

    expected_csrf = get_csrf_token(session_id)
    
    if not expected_csrf or csrf_token != expected_csrf:
        exp_prefix = expected_csrf[:5] if expected_csrf else "None"
        rec_prefix = csrf_token[:5] if csrf_token else "None"
        security_logger.warning(
            f"CSRF validation failed - User: {user_id}, "
            f"Expected: {exp_prefix}..., Received: {rec_prefix}..."
        )
        raise HTTPException(403, "Invalid or missing CSRF token")
    
    return user_id


def get_client_identifier(request: Request, session_id: Optional[str] = None) -> str:
    """Get a unique identifier for rate limiting"""
    if session_id:
        return f"session:{session_id}"
    
    # Fallback to IP address
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def check_rate_limit(identifier: str, strict: bool = False) -> bool:
    """Check if request is within rate limit
    
    Args:
        identifier: Client identifier (session ID or IP)
        strict: If True, use stricter rate limits for state-changing operations
        
    Returns:
        True if within limit, False if exceeded
    """
    try:
        return redis_check_rate_limit(identifier, strict=strict)
    except Exception as e:
        security_logger.error(f"Rate limit check failed: {e}")
        # Fail open - allow request if rate limiting system is down
        return True


def validate_origin_referer(request: Request) -> bool:
    """Validate Origin and Referer headers"""
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    
    # Get allowed origins from config
    allowed_origins = [settings.FRONTEND_URL]
    
    # In development and test, be more lenient
    if settings.ENVIRONMENT in ("development", "test"):
        allowed_origins.extend([
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000"
        ])
        # Allow requests without Origin/Referer in development/test
        if not origin and not referer:
            return True
    
    # Check origin
    if origin:
        origin_normalized = origin.rstrip("/")
        for allowed in allowed_origins:
            allowed_normalized = allowed.rstrip("/") if allowed else ""
            if origin_normalized == allowed_normalized:
                return True
    
    # Check referer as fallback
    if referer:
        try:
            from urllib.parse import urlparse
            referer_parsed = urlparse(referer)
            referer_origin = f"{referer_parsed.scheme}://{referer_parsed.netloc}"
            for allowed in allowed_origins:
                if referer_origin == allowed:
                    return True
        except Exception:
            pass
    
    return False


def log_api_access(
    request: Request,
    session_id: Optional[str] = None,
    status_code: int = 200,
    error: Optional[str] = None
):
    """Log detailed API access information"""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    
    user_agent = request.headers.get("User-Agent", "unknown")
    origin = request.headers.get("Origin", "none")
    referer = request.headers.get("Referer", "none")
    
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": request.method,
        "path": request.url.path,
        "query": str(request.url.query) if request.url.query else None,
        "session_id": session_id[:16] + "..." if session_id else None,
        "client_ip": client_ip,
        "user_agent": user_agent,
        "origin": origin,
        "referer": referer,
        "status_code": status_code,
        "error": error
    }
    
    if error or status_code >= 400:
        api_access_logger.warning(f"API Access: {json.dumps(log_data)}")
    else:
        api_access_logger.info(f"API Access: {json.dumps(log_data)}")


def set_auth_cookie(response: Response, session_id: str, request: Request) -> None:
    """Set session cookie with proper domain for cross-subdomain sharing
    
    Args:
        response: FastAPI Response object
        session_id: Session ID to store in cookie
        request: FastAPI Request object (used to extract domain)
    """
    from app.core.config import settings
    
    # Extract host from request
    host = request.headers.get("host", settings.DOMAIN)
    if ":" in host:
        host = host.split(":")[0]
    
    # Determine cookie domain for cross-subdomain sharing
    # For multi-level domains (e.g., api-dev.dunkbox.net), use parent domain (.dunkbox.net)
    # For localhost/single-part domains, use None (browser default)
    domain_parts = host.split(".")
    if len(domain_parts) >= 2:
        # Use parent domain with leading dot (e.g., ".dunkbox.net")
        # This allows cookie to be shared across all subdomains
        cookie_domain = "." + ".".join(domain_parts[-2:])
    else:
        # localhost or single-part domain - no domain parameter needed
        cookie_domain = None
    
    # Set cookie with secure settings
    response.set_cookie(
        key="session_id",
        value=session_id,
        domain=cookie_domain,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=60 * 60 * 24 * 7  # 7 days
    )