"""Middleware configuration for FastAPI application"""
import json
import logging
import secrets
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import (
    get_client_identifier, check_rate_limit,
    validate_origin_referer, log_api_access, get_client_ip
)
from app.db.redis import get_csrf_token, set_csrf_token

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("security")


def get_allowed_origins():
    """Get list of allowed CORS origins"""
    allowed_origins = [settings.FRONTEND_URL]
    if settings.ENVIRONMENT in ("development", "test"):
        allowed_origins.extend([
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000"
        ])
    return allowed_origins


def setup_cors_middleware(app):
    """Setup CORS middleware for FastAPI app"""
    allowed_origins = get_allowed_origins()
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def security_middleware(request: Request, call_next):
    """Middleware for security checks and API access logging"""
    allowed_origins = get_allowed_origins()
    session_id = None
    status_code = 500
    error = None
    
    try:
        path = request.url.path
        
        # Skip middleware for WebSocket connections
        is_websocket = path.startswith("/ws")
        if is_websocket:
            return await call_next(request)
        
        is_callback = (
            "/api/auth/google/login/callback" in path or
            "/api/auth/youtube/callback" in path or
            "/api/auth/tiktok/callback" in path or
            "/api/auth/instagram/callback" in path
        )
        
        # OAuth completion endpoints are called from callback pages served by the API domain
        # They should be excluded from origin/referer validation
        is_oauth_completion = (
            path == "/api/auth/instagram/complete" or
            path == "/api/auth/tiktok/complete" or
            path == "/api/auth/youtube/complete" or
            path == "/api/auth/google/complete"
        )
        
        is_public_endpoint = (
            path == "/api/auth/csrf" or
            path == "/api/auth/register" or
            path == "/api/auth/login" or
            path == "/api/auth/logout" or
            path == "/api/auth/me" or
            path == "/api/auth/google/login" or
            path == "/api/subscription/webhook" or
            path == "/api/stripe/webhook" or
            path == "/api/email/webhook" or
            path == "/metrics" or
            path == "/health"
        )
        
        is_video_file_endpoint = path.startswith("/api/videos/") and path.endswith("/file")
        
        session_id = request.cookies.get("session_id")
        
        # Log request details for upload endpoints to help diagnose failures
        if request.method in ["POST", "PUT", "PATCH"] and path.startswith("/api/upload"):
            client_ip = get_client_ip(request)
            content_type = request.headers.get("Content-Type", "unknown")
            origin = request.headers.get("Origin", "none")
            referer = request.headers.get("Referer", "none")
            
            logger.info(
                f"Upload request: {request.method} {path}, "
                f"client_ip={client_ip}, content_type={content_type}, "
                f"origin={origin}, referer={referer}, "
                f"session_id={session_id[:16] + '...' if session_id else 'none'}"
            )
        
        # Rate limiting
        if not is_callback:
            identifier = get_client_identifier(request, session_id)
            is_state_changing = request.method in ["POST", "PATCH", "DELETE", "PUT"]
            if not check_rate_limit(identifier, strict=is_state_changing):
                error = "Rate limit exceeded"
                security_logger.warning(f"Rate limit exceeded - Identifier: {identifier}, Path: {path}")
                response = Response(
                    content='{"error": "Rate limit exceeded. Please try again later."}',
                    status_code=429,
                    media_type="application/json"
                )
                origin = request.headers.get("Origin")
                if origin and origin in allowed_origins:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                log_api_access(request, session_id, 429, error)
                return response
            
            # Origin/Referer validation
            if not is_public_endpoint and not is_video_file_endpoint and not is_oauth_completion and request.method != "OPTIONS" and (request.method != "GET" or settings.ENVIRONMENT == "production"):
                if not validate_origin_referer(request):
                    error = "Invalid origin or referer"
                    security_logger.warning(f"Origin/Referer validation failed - Path: {path}")
                    response = Response(
                        content='{"error": "Invalid origin or referer"}',
                        status_code=403,
                        media_type="application/json"
                    )
                    origin = request.headers.get("Origin")
                    if origin:
                        if origin in allowed_origins or "*" in allowed_origins:
                            response.headers["Access-Control-Allow-Origin"] = origin if "*" not in allowed_origins else "*"
                            response.headers["Access-Control-Allow-Credentials"] = "true" if "*" not in allowed_origins else "false"
                    log_api_access(request, session_id, 403, error)
                    return response
        
        # Process request
        response = await call_next(request)
        status_code = response.status_code
        
        # Extract error from response body for 400+ status codes
        if status_code >= 400 and error is None:
            try:
                # Read response body to extract error details
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                
                # Parse JSON response to extract error message
                if body:
                    try:
                        body_json = json.loads(body.decode('utf-8'))
                        if isinstance(body_json, dict):
                            error = body_json.get("detail") or body_json.get("error") or body_json.get("message")
                            if isinstance(error, list):
                                # Handle Pydantic validation errors (list of errors)
                                error = "; ".join([str(e.get("msg", e)) for e in error])
                            elif not error:
                                # Fallback: use the whole JSON as string if no error field
                                error = json.dumps(body_json)[:200]
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        error = body.decode('utf-8', errors='ignore')[:200]  # Truncate long errors
                
                # Recreate response with body (since we consumed it)
                from fastapi.responses import Response as FastAPIResponse
                response = FastAPIResponse(
                    content=body,
                    status_code=status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type
                )
            except Exception as e:
                logger.warning(f"Failed to extract error from response: {e}")
        
        # Log error details for 400+ errors
        # User-blocking errors (400 Bad Request) should be logged as errors
        if status_code >= 400:
            client_ip = get_client_ip(request)
            if status_code == 400:
                logger.error(
                    f"Request failed {status_code} on {request.method} {path}: "
                    f"client_ip={client_ip}, error={error or 'unknown'}"
                )
            else:
                logger.warning(
                    f"Request failed {status_code} on {request.method} {path}: "
                    f"client_ip={client_ip}, error={error or 'unknown'}"
                )
        
        # FIX: Remove 'request.method == "GET"' so token is sent on POST/PUT too
        if session_id and not is_callback and status_code < 400:
            csrf_token = get_csrf_token(session_id)
            if not csrf_token:
                csrf_token = secrets.token_urlsafe(32)
                set_csrf_token(session_id, csrf_token)
            
            if csrf_token:
                # 1. Keep the header for legacy support
                response.headers["X-CSRF-Token"] = csrf_token
                
                # 2. ADD THIS: Set a non-HttpOnly cookie so React can actually find it
                # Reuse your existing logic to get the correct domain
                host = request.headers.get("host", settings.DOMAIN).split(":")[0]
                domain_parts = host.split(".")
                cookie_domain = "." + ".".join(domain_parts[-2:]) if len(domain_parts) >= 2 else None

                response.set_cookie(
                    key="csrf_token_client",
                    value=csrf_token,
                    domain=cookie_domain,
                    httponly=False,  # CRITICAL: JS must read this
                    secure=True,     # Since you are on HTTPS
                    samesite="lax",
                    path="/"
                )
        
        return response
        
    except Exception as e:
        error = str(e)
        security_logger.error(f"Security middleware error: {error}", exc_info=True)
        raise
    finally:
        log_api_access(request, session_id, status_code, error)


async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )
