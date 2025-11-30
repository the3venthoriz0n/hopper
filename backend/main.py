from urllib.parse import urlencode, unquote
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Cookie, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pathlib import Path
import uvicorn
import os
import asyncio
import json
import secrets
import random
import re
import httpx
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from collections import defaultdict
from functools import wraps

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Database and auth imports
from models import init_db, get_db, User, Video, Setting, OAuthToken
from auth import hash_password, verify_password, create_user, authenticate_user, get_user_by_id
import redis_client
from pydantic import BaseModel, EmailStr
import db_helpers
from encryption import encrypt, decrypt

app = FastAPI()

# ============================================================================
# DATABASE AND REDIS INITIALIZATION
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize database and connections on startup"""
    logger.info("Initializing database...")
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    logger.info("Testing Redis connection...")
    try:
        redis_client.redis_client.ping()
        logger.info("Redis connection successful")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    created_at: str

# Get domain from environment or default to localhost for development
DOMAIN = os.getenv("DOMAIN", "localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Create specific loggers for different components
upload_logger = logging.getLogger("upload")
tiktok_logger = logging.getLogger("tiktok")
youtube_logger = logging.getLogger("youtube")
instagram_logger = logging.getLogger("instagram")
security_logger = logging.getLogger("security")  # For security-related logs
api_access_logger = logging.getLogger("api_access")  # For detailed API access logs

# OAuth Credentials from environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
# Instagram uses Facebook Login for Business
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")

# TikTok OAuth Configuration
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_SCOPES = ["user.info.basic", "video.upload", "video.publish"]

# TikTok Content Posting API
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
TIKTOK_CREATOR_INFO_URL = f"{TIKTOK_API_BASE}/post/publish/creator_info/query/"
TIKTOK_INIT_UPLOAD_URL = f"{TIKTOK_API_BASE}/post/publish/video/init/"

# TikTok Rate Limiting: 6 requests per minute per user
# Simple rate limiter: track last request time per session
tiktok_rate_limiter = {}  # {session_id: [timestamps]}
TIKTOK_RATE_LIMIT_REQUESTS = 6
TIKTOK_RATE_LIMIT_WINDOW = 60  # seconds

# Instagram OAuth Configuration (Instagram Business Login)
# See: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
# Instagram OAuth URLs - Using Facebook Login for Business (supports resumable uploads)
INSTAGRAM_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
INSTAGRAM_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
INSTAGRAM_GRAPH_API_BASE = "https://graph.facebook.com"
# Facebook Login scopes for Instagram API
INSTAGRAM_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_read_engagement",
    "pages_show_list"
]

# Destination upload functions registry
# This allows easy addition of new destinations in the future
DESTINATION_UPLOADERS = {
    "youtube": None,  # Will be set below
    "tiktok": None,   # Will be set below
    "instagram": None,  # Will be set below
}


def get_google_client_config():
    """Build Google OAuth client config from environment variables"""
    if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID]):
        return None
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "project_id": GOOGLE_PROJECT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": []  # Will be set dynamically
        }
    }

# CORS Configuration
# Build allowed origins list based on environment variables
allowed_origins = []

# Log environment configuration for debugging
logger.info(f"=== Environment Configuration ===")
logger.info(f"ENVIRONMENT: {ENVIRONMENT}")
logger.info(f"FRONTEND_URL: {FRONTEND_URL or '(not set)'}")
logger.info(f"BACKEND_URL: {BACKEND_URL or '(not set)'}")
logger.info(f"DOMAIN: {DOMAIN}")

# Determine if this is production based on environment
is_production = ENVIRONMENT == "production"

# Always include the configured frontend URL if set
if FRONTEND_URL:
    allowed_origins.append(FRONTEND_URL)
    logger.info(f"CORS: Added FRONTEND_URL to allowed origins: {FRONTEND_URL}")
else:
    logger.warning("CORS: FRONTEND_URL not set! CORS may fail.")

# For non-production, be more permissive
if not is_production:
    # Add common dev URLs (both HTTP and HTTPS)
    dev_urls = [
        "http://localhost:3000", 
        "http://localhost:8000", 
        "http://127.0.0.1:3000",
        "https://localhost:3000",
        "https://localhost:8000"
    ]
    for url in dev_urls:
        if url not in allowed_origins:
            allowed_origins.append(url)
    
    # Also check if FRONTEND_URL contains a dev domain pattern and add HTTPS variant
    if FRONTEND_URL and "dev" in FRONTEND_URL.lower():
        # If FRONTEND_URL is HTTP, also allow HTTPS variant
        if FRONTEND_URL.startswith("http://"):
            https_variant = FRONTEND_URL.replace("http://", "https://")
            if https_variant not in allowed_origins:
                allowed_origins.append(https_variant)
                logger.info(f"CORS: Added HTTPS variant to allowed origins: {https_variant}")
        # If FRONTEND_URL is HTTPS, also allow HTTP variant
        elif FRONTEND_URL.startswith("https://"):
            http_variant = FRONTEND_URL.replace("https://", "http://")
            if http_variant not in allowed_origins:
                allowed_origins.append(http_variant)
                logger.info(f"CORS: Added HTTP variant to allowed origins: {http_variant}")
    
    # If no origins configured at all, allow everything as fallback for dev
    if not allowed_origins:
        logger.warning("CORS: No origins configured, allowing all origins for development")
        allowed_origins = ["*"]

# Log final configuration
logger.info(f"CORS Configuration - Environment: {ENVIRONMENT}, Is Production: {is_production}")
logger.info(f"CORS Allowed Origins: {allowed_origins}")

# If we have no origins in production, this is a critical error
if is_production and not allowed_origins:
    raise RuntimeError("FATAL: FRONTEND_URL must be set in production environment for CORS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-CSRF-Token"],  # Expose CSRF token header to frontend
)

# Global exception handler to ensure all error responses include CORS headers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all exceptions and ensure CORS headers are present"""
    origin = request.headers.get("Origin")
    
    # Determine if origin is allowed (handle wildcard case)
    origin_allowed = False
    if origin:
        if "*" in allowed_origins:
            # Wildcard allows all origins, but can't use with credentials
            # In dev mode, we'll allow it but without credentials header
            origin_allowed = True
        elif origin in allowed_origins:
            origin_allowed = True
    
    # If it's an HTTPException, use its status code and detail
    if isinstance(exc, HTTPException):
        response = Response(
            content=json.dumps({"detail": exc.detail}),
            status_code=exc.status_code,
            media_type="application/json"
        )
    else:
        # For other exceptions, return 500
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        response = Response(
            content=json.dumps({"detail": "Internal server error"}),
            status_code=500,
            media_type="application/json"
        )
    
    # Add CORS headers if origin is allowed
    if origin_allowed:
        if "*" in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = "*"
            # Can't use credentials with wildcard
        else:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
    
    return response

# ============================================================================
# SECURITY IMPLEMENTATION
# ============================================================================

# Rate Limiter: {identifier: [timestamps]} - in-memory is fine
# identifier can be session_id or IP address
rate_limiter = defaultdict(list)
# Rate limiting: more permissive for production (real users), reasonable for development
if ENVIRONMENT == "development":
    RATE_LIMIT_REQUESTS = 1000  # requests per window
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_STRICT_REQUESTS = 200  # stricter limit for state-changing operations
    RATE_LIMIT_STRICT_WINDOW = 60  # seconds
else:
    RATE_LIMIT_REQUESTS = 5000  # requests per window (increased for production)
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_STRICT_REQUESTS = 1000  # stricter limit for state-changing operations (increased for production)
    RATE_LIMIT_STRICT_WINDOW = 60  # seconds

# Allowed origins for Origin/Referer validation
ALLOWED_ORIGINS = [FRONTEND_URL] if ENVIRONMENT == "production" else [FRONTEND_URL, "http://localhost:3000", "http://localhost:8000"]

def get_client_identifier(request: Request, session_id: Optional[str] = None) -> str:
    """Get client identifier for rate limiting (prefer session_id, fallback to IP)"""
    if session_id:
        return f"session:{session_id}"
    # Get IP from X-Forwarded-For (if behind proxy) or direct connection
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"

def check_rate_limit(identifier: str, strict: bool = False) -> bool:
    """Check if request is within rate limit. Returns True if allowed, False if rate limited."""
    now = datetime.now(timezone.utc)
    window = RATE_LIMIT_STRICT_WINDOW if strict else RATE_LIMIT_WINDOW
    max_requests = RATE_LIMIT_STRICT_REQUESTS if strict else RATE_LIMIT_REQUESTS
    
    # Clean old entries
    cutoff = now - timedelta(seconds=window)
    rate_limiter[identifier] = [
        ts for ts in rate_limiter[identifier] 
        if ts > cutoff
    ]
    
    # Check limit
    if len(rate_limiter[identifier]) >= max_requests:
        return False
    
    # Add current request
    rate_limiter[identifier].append(now)
    return True

def validate_origin_referer(request: Request) -> bool:
    """Validate Origin or Referer header matches allowed origins"""
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    
    # In development, allow requests without Origin/Referer (e.g., direct API calls)
    if ENVIRONMENT != "production":
        if not origin and not referer:
            return True
    
    # Check Origin first (more reliable for CORS)
    if origin:
        # Remove protocol and normalize
        origin_normalized = origin.rstrip("/")
        for allowed in ALLOWED_ORIGINS:
            allowed_normalized = allowed.rstrip("/")
            if origin_normalized == allowed_normalized:
                return True
    
    # Fallback to Referer
    if referer:
        try:
            from urllib.parse import urlparse
            referer_parsed = urlparse(referer)
            referer_origin = f"{referer_parsed.scheme}://{referer_parsed.netloc}"
            for allowed in ALLOWED_ORIGINS:
                if referer_origin == allowed:
                    return True
        except Exception:
            pass
    
    return False

# ============================================================================
# FastAPI Dependencies for Security (REDIS-BASED)
# ============================================================================

def require_auth(request: Request) -> int:
    """Dependency: Require authentication, return user_id"""
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        raise HTTPException(401, "Not authenticated. Please log in.")
    
    user_id = redis_client.get_session(session_id)
    if not user_id:
        raise HTTPException(401, "Session expired. Please log in again.")
    
    return user_id

async def require_csrf_new(
    request: Request,
    user_id: int = Depends(require_auth),
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token")
) -> int:
    """Dependency: Require auth + valid CSRF token, return user_id"""
    session_id = request.cookies.get("session_id")
    
    # Get CSRF token from header or form data
    csrf_token = x_csrf_token
    if not csrf_token:
        try:
            form_data = await request.form()
            csrf_token = form_data.get("csrf_token")
        except Exception:
            pass
    
    # Get expected CSRF token from Redis
    expected_csrf = redis_client.get_csrf_token(session_id)
    if not expected_csrf or csrf_token != expected_csrf:
        security_logger.warning(
            f"CSRF validation failed - User: {user_id}, "
            f"IP: {request.client.host if request.client else 'unknown'}, "
            f"Path: {request.url.path}"
        )
        raise HTTPException(403, "Invalid or missing CSRF token")
    
    return user_id

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

# Middleware for API access logging and security checks
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Middleware for security checks and API access logging"""
    start_time = datetime.now(timezone.utc)
    session_id = None
    status_code = 500
    error = None
    
    try:
        # Skip security checks for OAuth callbacks and static pages
        path = request.url.path
        is_callback = (
            "/api/auth/youtube/callback" in path or
            "/api/auth/tiktok/callback" in path or
            "/api/auth/instagram/callback" in path or
            "/api/auth/instagram/complete" in path or
            path in ["/terms", "/privacy"]
        )
        
        # Get session ID if available
        session_id = request.cookies.get("session_id")
        
        # Rate limiting (apply to all endpoints except callbacks)
        if not is_callback:
            identifier = get_client_identifier(request, session_id)
            # Stricter rate limiting for state-changing methods
            is_state_changing = request.method in ["POST", "PATCH", "DELETE", "PUT"]
            if not check_rate_limit(identifier, strict=is_state_changing):
                error = "Rate limit exceeded"
                security_logger.warning(
                    f"Rate limit exceeded - Identifier: {identifier}, "
                    f"Path: {path}, Method: {request.method}"
                )
                response = Response(
                    content=json.dumps({"error": "Rate limit exceeded. Please try again later."}),
                    status_code=429,
                    media_type="application/json"
                )
                # Add CORS headers to error response
                origin = request.headers.get("Origin")
                if origin and origin in allowed_origins:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                log_api_access(request, session_id, 429, error)
                return response
            
            # Origin/Referer validation (skip for GET requests in dev)
            if request.method != "GET" or ENVIRONMENT == "production":
                if not validate_origin_referer(request):
                    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    if not client_ip:
                        client_ip = request.client.host if request.client else "unknown"
                    error = "Invalid origin or referer"
                    security_logger.warning(
                        f"Origin/Referer validation failed - "
                        f"Origin: {request.headers.get('Origin', 'none')}, "
                        f"Referer: {request.headers.get('Referer', 'none')}, "
                        f"Path: {path}, IP: {client_ip}"
                    )
                    response = Response(
                        content=json.dumps({"error": "Invalid origin or referer"}),
                        status_code=403,
                        media_type="application/json"
                    )
                    # Add CORS headers to error response
                    origin = request.headers.get("Origin")
                    if origin and origin in allowed_origins:
                        response.headers["Access-Control-Allow-Origin"] = origin
                        response.headers["Access-Control-Allow-Credentials"] = "true"
                    log_api_access(request, session_id, 403, error)
                    return response
        
        # Process request
        response = await call_next(request)
        status_code = response.status_code
        
        # Set CSRF token in response header for GET requests (so frontend can read it)
        if request.method == "GET" and session_id and not is_callback:
            csrf_token = redis_client.get_csrf_token(session_id)
            # Generate CSRF token if it doesn't exist
            if not csrf_token:
                csrf_token = secrets.token_urlsafe(32)
                redis_client.set_csrf_token(session_id, csrf_token)
            # Only set header if token exists (should always exist after generation above)
            if csrf_token:
                response.headers["X-CSRF-Token"] = csrf_token
        
        return response
        
    except HTTPException as e:
        status_code = e.status_code
        error = e.detail
        raise
    except Exception as e:
        error = str(e)
        security_logger.error(f"Security middleware error: {error}", exc_info=True)
        raise
    finally:
        # Log API access
        log_api_access(request, session_id, status_code, error)

# ============================================================================
# END SECURITY IMPLEMENTATION
# ============================================================================

# Storage - only need UPLOAD_DIR now (no more SESSIONS_DIR)
UPLOAD_DIR = Path("uploads")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Directory already exists or mounted

# Helper functions for template replacement
def replace_template_placeholders(template: str, filename: str, wordbank: list) -> str:
    """Replace template placeholders with actual values"""
    # Replace {filename}
    result = template.replace('{filename}', filename)
    
    # Replace each {random} with a random word from wordbank
    if wordbank:
        # Find all {random} occurrences and replace each independently
        while '{random}' in result:
            random_word = random.choice(wordbank)
            result = result.replace('{random}', random_word, 1)  # Replace only first occurrence
    else:
        # If wordbank is empty, just remove {random} placeholders
        result = result.replace('{random}', '')
    
    return result


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/auth/register")
def register(request_data: RegisterRequest, response: Response):
    """Register a new user"""
    try:
        # Validate password strength (minimum 8 characters)
        if len(request_data.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters long")
        
        # Create user
        user = create_user(request_data.email, request_data.password)
        
        # Create session
        session_id = secrets.token_urlsafe(32)
        redis_client.set_session(session_id, user.id)
        
        # Set session cookie
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,
            samesite="lax",
            secure=ENVIRONMENT == "production"
        )
        
        logger.info(f"User registered: {user.email} (ID: {user.id})")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat()
            }
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(500, "Registration failed")


@app.post("/api/auth/login")
def login(request_data: LoginRequest, response: Response):
    """Login user"""
    try:
        # Authenticate user
        user = authenticate_user(request_data.email, request_data.password)
        if not user:
            raise HTTPException(401, "Invalid email or password")
        
        # Create session
        session_id = secrets.token_urlsafe(32)
        redis_client.set_session(session_id, user.id)
        
        # Set session cookie
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,
            samesite="lax",
            secure=ENVIRONMENT == "production"
        )
        
        logger.info(f"User logged in: {user.email} (ID: {user.id})")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(500, "Login failed")


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """Logout user"""
    session_id = request.cookies.get("session_id")
    if session_id:
        redis_client.delete_session(session_id)
        response.delete_cookie("session_id")
        logger.info(f"User logged out (session: {session_id[:16]}...)")
    return {"message": "Logged out successfully"}


@app.get("/api/auth/me")
def get_current_user(request: Request):
    """Get current logged-in user"""
    try:
        session_id = request.cookies.get("session_id")
        if not session_id:
            return {"user": None}
        
        user_id = redis_client.get_session(session_id)
        if not user_id:
            return {"user": None}
        
        user = get_user_by_id(user_id)
        if not user:
            return {"user": None}
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error in /api/auth/me: {e}", exc_info=True)
        # Return None user instead of raising error to prevent 500
        return {"user": None}


@app.get("/api/auth/csrf")
def get_csrf(request: Request, response: Response):
    """Get or generate CSRF token for the current session"""
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        # Create new session for unauthenticated users
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,
            samesite="lax",
            secure=ENVIRONMENT == "production"
        )
    
    # Generate CSRF token and store in Redis
    csrf_token = secrets.token_urlsafe(32)
    redis_client.set_csrf_token(session_id, csrf_token)
    
    # Return token in both response body and header
    response.headers["X-CSRF-Token"] = csrf_token
    return {"csrf_token": csrf_token}


# ============================================================================
# OAUTH ENDPOINTS (YouTube, TikTok, Instagram)
# ============================================================================

@app.get("/api/auth/youtube")
def auth_youtube(request: Request, user_id: int = Depends(require_auth)):
    """Start YouTube OAuth - requires authentication"""
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
    # Build redirect URI dynamically based on request
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
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
    url, state = flow.authorization_url(access_type='offline', state=str(user_id))
    return {"url": url}

@app.get("/api/auth/youtube/callback")
def auth_callback(code: str, state: str, request: Request, response: Response):
    """OAuth callback - stores credentials in database"""
    # Get user_id from state parameter
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid state parameter")
    
    # Verify user exists
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    
    # Build redirect URI dynamically
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
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
    
    # Create complete Credentials object
    creds = Credentials(
        token=flow_creds.token,
        refresh_token=flow_creds.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=flow_creds.scopes
    )
    
    # Save OAuth token to database (encrypted)
    token_data = db_helpers.credentials_to_oauth_token_data(creds, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
    db_helpers.save_oauth_token(
        user_id=user_id,
        platform="youtube",
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
        extra_data=token_data["extra_data"]
    )
    
    # Enable YouTube destination by default
    db_helpers.set_user_setting(user_id, "destinations", "youtube_enabled", True)
    
    youtube_logger.info(f"YouTube OAuth completed for user {user_id}")
    
    # Redirect to frontend
    if FRONTEND_URL:
        frontend_url = f"{FRONTEND_URL}?connected=youtube"
    else:
        host = request.headers.get("host", "localhost:8000")
        protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        frontend_url = f"{protocol}://{host.replace(':8000', ':3000')}?connected=youtube"
    
    return RedirectResponse(frontend_url)

@app.get("/api/destinations")
def get_destinations(user_id: int = Depends(require_auth)):
    """Get destination status for current user"""
    # Get OAuth tokens
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube")
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok")
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram")
    
    # Get enabled status from settings
    settings = db_helpers.get_user_settings(user_id, "destinations")
    
    # Get scheduled video count
    videos = db_helpers.get_user_videos(user_id)
    scheduled_count = len([v for v in videos if v.status == 'scheduled'])
    
    return {
        "youtube": {
            "connected": youtube_token is not None,
            "enabled": settings.get("youtube_enabled", False)
        },
        "tiktok": {
            "connected": tiktok_token is not None,
            "enabled": settings.get("tiktok_enabled", False)
        },
        "instagram": {
            "connected": instagram_token is not None,
            "enabled": settings.get("instagram_enabled", False)
        },
        "scheduled_videos": scheduled_count
    }

@app.get("/api/auth/youtube/account")
def get_youtube_account(user_id: int = Depends(require_auth)):
    """Get YouTube account information (channel name/email)"""
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube")
    
    if not youtube_token:
        return {"account": None}
    
    try:
        # Convert to Credentials object (automatically decrypts)
        youtube_creds = db_helpers.oauth_token_to_credentials(youtube_token)
        if not youtube_creds:
            return {"account": None}
        
        # Refresh token if needed
        if youtube_creds.expired and youtube_creds.refresh_token:
            try:
                youtube_creds.refresh(GoogleRequest())
                # Save refreshed token back to database
                token_data = db_helpers.credentials_to_oauth_token_data(
                    youtube_creds, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
                )
                db_helpers.save_oauth_token(
                    user_id=user_id,
                    platform="youtube",
                    access_token=token_data["access_token"],
                    refresh_token=token_data["refresh_token"],
                    expires_at=token_data["expires_at"],
                    extra_data=token_data["extra_data"]
                )
            except Exception as refresh_error:
                youtube_logger.warning(f"Token refresh failed for user {user_id}: {str(refresh_error)}")
        
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get channel info
        channels_response = youtube.channels().list(
            part='snippet',
            mine=True
        ).execute()
        
        account_info = None
        if channels_response.get('items') and len(channels_response['items']) > 0:
            channel = channels_response['items'][0]
            account_info = {
                "channel_name": channel['snippet']['title'],
                "channel_id": channel['id'],
                "thumbnail": channel['snippet'].get('thumbnails', {}).get('default', {}).get('url')
            }
        
        # Get email from Google OAuth2 userinfo
        try:
            if youtube_creds.expired and youtube_creds.refresh_token:
                youtube_creds.refresh(GoogleRequest())
            
            userinfo_response = httpx.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {youtube_creds.token}'},
                timeout=10.0
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
        
        return {"account": account_info}
    except Exception as e:
        youtube_logger.error(f"Error getting YouTube account info for user {user_id}: {str(e)}", exc_info=True)
        return {"account": None, "error": str(e)}

@app.post("/api/global/wordbank")
def add_wordbank_word(word: str, user_id: int = Depends(require_csrf_new)):
    """Add a word to the global wordbank"""
    # Strip whitespace and capitalize
    word = word.strip().capitalize()
    if not word:
        raise HTTPException(400, "Word cannot be empty")
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global")
    wordbank = settings.get("wordbank", [])
    
    if word not in wordbank:
        wordbank.append(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank)
    
    # Return updated settings
    return db_helpers.get_user_settings(user_id, "global")
    
    return {"wordbank": session["global_settings"]["wordbank"]}

@app.delete("/api/global/wordbank/{word}")
def remove_wordbank_word(word: str, user_id: int = Depends(require_csrf_new)):
    """Remove a word from the global wordbank"""
    # Decode URL-encoded word
    word = unquote(word)
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global")
    wordbank = settings.get("wordbank", [])
    
    if word in wordbank:
        wordbank.remove(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank)
    
    return {"wordbank": wordbank}

@app.delete("/api/global/wordbank")
def clear_wordbank(user_id: int = Depends(require_csrf_new)):
    """Clear all words from the global wordbank"""
    db_helpers.set_user_setting(user_id, "global", "wordbank", [])
    return {"wordbank": []}

@app.post("/api/destinations/youtube/toggle")
def toggle_youtube(enabled: bool, user_id: int = Depends(require_csrf_new)):
    """Toggle YouTube destination on/off"""
    db_helpers.set_user_setting(user_id, "destinations", "youtube_enabled", enabled)
    
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube")
    return {
        "youtube": {
            "connected": youtube_token is not None,
            "enabled": enabled
        }
    }

@app.post("/api/destinations/tiktok/toggle")
def toggle_tiktok(enabled: bool, user_id: int = Depends(require_csrf_new)):
    """Toggle TikTok destination on/off"""
    db_helpers.set_user_setting(user_id, "destinations", "tiktok_enabled", enabled)
    
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok")
    return {
        "tiktok": {
            "connected": tiktok_token is not None,
            "enabled": enabled
        }
    }

@app.post("/api/destinations/instagram/toggle")
def toggle_instagram(enabled: bool, user_id: int = Depends(require_csrf_new)):
    """Toggle Instagram destination on/off"""
    db_helpers.set_user_setting(user_id, "destinations", "instagram_enabled", enabled)
    
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram")
    return {
        "instagram": {
            "connected": instagram_token is not None,
            "enabled": enabled
        }
    }

@app.post("/api/auth/youtube/disconnect")
def disconnect_youtube(user_id: int = Depends(require_csrf_new)):
    """Disconnect YouTube account"""
    db_helpers.delete_oauth_token(user_id, "youtube")
    db_helpers.set_user_setting(user_id, "destinations", "youtube_enabled", False)
    return {"message": "Disconnected"}

@app.get("/api/auth/tiktok")
def auth_tiktok(request: Request, user_id: int = Depends(require_auth)):
    """Initiate TikTok OAuth flow - requires authentication"""
    
    # Validate configuration
    if not TIKTOK_CLIENT_KEY:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing TIKTOK_CLIENT_KEY."
        )
    
    # Build redirect URI (must match TikTok Developer Portal exactly)
    redirect_uri = f"{BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
    
    # Build scope string (comma-separated, no spaces)
    scope_string = ",".join(TIKTOK_SCOPES)
    
    # Build authorization URL with proper encoding
    params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": scope_string,
        "redirect_uri": redirect_uri,
        "state": str(user_id),  # Pass user_id in state
    }
    
    query_string = urlencode(params, doseq=False)
    auth_url = f"{TIKTOK_AUTH_URL}?{query_string}"
    
    # Debug logging
    tiktok_logger.info(f"Initiating auth flow for user {user_id}")
    tiktok_logger.debug(f"Client Key: {TIKTOK_CLIENT_KEY[:4]}...{TIKTOK_CLIENT_KEY[-4:]}, "
                       f"Redirect URI: {redirect_uri}, Scope: {scope_string}")
    
    return {"url": auth_url}


@app.get("/api/auth/tiktok/callback")
async def auth_tiktok_callback(
    request: Request,
    response: Response,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None
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
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate required parameters
    if not code or not state:
        tiktok_logger.error("Missing code or state")
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate configuration
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing credentials."
        )
    
    # Validate state (get user_id)
    try:
        user_id = int(state)
    except (ValueError, TypeError):
        tiktok_logger.error("Invalid state parameter")
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Verify user exists
    user = get_user_by_id(user_id)
    if not user:
        tiktok_logger.error(f"User {user_id} not found")
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    try:
        # Exchange authorization code for access token
        redirect_uri = f"{BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
        decoded_code = unquote(code) if code else None
        
        token_data = {
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
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
                return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_token_failed")
            
            token_json = token_response.json()
            
            if "access_token" not in token_json:
                tiktok_logger.error("No access_token in response")
                return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_token_failed")
            
            tiktok_logger.info(f"Token exchange successful for user {user_id} - Open ID: {token_json.get('open_id', 'N/A')}")
            
            # Calculate expiry time
            expires_in = token_json.get("expires_in")
            expires_at = None
            if expires_in:
                from datetime import datetime, timedelta, timezone
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            
            # Store in database (encrypted)
            db_helpers.save_oauth_token(
                user_id=user_id,
                platform="tiktok",
                access_token=token_json["access_token"],
                refresh_token=token_json.get("refresh_token"),
                expires_at=expires_at,
                extra_data={
                    "open_id": token_json.get("open_id"),
                    "scope": token_json.get("scope"),
                    "token_type": token_json.get("token_type"),
                    "refresh_expires_in": token_json.get("refresh_expires_in")
                }
            )
            
            # Enable TikTok destination
            db_helpers.set_user_setting(user_id, "destinations", "tiktok_enabled", True)
            
            tiktok_logger.info(f"TikTok OAuth completed for user {user_id}")
            
            # Redirect to frontend
            return RedirectResponse(f"{FRONTEND_URL}?connected=tiktok")
            
    except Exception as e:
        tiktok_logger.error(f"Callback exception: {e}", exc_info=True)
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")


@app.get("/api/auth/tiktok/account")
def get_tiktok_account(user_id: int = Depends(require_auth)):
    """Get TikTok account information (display name/username)"""
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok")
    
    if not tiktok_token:
        return {"account": None}
    
    try:
        # Get access token (decrypted)
        access_token = decrypt(tiktok_token.access_token)
        if not access_token:
            return {"account": None}
        
        # Get creator info from TikTok API
        open_id = tiktok_token.extra_data.get("open_id") if tiktok_token.extra_data else None
        
        if not open_id:
            tiktok_logger.warning(f"No open_id found for user {user_id}")
            return {"account": None}
        
        # Call TikTok creator info API
        try:
            creator_info_response = httpx.get(
                TIKTOK_CREATOR_INFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )
            
            if creator_info_response.status_code != 200:
                tiktok_logger.warning(f"TikTok creator info request failed: {creator_info_response.status_code}")
                return {"account": None}
            
            creator_data = creator_info_response.json()
            creator_info = creator_data.get("data", {})
            
            # Extract account information
            account_info = {}
            
            if "creator_nickname" in creator_info:
                account_info["display_name"] = creator_info["creator_nickname"]
            elif "display_name" in creator_info:
                account_info["display_name"] = creator_info["display_name"]
            
            if "creator_username" in creator_info:
                account_info["username"] = creator_info["creator_username"]
            elif "username" in creator_info:
                account_info["username"] = creator_info["username"]
            
            if "creator_avatar_url" in creator_info:
                account_info["avatar_url"] = creator_info["creator_avatar_url"]
            elif "avatar_url" in creator_info:
                account_info["avatar_url"] = creator_info["avatar_url"]
            
            account_info["open_id"] = open_id
            
            return {"account": account_info if account_info else None}
            
        except Exception as api_error:
            tiktok_logger.error(f"Error calling TikTok API for user {user_id}: {str(api_error)}")
            return {"account": None}
        
    except Exception as e:
        tiktok_logger.error(f"Error getting TikTok account info for user {user_id}: {str(e)}", exc_info=True)
        return {"account": None, "error": str(e)}

@app.post("/api/auth/tiktok/disconnect")
def disconnect_tiktok(user_id: int = Depends(require_csrf_new)):
    """Disconnect TikTok account"""
    db_helpers.delete_oauth_token(user_id, "tiktok")
    db_helpers.set_user_setting(user_id, "destinations", "tiktok_enabled", False)
    return {"message": "Disconnected"}

@app.get("/api/auth/instagram")
def auth_instagram(request: Request, user_id: int = Depends(require_auth)):
    """Initiate Instagram OAuth flow via Facebook Login for Business - requires authentication"""
    
    # Validate configuration
    if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Instagram OAuth not configured. Missing FACEBOOK_APP_ID or FACEBOOK_APP_SECRET."
        )
    
    # Build redirect URI
    redirect_uri = f"{BACKEND_URL.rstrip('/')}/api/auth/instagram/callback"
    
    # Build scope string (comma-separated for Facebook)
    scope_string = ",".join(INSTAGRAM_SCOPES)
    
    # Build Facebook Login for Business authorization URL
    params = {
        "client_id": FACEBOOK_APP_ID,
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
    instagram_logger.debug(f"Redirect URI: {redirect_uri}, Scope: {scope_string}")
    
    return {"url": auth_url}

@app.get("/api/auth/instagram/callback")
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
    
    # Check for errors from Facebook
    if error:
        error_msg = f"Facebook OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        instagram_logger.error(error_msg)
        return RedirectResponse(f"{FRONTEND_URL}?error=instagram_auth_failed")
    
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
                window.location.href = '{FRONTEND_URL}?error=instagram_auth_failed&reason=' + error;
            }} else if (accessToken) {{
                // Send tokens to backend to complete authentication
                fetch('{BACKEND_URL.rstrip("/")}/api/auth/instagram/complete', {{
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
                        window.location.href = '{FRONTEND_URL}?connected=instagram';
                    }} else {{
                        window.location.href = '{FRONTEND_URL}?error=instagram_auth_failed&detail=' + encodeURIComponent(data.error || 'Unknown error');
                    }}
                }})
                .catch(err => {{
                    console.error('Error completing auth:', err);
                    window.location.href = '{FRONTEND_URL}?error=instagram_auth_failed';
                }});
            }} else {{
                window.location.href = '{FRONTEND_URL}?error=instagram_auth_failed&reason=missing_tokens';
            }}
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.post("/api/auth/instagram/complete")
async def complete_instagram_auth(request: Request, response: Response):
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
        try:
            user_id = int(state)
        except (ValueError, TypeError):
            instagram_logger.error("Invalid state parameter")
            return {"success": False, "error": "Invalid state"}
        
        # Verify user exists
        user = get_user_by_id(user_id)
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
                        "client_id": FACEBOOK_APP_ID,
                        "client_secret": FACEBOOK_APP_SECRET,
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
            
            # Debug: Use /debug_token to get detailed token information
            debug_token_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/debug_token"
            debug_token_params = {
                "input_token": access_token_to_use,
                "access_token": f"{FACEBOOK_APP_ID}|{FACEBOOK_APP_SECRET}"  # App access token
            }
            instagram_logger.info("Debugging access token with /debug_token...")
            debug_token_response = await client.get(debug_token_url, params=debug_token_params)
            if debug_token_response.status_code == 200:
                debug_token_data = debug_token_response.json()
                instagram_logger.info(f"Token debug info: {json.dumps(debug_token_data, indent=2)}")
                token_info = debug_token_data.get("data", {})
                scopes = token_info.get("scopes", [])
                instagram_logger.info(f"Token scopes: {', '.join(scopes)}")
            
            # Debug: Check what permissions this token has
            debug_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/me/permissions"
            debug_params = {"access_token": access_token_to_use}
            
            instagram_logger.info("Checking token permissions...")
            debug_response = await client.get(debug_url, params=debug_params)
            if debug_response.status_code == 200:
                debug_data = debug_response.json()
                instagram_logger.info(f"Token permissions: {json.dumps(debug_data, indent=2)}")
                
                # Check if pages_show_list is granted
                permissions = debug_data.get("data", [])
                has_pages_show_list = any(p.get("permission") == "pages_show_list" and p.get("status") == "granted" for p in permissions)
                instagram_logger.info(f"Has 'pages_show_list' permission: {has_pages_show_list}")
                
                if not has_pages_show_list:
                    return {
                        "success": False,
                        "error": "Missing 'pages_show_list' permission. Please reconnect Instagram and make sure to grant all requested permissions during login."
                    }
            
            # Debug: Check which Facebook user this token belongs to
            user_id = None
            user_name = None
            me_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/me"
            me_params = {"fields": "id,name,email", "access_token": access_token_to_use}
            me_response = await client.get(me_url, params=me_params)
            if me_response.status_code == 200:
                me_data = me_response.json()
                user_id = me_data.get('id')
                user_name = me_data.get('name', 'Unknown')
                instagram_logger.info(f"Token belongs to Facebook user: {user_name} (ID: {user_id})")
                
                # Try alternative: Check if user has any pages by querying /{user_id}/accounts
                alt_pages_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{user_id}/accounts"
                alt_pages_params = {
                    "fields": "id,name,access_token,instagram_business_account",
                    "access_token": access_token_to_use
                }
                instagram_logger.info(f"Trying alternative endpoint: {alt_pages_url}")
                alt_pages_response = await client.get(alt_pages_url, params=alt_pages_params)
                if alt_pages_response.status_code == 200:
                    alt_pages_data = alt_pages_response.json()
                    instagram_logger.info(f"Alternative endpoint response: {json.dumps(alt_pages_data, indent=2)}")
            else:
                instagram_logger.warning(f"Could not fetch user info: {me_response.text}")
            
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
                # Check if there's pagination or other metadata
                instagram_logger.error(f"No Facebook Pages in 'data' array. Full response: {pages_data}")
                
                # Check if there are any permissions issues  
                if "error" in pages_data:
                    error_info = pages_data["error"]
                    return {
                        "success": False, 
                        "error": f"Facebook API Error: {error_info.get('message', 'Unknown error')} (Code: {error_info.get('code', 'N/A')})"
                    }
                
                # Additional debugging: Try to get user's pages via different method
                instagram_logger.warning("No pages found via /me/accounts. This could mean:")
                instagram_logger.warning("1. The Facebook account doesn't have any Pages")
                instagram_logger.warning("2. The account isn't an admin/manager of any Pages")
                instagram_logger.warning("3. The Pages exist but aren't accessible via this API")
                
                # Get user info for better error message
                user_info = f"Logged in as: {user_name} (ID: {user_id})" if user_name and user_id else "Could not identify Facebook user"
                user_id_str = str(user_id) if user_id else "unknown"
                
                return {
                    "success": False, 
                    "error": f"No Facebook Pages found for {user_info}. Both /me/accounts and /{user_id_str}/accounts returned empty. Please verify: 1) You're logged in with the Facebook account that OWNS/MANAGES the Page (not just a personal account), 2) The Page actually exists and you can access it at facebook.com/pages, 3) You have admin or manager role on the Page (check Page Settings > Page Roles), 4) The Page is linked to an Instagram Business Account."
                }
            
            # Log all pages for debugging
            for page in pages:
                page_name = page.get("name", "Unknown")
                has_ig = "instagram_business_account" in page
                instagram_logger.debug(f"Page: {page_name}, Has Instagram: {has_ig}")
            
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
            
            instagram_logger.info(f"Instagram Username: @{username} for user {user_id}")
            
            # Calculate expiry (Instagram tokens are long-lived)
            expires_at = None
            if 'expires_in' in locals():
                from datetime import datetime, timedelta, timezone
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            
            # Store in database (encrypted)
            db_helpers.save_oauth_token(
                user_id=user_id,
                platform="instagram",
                access_token=page_access_token,
                refresh_token=None,  # Instagram doesn't use refresh tokens
                expires_at=expires_at,
                extra_data={
                    "user_access_token": access_token_to_use,
                    "page_id": page_id,
                    "business_account_id": business_account_id,
                    "username": username
                }
            )
            
            # Enable Instagram destination
            db_helpers.set_user_setting(user_id, "destinations", "instagram_enabled", True)
            
            instagram_logger.info(f"Instagram connected successfully for user {user_id}")
            
            return {"success": True}
            
    except Exception as e:
        instagram_logger.error(f"Complete auth exception: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

@app.get("/api/auth/instagram/account")
async def get_instagram_account(user_id: int = Depends(require_auth)):
    """Get Instagram account information (username)"""
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram")
    
    if not instagram_token:
        return {"account": None}
    
    try:
        # Get username from extra_data
        extra_data = instagram_token.extra_data or {}
        username = extra_data.get("username")
        business_account_id = extra_data.get("business_account_id")
        
        if username and business_account_id:
            return {"account": {"username": username, "user_id": business_account_id}}
        
        # If not cached, fetch from Instagram API
        access_token = decrypt(instagram_token.access_token)
        if not access_token:
            return {"account": None}
        
        # Fetch profile info
        profile_info = await fetch_instagram_profile(access_token)
        username = profile_info.get("username")
        business_account_id = profile_info.get("business_account_id")
        
        if not username or not business_account_id:
            instagram_logger.error(f"Failed to fetch Instagram profile for user {user_id}")
            return {"account": None, "error": "Failed to fetch account info"}
        
        # Update extra_data with cached info
        extra_data["username"] = username
        extra_data["business_account_id"] = business_account_id
        db_helpers.save_oauth_token(
            user_id=user_id,
            platform="instagram",
            access_token=instagram_token.access_token,  # Already encrypted
            refresh_token=None,
            expires_at=instagram_token.expires_at,
            extra_data=extra_data
        )
        
        account_info = {
            "username": username,
            "user_id": business_account_id  # This is the Business Account ID
        }
        
        return {"account": account_info}
    except Exception as e:
        instagram_logger.error(f"Error getting Instagram account info for user {user_id}: {str(e)}", exc_info=True)
        return {"account": None, "error": str(e)}

@app.post("/api/auth/instagram/disconnect")
def disconnect_instagram(user_id: int = Depends(require_csrf_new)):
    """Disconnect Instagram account"""
    db_helpers.delete_oauth_token(user_id, "instagram")
    db_helpers.set_user_setting(user_id, "destinations", "instagram_enabled", False)
    return {"message": "Disconnected"}


# Helper: Fetch Instagram profile info (username and Business Account ID)
async def fetch_instagram_profile(access_token: str) -> dict:
    """
    Fetch Instagram profile information using /me endpoint.
    Returns dict with 'username' and 'business_account_id' (or None for each if failed).
    This is the root cause fix - centralizes profile fetching logic.
    """
    try:
        async with httpx.AsyncClient() as client:
            me_response = await client.get(
                f"{INSTAGRAM_GRAPH_API_BASE}/me",
                params={
                    "fields": "id,username,account_type",
                    "access_token": access_token
                },
                timeout=10.0
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


@app.get("/api/global/settings")
def get_global_settings(user_id: int = Depends(require_auth)):
    """Get global settings"""
    return db_helpers.get_user_settings(user_id, "global")

@app.post("/api/global/settings")
def update_global_settings(
    user_id: int = Depends(require_csrf_new),
    title_template: str = None,
    description_template: str = None,
    upload_immediately: bool = None,
    schedule_mode: str = None,
    schedule_interval_value: int = None,
    schedule_interval_unit: str = None,
    schedule_start_time: str = None,
    allow_duplicates: bool = None
):
    """Update global settings"""
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "global", "title_template", title_template)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "global", "description_template", description_template)
    
    if upload_immediately is not None:
        db_helpers.set_user_setting(user_id, "global", "upload_immediately", upload_immediately)
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        db_helpers.set_user_setting(user_id, "global", "schedule_mode", schedule_mode)
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_value", schedule_interval_value)
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_unit", schedule_interval_unit)
    
    if schedule_start_time is not None:
        db_helpers.set_user_setting(user_id, "global", "schedule_start_time", schedule_start_time)
    
    if allow_duplicates is not None:
        db_helpers.set_user_setting(user_id, "global", "allow_duplicates", allow_duplicates)
    
    return db_helpers.get_user_settings(user_id, "global")

@app.get("/api/youtube/settings")
def get_youtube_settings(user_id: int = Depends(require_auth)):
    """Get YouTube upload settings"""
    return db_helpers.get_user_settings(user_id, "youtube")

@app.post("/api/youtube/settings")
def update_youtube_settings(
    user_id: int = Depends(require_csrf_new),
    visibility: str = None, 
    made_for_kids: bool = None,
    title_template: str = None,
    description_template: str = None,
    tags_template: str = None
):
    """Update YouTube upload settings"""
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        db_helpers.set_user_setting(user_id, "youtube", "visibility", visibility)
    
    if made_for_kids is not None:
        db_helpers.set_user_setting(user_id, "youtube", "made_for_kids", made_for_kids)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "youtube", "title_template", title_template)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "description_template", description_template)
    
    if tags_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "tags_template", tags_template)
    
    return db_helpers.get_user_settings(user_id, "youtube")

@app.get("/api/youtube/videos")
def get_youtube_videos(
    user_id: int = Depends(require_auth),
    page: int = 1,
    per_page: int = 50,
    hide_shorts: bool = False
):
    """Get user's YouTube videos (paginated)"""
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube")
    
    if not youtube_token:
        raise HTTPException(401, "YouTube not connected")
    
    # Decrypt and build credentials
    youtube_creds = google.oauth2.credentials.Credentials(
        token=decrypt(youtube_token.access_token),
        refresh_token=decrypt(youtube_token.refresh_token) if youtube_token.refresh_token else None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET
    )
    
    try:
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
                import re
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
        
    except Exception as e:
        youtube_logger.error(f"Error fetching YouTube videos: {str(e)}", exc_info=True)
        raise HTTPException(500, f"Error fetching videos: {str(e)}")

# TikTok settings endpoints
@app.get("/api/tiktok/settings")
def get_tiktok_settings(user_id: int = Depends(require_auth)):
    """Get TikTok upload settings"""
    return db_helpers.get_user_settings(user_id, "tiktok")

@app.post("/api/tiktok/settings")
def update_tiktok_settings(
    user_id: int = Depends(require_csrf_new),
    privacy_level: str = None,
    allow_comments: bool = None,
    allow_duet: bool = None,
    allow_stitch: bool = None,
    title_template: str = None,
    description_template: str = None
):
    """Update TikTok upload settings"""
    if privacy_level is not None:
        if privacy_level not in ["public", "private", "friends"]:
            raise HTTPException(400, "Invalid privacy level")
        db_helpers.set_user_setting(user_id, "tiktok", "privacy_level", privacy_level)
    
    if allow_comments is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_comments", allow_comments)
    
    if allow_duet is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_duet", allow_duet)
    
    if allow_stitch is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_stitch", allow_stitch)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "tiktok", "title_template", title_template)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "description_template", description_template)
    
    return db_helpers.get_user_settings(user_id, "tiktok")

# Instagram settings endpoints
@app.get("/api/instagram/settings")
def get_instagram_settings(user_id: int = Depends(require_auth)):
    """Get Instagram upload settings"""
    return db_helpers.get_user_settings(user_id, "instagram")

@app.post("/api/instagram/settings")
def update_instagram_settings(
    user_id: int = Depends(require_csrf_new),
    caption_template: str = None,
    location_id: str = None,
    disable_comments: bool = None,
    disable_likes: bool = None
):
    """Update Instagram upload settings"""
    if caption_template is not None:
        if len(caption_template) > 2200:
            raise HTTPException(400, "Caption template must be 2200 characters or less")
        db_helpers.set_user_setting(user_id, "instagram", "caption_template", caption_template)
    
    if location_id is not None:
        db_helpers.set_user_setting(user_id, "instagram", "location_id", location_id)
    
    if disable_comments is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_comments", disable_comments)
    
    if disable_likes is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_likes", disable_likes)
    
    return db_helpers.get_user_settings(user_id, "instagram")

@app.post("/api/videos")
async def add_video(file: UploadFile = File(...), user_id: int = Depends(require_csrf_new)):
    """Add video to user's queue"""
    # Get user settings
    global_settings = db_helpers.get_user_settings(user_id, "global")
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube")
    
    # Check for duplicates if not allowed
    if not global_settings.get("allow_duplicates", False):
        existing_videos = db_helpers.get_user_videos(user_id)
        if any(v.filename == file.filename for v in existing_videos):
            raise HTTPException(400, f"Duplicate video: {file.filename} is already in the queue")
    
    # Save file to disk
    path = UPLOAD_DIR / file.filename
    with open(path, "wb") as f:
        f.write(await file.read())
    
    # Generate YouTube title
    filename_no_ext = file.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    youtube_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Add to database
    video = db_helpers.add_user_video(
        user_id=user_id,
        filename=file.filename,
        path=str(path),
        generated_title=youtube_title
    )
    
    upload_logger.info(f"Video added for user {user_id}: {file.filename}")
    
    return {
        "id": video.id,
        "filename": video.filename,
        "path": video.path,
        "status": video.status,
        "generated_title": video.generated_title
    }

@app.get("/api/videos")
def get_videos(user_id: int = Depends(require_auth)):
    """Get video queue with progress and computed titles for user"""
    # Get user's videos and settings
    videos = db_helpers.get_user_videos(user_id)
    global_settings = db_helpers.get_user_settings(user_id, "global")
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube")
    tiktok_settings = db_helpers.get_user_settings(user_id, "tiktok")
    instagram_settings = db_helpers.get_user_settings(user_id, "instagram")
    dest_settings = db_helpers.get_user_settings(user_id, "destinations")
    
    # Get OAuth tokens
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube")
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok")
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram")
    
    videos_with_info = []
    for video in videos:
        video_dict = {
            "id": video.id,
            "filename": video.filename,
            "path": video.path,
            "status": video.status,
            "generated_title": video.generated_title,
            "custom_settings": video.custom_settings or {},
            "error": video.error,
            "scheduled_time": video.scheduled_time.isoformat() if hasattr(video, 'scheduled_time') and video.scheduled_time else None
        }
        
        # Add upload progress from Redis if available
        upload_progress = redis_client.get_upload_progress(user_id, video.id)
        if upload_progress is not None:
            video_dict['upload_progress'] = upload_progress
        
        # Compute YouTube title - Priority: custom > generated_title > template
        custom_settings = video.custom_settings or {}
        if 'title' in custom_settings:
            youtube_title = custom_settings['title']
        elif video.generated_title:
            youtube_title = video.generated_title
        else:
            filename_no_ext = video.filename.rsplit('.', 1)[0]
            title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            youtube_title = replace_template_placeholders(
                title_template,
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Enforce YouTube's 100 character limit
        video_dict['youtube_title'] = youtube_title[:100] if len(youtube_title) > 100 else youtube_title
        video_dict['title_too_long'] = len(youtube_title) > 100
        video_dict['title_original_length'] = len(youtube_title)
        
        # Compute upload properties
        upload_props = {}
        
        # YouTube properties
        if dest_settings.get("youtube_enabled") and youtube_token:
            filename_no_ext = video.filename.rsplit('.', 1)[0]
            upload_props['youtube'] = {
                'title': video_dict['youtube_title'],
                'visibility': custom_settings.get('visibility', youtube_settings.get('visibility', 'private')),
                'made_for_kids': custom_settings.get('made_for_kids', youtube_settings.get('made_for_kids', False)),
            }
            
            # Description
            if 'description' in custom_settings:
                upload_props['youtube']['description'] = custom_settings['description']
            else:
                desc_template = youtube_settings.get('description_template', '') or global_settings.get('description_template', '')
                upload_props['youtube']['description'] = replace_template_placeholders(
                    desc_template, filename_no_ext, global_settings.get('wordbank', [])
                ) if desc_template else ''
            
            # Tags
            if 'tags' in custom_settings:
                upload_props['youtube']['tags'] = custom_settings['tags']
            else:
                tags_template = youtube_settings.get('tags_template', '')
                upload_props['youtube']['tags'] = replace_template_placeholders(
                    tags_template, filename_no_ext, global_settings.get('wordbank', [])
                ) if tags_template else ''
        
        # TikTok properties
        if dest_settings.get("tiktok_enabled") and tiktok_token:
            filename_no_ext = video.filename.rsplit('.', 1)[0]
            
            if 'title' in custom_settings:
                tiktok_title = custom_settings['title']
            elif video.generated_title:
                tiktok_title = video.generated_title
            else:
                title_template = tiktok_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
                tiktok_title = replace_template_placeholders(
                    title_template, filename_no_ext, global_settings.get('wordbank', [])
                )
            
            upload_props['tiktok'] = {
                'title': tiktok_title[:2200] if len(tiktok_title) > 2200 else tiktok_title,
                'privacy_level': custom_settings.get('privacy_level', tiktok_settings.get('privacy_level', 'public')),
                'allow_comments': custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', True)),
                'allow_duet': custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', True)),
                'allow_stitch': custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', True))
            }
        
        # Instagram properties
        if dest_settings.get("instagram_enabled") and instagram_token:
            filename_no_ext = video.filename.rsplit('.', 1)[0]
            
            # Caption
            if 'title' in custom_settings:
                caption = custom_settings['title']
            elif video.generated_title:
                caption = video.generated_title
            else:
                caption_template = instagram_settings.get('caption_template', '') or global_settings.get('title_template', '{filename}')
                caption = replace_template_placeholders(
                    caption_template, filename_no_ext, global_settings.get('wordbank', [])
                )
            
            upload_props['instagram'] = {
                'caption': caption[:2200] if len(caption) > 2200 else caption,
                'location_id': instagram_settings.get('location_id', ''),
                'disable_comments': instagram_settings.get('disable_comments', False),
                'disable_likes': instagram_settings.get('disable_likes', False)
            }
        
        video_dict['upload_properties'] = upload_props
        videos_with_info.append(video_dict)
    
    return videos_with_info

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, user_id: int = Depends(require_csrf_new)):
    """Remove video from user's queue"""
    success = db_helpers.delete_video(video_id, user_id)
    if not success:
        raise HTTPException(404, "Video not found")
    
    # Clean up file if it exists
    videos = db_helpers.get_user_videos(user_id)
    video = next((v for v in videos if v.id == video_id), None)
    if video and Path(video.path).exists():
        try:
            Path(video.path).unlink()
        except Exception as e:
            upload_logger.warning(f"Could not delete file {video.path}: {e}")
    
    return {"ok": True}

@app.post("/api/videos/{video_id}/recompute-title")
def recompute_video_title(video_id: int, user_id: int = Depends(require_csrf_new)):
    """Recompute video title from current template"""
    # Get video
    videos = db_helpers.get_user_videos(user_id)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Get settings
    global_settings = db_helpers.get_user_settings(user_id, "global")
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube")
    
    # Remove custom title if exists in custom_settings
    custom_settings = video.custom_settings or {}
    if "title" in custom_settings:
        del custom_settings["title"]
        db_helpers.update_video(video_id, user_id, custom_settings=custom_settings)
    
    # Regenerate title
    filename_no_ext = video.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    
    new_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Update generated_title in database
    db_helpers.update_video(video_id, user_id, generated_title=new_title)
    
    return {"ok": True, "title": new_title[:100]}

@app.patch("/api/videos/{video_id}")
def update_video(
    video_id: int,
    user_id: int = Depends(require_csrf_new),
    title: str = None,
    description: str = None,
    tags: str = None,
    visibility: str = None,
    made_for_kids: bool = None,
    scheduled_time: str = None
):
    """Update video settings"""
    # Get video
    videos = db_helpers.get_user_videos(user_id)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Update custom settings
    custom_settings = video.custom_settings or {}
    
    if title is not None:
        if len(title) > 100:
            raise HTTPException(400, "Title must be 100 characters or less")
        custom_settings["title"] = title
    
    if description is not None:
        custom_settings["description"] = description
    
    if tags is not None:
        custom_settings["tags"] = tags
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        custom_settings["visibility"] = visibility
    
    if made_for_kids is not None:
        custom_settings["made_for_kids"] = made_for_kids
    
    # Build update dict
    update_data = {"custom_settings": custom_settings}
    
    # Handle scheduled_time
    if scheduled_time is not None:
        if scheduled_time:  # Set schedule
            try:
                from datetime import datetime
                parsed_time = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                update_data["scheduled_time"] = parsed_time
                if video.status == "pending":
                    update_data["status"] = "scheduled"
            except ValueError:
                raise HTTPException(400, "Invalid datetime format")
        else:  # Clear schedule
            update_data["scheduled_time"] = None
            if video.status == "scheduled":
                update_data["status"] = "pending"
    
    # Update in database
    db_helpers.update_video(video_id, user_id, **update_data)
    
    # Return updated video
    updated_videos = db_helpers.get_user_videos(user_id)
    updated_video = next((v for v in updated_videos if v.id == video_id), None)
    
    return {
        "id": updated_video.id,
        "filename": updated_video.filename,
        "status": updated_video.status,
        "custom_settings": updated_video.custom_settings,
        "scheduled_time": updated_video.scheduled_time.isoformat() if hasattr(updated_video, 'scheduled_time') and updated_video.scheduled_time else None
    }

@app.post("/api/videos/reorder")
async def reorder_videos(request: Request, user_id: int = Depends(require_csrf_new)):
    """Reorder videos in the user's queue"""
    try:
        # Parse JSON body
        body = await request.json()
        video_ids = body.get("video_ids", [])
        
        if not video_ids:
            raise HTTPException(400, "video_ids required")
        
        # Get user's videos
        videos = db_helpers.get_user_videos(user_id)
        video_map = {v.id: v for v in videos}
        
        # Note: Currently we don't have an order field in the Video model
        # This would require adding an 'order' or 'position' column
        # For now, we'll just acknowledge the reorder (frontend handles display order)
        # TODO: Add 'order' field to Video model for persistent ordering
        
        return {"ok": True, "count": len(video_ids)}
    except Exception as e:
        raise HTTPException(400, f"Invalid request: {str(e)}")

@app.post("/api/videos/cancel-scheduled")
async def cancel_scheduled_videos(user_id: int = Depends(require_csrf_new)):
    """Cancel all scheduled videos for user"""
    videos = db_helpers.get_user_videos(user_id)
    cancelled_count = 0
    
    for video in videos:
        if video.status == "scheduled":
            video_id = video.id
            db_helpers.update_video(video_id, user_id, status="pending", scheduled_time=None)
            cancelled_count += 1
    
    return {"ok": True, "cancelled": cancelled_count}


def upload_video_to_youtube(video, session):
    """Helper function to upload a single video to YouTube"""
    youtube_creds = session["youtube_creds"]
    youtube_settings = session["youtube_settings"]
    upload_progress = session["upload_progress"]
    
    youtube_logger.info(f"Starting upload for {video['filename']}")
    
    if not youtube_creds:
        video['status'] = 'failed'
        video['error'] = 'No YouTube credentials'
        youtube_logger.error("No YouTube credentials")
        return
    
    # Validate credentials are complete
    if not youtube_creds.client_id or not youtube_creds.client_secret or not youtube_creds.token_uri:
        video['status'] = 'failed'
        error_msg = 'YouTube credentials are incomplete. Please disconnect and reconnect YouTube.'
        video['error'] = error_msg
        youtube_logger.error(error_msg)
        return
    
    try:
        video['status'] = 'uploading'
        upload_progress[video['id']] = 0
        
        youtube_logger.debug("Building YouTube API client...")
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Check for custom settings, otherwise use global settings and templates
        custom_settings = video.get('custom_settings', {})
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        
        # Priority for title: custom > generated_title > destination > global
        if 'title' in custom_settings:
            title = custom_settings['title']
        elif 'generated_title' in video:
            # Use the pre-generated title from when video was added
            title = video['generated_title']
        else:
            # Fallback: destination template > global template
            global_settings = session.get("global_settings", {})
            title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            title = replace_template_placeholders(
                title_template, 
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Enforce YouTube's 100 character limit for titles
        if len(title) > 100:
            title = title[:100]
        
        # Priority for description: custom > destination > global
        if 'description' in custom_settings:
            description = custom_settings['description']
        else:
            # Fallback: destination template > global template
            global_settings = session.get("global_settings", {})
            desc_template = youtube_settings.get('description_template', '') or global_settings.get('description_template', 'Uploaded via Hopper')
            description = replace_template_placeholders(
                desc_template,
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Use custom visibility if set, otherwise use global setting
        visibility = custom_settings.get('visibility', youtube_settings['visibility'])
        made_for_kids = custom_settings.get('made_for_kids', youtube_settings['made_for_kids'])
        
        # Use custom tags if set, otherwise use template (tags use global wordbank)
        if 'tags' in custom_settings:
            tags_str = custom_settings['tags']
        else:
            global_settings = session.get("global_settings", {})
            tags_str = replace_template_placeholders(
                youtube_settings.get('tags_template', ''),
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Parse tags (comma-separated, strip whitespace, filter empty)
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
        
        snippet_body = {
            'title': title,
            'description': description,
            'categoryId': '22'
        }
        
        # Only add tags if there are any
        if tags:
            snippet_body['tags'] = tags
        
        youtube_logger.info(f"Preparing upload request - Title: {title[:50]}..., Visibility: {visibility}")
        youtube_logger.debug(f"Video path: {video['path']}")
        
        request = youtube.videos().insert(
            part='snippet,status',
            body={
                'snippet': snippet_body,
                'status': {
                    'privacyStatus': visibility,
                    'selfDeclaredMadeForKids': made_for_kids
                }
            },
            media_body=MediaFileUpload(video['path'], resumable=True)
        )
        
        youtube_logger.info("Starting resumable upload...")
        response = None
        chunk_count = 0
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                upload_progress[video['id']] = progress
                chunk_count += 1
                if chunk_count % 10 == 0 or progress == 100:  # Log every 10 chunks or at completion
                    youtube_logger.info(f"Upload progress: {progress}%")
        
        video['status'] = 'uploaded'
        video['youtube_id'] = response['id']
        upload_progress[video['id']] = 100
        youtube_logger.info(f"Successfully uploaded {video['filename']}, YouTube ID: {response['id']}")
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = str(e)
        youtube_logger.error(f"Error uploading {video['filename']}: {str(e)}", exc_info=True)
        if video['id'] in upload_progress:
            del upload_progress[video['id']]


def check_tiktok_rate_limit(session_id):
    """Check if TikTok API rate limit is exceeded (6 requests per minute)"""
    import time
    current_time = time.time()
    
    if session_id not in tiktok_rate_limiter:
        tiktok_rate_limiter[session_id] = []
    
    # Keep only recent requests
    tiktok_rate_limiter[session_id] = [
        ts for ts in tiktok_rate_limiter[session_id]
        if current_time - ts < TIKTOK_RATE_LIMIT_WINDOW
    ]
    
    # Check limit
    if len(tiktok_rate_limiter[session_id]) >= TIKTOK_RATE_LIMIT_REQUESTS:
        wait_time = int(TIKTOK_RATE_LIMIT_WINDOW - (current_time - min(tiktok_rate_limiter[session_id])))
        raise Exception(f"TikTok rate limit exceeded. Wait {wait_time}s before trying again.")
    
    tiktok_rate_limiter[session_id].append(current_time)


def get_tiktok_creator_info(session):
    """Query TikTok creator info and cache it in session"""
    # Return cached if available
    if session.get("tiktok_creator_info"):
        return session["tiktok_creator_info"]
    
    access_token = session.get("tiktok_creds", {}).get("access_token")
    if not access_token:
        raise Exception("No TikTok access token")
    
    response = httpx.post(
        TIKTOK_CREATOR_INFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        },
        json={},
        timeout=30.0
    )
    
    if response.status_code != 200:
        error = response.json().get("error", {})
        raise Exception(f"Failed to query creator info: {error.get('code', 'unknown')} - {error.get('message', response.text)}")
    
    # Log the full response for debugging
    response_json = response.json()
    tiktok_logger.debug(f"TikTok creator_info API response: {response_json}")
    
    # Cache and return
    creator_info = response_json.get("data", {})
    tiktok_logger.debug(f"Extracted creator_info keys: {list(creator_info.keys())}")
    tiktok_logger.debug(f"Extracted creator_info: {creator_info}")
    
    session["tiktok_creator_info"] = creator_info
    return session["tiktok_creator_info"]


def map_privacy_level_to_tiktok(privacy_level, creator_info):
    """Map frontend privacy level to TikTok's format"""
    mapping = {
        "public": "PUBLIC_TO_EVERYONE",
        "private": "SELF_ONLY",
        "friends": "MUTUAL_FOLLOW_FRIENDS"
    }
    
    # Normalize and map
    privacy_level = str(privacy_level).lower().strip() if privacy_level else "public"
    tiktok_privacy = mapping.get(privacy_level, "PUBLIC_TO_EVERYONE")
    
    # Validate against available options
    available_options = creator_info.get("privacy_level_options", [])
    if available_options and tiktok_privacy not in available_options:
        tiktok_logger.warning(f"Privacy '{tiktok_privacy}' not available, using '{available_options[0]}'")
        tiktok_privacy = available_options[0]
    
    return tiktok_privacy


def upload_video_to_tiktok(video, session, session_id=None):
    """Upload video to TikTok using Content Posting API"""
    tiktok_creds = session.get("tiktok_creds")
    tiktok_settings = session.get("tiktok_settings", {})
    upload_progress = session["upload_progress"]
    
    # Get user_id for logging
    user_id = session.get("user_id", "unknown")
    
    if not tiktok_creds:
        video['status'] = 'failed'
        video['error'] = 'No TikTok credentials'
        return
    
    try:
        video['status'] = 'uploading'
        upload_progress[video['id']] = 0
        
        access_token = tiktok_creds.get("access_token")
        if not access_token:
            raise Exception("No TikTok access token")
        
        check_tiktok_rate_limit(session_id)
        creator_info = get_tiktok_creator_info(session)
        
        # Get video file
        video_path = Path(video['path'])
        if not video_path.exists():
            raise Exception(f"Video file not found: {video['path']}")
        
        video_size = video_path.stat().st_size
        if video_size == 0:
            raise Exception("Video file is empty")
        
        # Prepare metadata
        custom_settings = video.get('custom_settings', {})
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        
        # Get title (priority: custom > generated > template > filename)
        if 'title' in custom_settings:
            title = custom_settings['title']
        elif 'generated_title' in video:
            title = video['generated_title']
        else:
            global_settings = session.get("global_settings", {})
            title_template = tiktok_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            title = replace_template_placeholders(title_template, filename_no_ext, global_settings.get('wordbank', []))
        
        title = (title or filename_no_ext)[:2200]  # TikTok limit
        
        # Get settings with defaults
        privacy_level = custom_settings.get('privacy_level', tiktok_settings.get('privacy_level', 'public'))
        tiktok_privacy = map_privacy_level_to_tiktok(privacy_level, creator_info)
        allow_comments = custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', True))
        allow_duet = custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', True))
        allow_stitch = custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', True))
        
        tiktok_logger.info(f"Uploading {video['filename']} ({video_size / (1024*1024):.2f} MB)")
        upload_progress[video['id']] = 5
        
        # Step 1: Initialize upload
        init_response = httpx.post(
            TIKTOK_INIT_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8"
            },
            json={
                "post_info": {
                    "title": title,
                    "privacy_level": tiktok_privacy,
                    "disable_duet": not allow_duet,
                    "disable_comment": not allow_comments,
                    "disable_stitch": not allow_stitch
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
                }
            },
            timeout=30.0
        )
        
        if init_response.status_code != 200:
            import json as json_module
            
            # Log the request that was sent
            request_body = {
                "post_info": {
                    "title": title,
                    "privacy_level": tiktok_privacy,
                    "disable_duet": not allow_duet,
                    "disable_comment": not allow_comments,
                    "disable_stitch": not allow_stitch
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
                }
            }
            tiktok_logger.debug(f"Request body: {json_module.dumps(request_body, indent=2)}")
            
            # Log the full response
            tiktok_logger.error(f"Init failed with status {init_response.status_code}")
            try:
                response_data = init_response.json()
                tiktok_logger.error(f"Full response: {json_module.dumps(response_data, indent=2)}")
                error = response_data.get("error", {})
                raise Exception(f"Init failed: {error.get('message', 'Unknown error')}")
            except Exception as parse_error:
                tiktok_logger.error(f"Raw response text: {init_response.text}")
                raise Exception(f"Init failed: {init_response.status_code} - {init_response.text}")
        
        init_data = init_response.json()
        publish_id = init_data["data"]["publish_id"]
        upload_url = init_data["data"]["upload_url"]
        
        tiktok_logger.info(f"Initialized, publish_id: {publish_id}")
        upload_progress[video['id']] = 10
        
        # Step 2: Upload video file
        tiktok_logger.info("Uploading video file...")
        
        file_ext = video['filename'].rsplit('.', 1)[-1].lower()
        content_type = {'mp4': 'video/mp4', 'mov': 'video/quicktime', 'webm': 'video/webm'}.get(file_ext, 'video/mp4')
        
        with open(video_path, 'rb') as f:
            upload_response = httpx.put(
                upload_url,
                headers={
                    "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                    "Content-Type": content_type
                },
                content=f.read(),
                timeout=300.0
            )
        
        if upload_response.status_code not in [200, 201]:
            import json as json_module
            tiktok_logger.error(f"Upload failed with status {upload_response.status_code}")
            try:
                response_data = upload_response.json()
                tiktok_logger.error(f"Full upload response: {json_module.dumps(response_data, indent=2)}")
                error_msg = response_data.get("error", {}).get("message", upload_response.text)
            except:
                tiktok_logger.error(f"Raw upload response: {upload_response.text}")
                error_msg = upload_response.text
            raise Exception(f"Upload failed: {upload_response.status_code} - {error_msg}")
        
        # Success
        upload_progress[video['id']] = 100
        video['tiktok_publish_id'] = publish_id
        video['status'] = 'uploaded'
        video['tiktok_id'] = publish_id
        
        tiktok_logger.info(f"Success! publish_id: {publish_id}")
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = f'TikTok upload failed: {str(e)}'
        tiktok_logger.error(f"Upload error: {str(e)}", exc_info=True)
        upload_progress.pop(video['id'], None)
            
async def upload_video_to_instagram(video, session):
    """Upload video to Instagram using Graph API"""
    instagram_creds = session.get("instagram_creds")
    instagram_settings = session.get("instagram_settings", {})
    upload_progress = session["upload_progress"]
    
    instagram_logger.info(f"Starting upload for {video['filename']}")
    
    if not instagram_creds:
        video['status'] = 'failed'
        video['error'] = 'No Instagram credentials'
        instagram_logger.error("No Instagram credentials")
        return
    
    # Log what credentials we have (without exposing full token)
    instagram_logger.debug(f"Instagram creds keys: {list(instagram_creds.keys())}")
    instagram_logger.debug(f"Has access_token: {'access_token' in instagram_creds}")
    instagram_logger.debug(f"Has business_account_id: {'business_account_id' in instagram_creds}")
    if 'access_token' in instagram_creds:
        token = instagram_creds.get("access_token")
        instagram_logger.debug(f"Access token type: {type(token)}, length: {len(str(token)) if token else 0}")
    
    try:
        video['status'] = 'uploading'
        upload_progress[video['id']] = 0
        
        access_token = instagram_creds.get("access_token")
        business_account_id = instagram_creds.get("business_account_id")
        
        if not access_token:
            raise Exception("No Instagram access token")
        
        if not business_account_id:
            raise Exception("No Instagram Business Account ID. Please reconnect your Instagram account.")
        
        # Validate token format (should be a non-empty string)
        if not isinstance(access_token, str) or len(access_token.strip()) == 0:
            instagram_logger.error(f"Invalid access token format. Type: {type(access_token)}, Value: {access_token[:50] if access_token else 'None'}...")
            raise Exception("Invalid Instagram access token format. Please reconnect your Instagram account.")
        
        instagram_logger.debug(f"Using access token: {access_token[:20]}... (length: {len(access_token)})")
        instagram_logger.debug(f"Using business account ID: {business_account_id}")
        
        # Get video file
        video_path = Path(video['path'])
        if not video_path.exists():
            raise Exception(f"Video file not found: {video['path']}")
        
        # Prepare caption
        custom_settings = video.get('custom_settings', {})
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        
        # Get caption (priority: custom > generated > template > global)
        if 'title' in custom_settings:
            caption = custom_settings['title']
        elif 'generated_title' in video:
            caption = video['generated_title']
        else:
            global_settings = session.get("global_settings", {})
            caption_template = instagram_settings.get('caption_template', '') or global_settings.get('title_template', '{filename}')
            caption = replace_template_placeholders(
                caption_template,
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Instagram caption limit is 2200 characters
        caption = (caption or filename_no_ext)[:2200]
        
        # Get settings
        location_id = instagram_settings.get('location_id', '')
        disable_comments = instagram_settings.get('disable_comments', False)
        disable_likes = instagram_settings.get('disable_likes', False)
        
        instagram_logger.info(f"Uploading {video['filename']} to Instagram")
        upload_progress[video['id']] = 10
        
        # Instagram Graph API video upload process (per official docs):
        # 1. Create a container with media_type=REELS and upload_type=resumable
        # 2. Upload video to rupload.facebook.com
        # 3. Check container status
        # 4. Publish the container
        
        # Read video file
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        video_size = len(video_data)
        upload_progress[video['id']] = 20
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Step 1: Create resumable upload container
            # Per docs: POST https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/media?upload_type=resumable
            container_url = f"https://graph.facebook.com/v21.0/{business_account_id}/media"
            container_params = {
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption
            }
            
            # Add optional params
            if location_id:
                container_params["location_id"] = location_id
            
            # Per docs: Use Authorization header with Bearer token
            container_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Creating resumable upload container for {video['filename']}")
            instagram_logger.debug(f"Container URL: {container_url}")
            instagram_logger.debug(f"Container params: {dict((k, v) for k, v in container_params.items())}")
            instagram_logger.debug(f"Access token length: {len(access_token)}, starts with: {access_token[:10]}...")
            
            container_response = await client.post(
                container_url,
                json=container_params,  # Use json instead of data for JSON body
                headers=container_headers
            )
            
            if container_response.status_code != 200:
                error_data = container_response.json() if container_response.headers.get('content-type', '').startswith('application/json') else container_response.text
                instagram_logger.error(f"Failed to create container: {error_data}")
                instagram_logger.error(f"Response status: {container_response.status_code}")
                instagram_logger.error(f"Response headers: {dict(container_response.headers)}")
                
                # Check if it's a token expiration issue
                if isinstance(error_data, dict) and error_data.get('error', {}).get('code') == 190:
                    raise Exception("Instagram access token is invalid or expired. Please reconnect your Instagram account.")
                
                raise Exception(f"Failed to create resumable upload container: {error_data}")
            
            container_result = container_response.json()
            container_id = container_result.get('id')
            
            if not container_id:
                raise Exception(f"No container ID in response: {container_result}")
            
            instagram_logger.info(f"Created container {container_id}")
            video['instagram_container_id'] = container_id
            upload_progress[video['id']] = 40
            
            # Step 2: Upload video to rupload.facebook.com
            upload_url = f"https://rupload.facebook.com/ig-api-upload/v21.0/{container_id}"
            upload_headers = {
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(video_size)
            }
            
            instagram_logger.info(f"Uploading video data ({video_size} bytes) to rupload.facebook.com")
            
            upload_response = await client.post(
                upload_url,
                headers=upload_headers,
                content=video_data
            )
            
            if upload_response.status_code != 200:
                error_data = upload_response.json() if upload_response.headers.get('content-type', '').startswith('application/json') else upload_response.text
                instagram_logger.error(f"Failed to upload video: {error_data}")
                raise Exception(f"Failed to upload video data: {error_data}")
            
            upload_result = upload_response.json()
            if not upload_result.get('success'):
                raise Exception(f"Upload failed: {upload_result}")
            
            instagram_logger.info(f"Video uploaded successfully")
            upload_progress[video['id']] = 70
            
            # Step 3: Wait for Instagram to process the video and check status
            instagram_logger.info(f"Waiting for Instagram to process video")
            await asyncio.sleep(5)
            
            # Check container status
            # Per docs: GET /<IG_MEDIA_CONTAINER_ID>?fields=status_code
            status_url = f"https://graph.facebook.com/v21.0/{container_id}"
            status_params = {
                "fields": "status_code"
            }
            status_headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            for attempt in range(5):  # Check up to 5 times (once per minute for 5 minutes max)
                status_response = await client.get(status_url, params=status_params, headers=status_headers)
                if status_response.status_code == 200:
                    status_result = status_response.json()
                    status_code = status_result.get('status_code')
                    instagram_logger.info(f"Container status (attempt {attempt + 1}): {status_code}")
                    
                    if status_code == 'FINISHED':
                        break
                    elif status_code == 'ERROR':
                        raise Exception(f"Container processing failed")
                    elif status_code == 'EXPIRED':
                        raise Exception(f"Container expired")
                    # IN_PROGRESS - wait and retry
                
                if attempt < 4:
                    await asyncio.sleep(60)  # Wait 60 seconds before checking again (per docs: once per minute)
            
            upload_progress[video['id']] = 85
            
            # Step 4: Publish the container
            # Per docs: POST https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/media_publish?creation_id=<IG_MEDIA_CONTAINER_ID>
            publish_url = f"https://graph.facebook.com/v21.0/{business_account_id}/media_publish"
            publish_params = {
                "creation_id": container_id
            }
            publish_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Publishing container {container_id}")
            
            publish_response = await client.post(publish_url, json=publish_params, headers=publish_headers)
            
            if publish_response.status_code != 200:
                error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else publish_response.text
                instagram_logger.error(f"Failed to publish: {error_data}")
                raise Exception(f"Failed to publish media: {error_data}")
            
            publish_result = publish_response.json()
            media_id = publish_result.get('id')
            
            if not media_id:
                raise Exception(f"No media ID in publish response: {publish_result}")
            
            instagram_logger.info(f"Published to Instagram: {media_id}")
            
            video['instagram_id'] = media_id
            video['status'] = 'completed'
            upload_progress[video['id']] = 100
            
            # Clean up progress after a delay
            await asyncio.sleep(2)
            upload_progress.pop(video['id'], None)
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = f'Instagram upload failed: {str(e)}'
        instagram_logger.error(f"Error uploading {video['filename']}: {str(e)}", exc_info=True)
        upload_progress.pop(video['id'], None)

# Register upload functions
DESTINATION_UPLOADERS["youtube"] = upload_video_to_youtube
DESTINATION_UPLOADERS["tiktok"] = upload_video_to_tiktok
DESTINATION_UPLOADERS["instagram"] = upload_video_to_instagram

async def scheduler_task():
    """Background task that checks for scheduled videos and uploads them to all enabled destinations"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = datetime.now(timezone.utc)
            
            # Get all users from database
            with db_helpers.get_db() as db:
                from models import User
                users = db.query(User).all()
                
                for user in users:
                    user_id = user.id
                    
                    # Get user's scheduled videos
                    videos = db_helpers.get_user_videos(user_id)
                    
                    for video in videos:
                        if video.status == 'scheduled' and video.scheduled_time:
                            try:
                                scheduled_time = datetime.fromisoformat(video.scheduled_time) if isinstance(video.scheduled_time, str) else video.scheduled_time
                                
                                # If scheduled time has passed, upload the video
                                if current_time >= scheduled_time:
                                    video_id = video.id
                                    print(f"Uploading scheduled video for user {user_id}: {video.filename}")
                                    
                                    # Mark as uploading
                                    db_helpers.update_video(video_id, user_id, status="uploading")
                                    
                                    # Get enabled destinations
                                    dest_settings = db_helpers.get_user_settings(user_id, "destinations")
                                    enabled_destinations = []
                                    for dest_name in ["youtube", "tiktok", "instagram"]:
                                        is_enabled = dest_settings.get(f"{dest_name}_enabled", False)
                                        has_token = db_helpers.get_oauth_token(user_id, dest_name) is not None
                                        if is_enabled and has_token:
                                            enabled_destinations.append(dest_name)
                                    
                                    if not enabled_destinations:
                                        print(f"  No enabled destinations for user {user_id}, skipping")
                                        continue
                                    
                                    # Build temporary session-like structure for uploader functions
                                    temp_session = {
                                        "user_id": user_id,
                                        "youtube_settings": db_helpers.get_user_settings(user_id, "youtube") or {},
                                        "tiktok_settings": db_helpers.get_user_settings(user_id, "tiktok") or {},
                                        "instagram_settings": db_helpers.get_user_settings(user_id, "instagram") or {},
                                    }
                                    
                                    # Load OAuth tokens
                                    for dest_name in enabled_destinations:
                                        token = db_helpers.get_oauth_token(user_id, dest_name)
                                        if token:
                                            creds = {
                                                "access_token": decrypt(token.access_token),
                                                "refresh_token": decrypt(token.refresh_token) if token.refresh_token else None,
                                            }
                                            if token.extra_data:
                                                creds.update(token.extra_data)
                                            temp_session[f"{dest_name}_creds"] = creds
                                    
                                    # Convert video object to dict for uploader functions
                                    video_dict = {
                                        "id": video.id,
                                        "filename": video.filename,
                                        "path": video.path,
                                        "status": video.status,
                                        "generated_title": video.generated_title,
                                    }
                                    
                                    # Upload to each enabled destination
                                    success_count = 0
                                    for dest_name in enabled_destinations:
                                        uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                                        if uploader_func:
                                            try:
                                                print(f"  Uploading to {dest_name}...")
                                                if dest_name == "instagram":
                                                    await uploader_func(video_dict, temp_session)
                                                else:
                                                    uploader_func(video_dict, temp_session)
                                                success_count += 1
                                            except Exception as upload_err:
                                                print(f"  Error uploading to {dest_name}: {upload_err}")
                                    
                                    # Update final status
                                    if success_count == len(enabled_destinations):
                                        db_helpers.update_video(video_id, user_id, status="uploaded")
                                    else:
                                        db_helpers.update_video(video_id, user_id, status="failed", error=f"Upload failed for some destinations")
                                        
                            except Exception as e:
                                print(f"Error processing scheduled video {video.filename}: {e}")
                                db_helpers.update_video(video_id, user_id, status="failed", error=str(e))
        except Exception as e:
            print(f"Error in scheduler task: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    """Start the scheduler when the app starts"""
    asyncio.create_task(scheduler_task())
    print("Scheduler task started")

@app.post("/api/upload")
async def upload_videos(user_id: int = Depends(require_csrf_new)):
    """Upload all pending videos to all enabled destinations (immediate or scheduled)"""
    
    # Check if at least one destination is enabled and connected
    enabled_destinations = []
    
    upload_logger.debug(f"Checking destinations for user {user_id}...")
    
    # Get destination settings
    destination_settings = db_helpers.get_user_settings(user_id, "destinations")
    
    for dest_name in ["youtube", "tiktok", "instagram"]:
        # Check if destination is enabled
        is_enabled = destination_settings.get(f"{dest_name}_enabled", False)
        
        # Check if user has OAuth token for this destination
        has_token = db_helpers.get_oauth_token(user_id, dest_name) is not None
        
        upload_logger.debug(f"{dest_name}: enabled={is_enabled}, has_token={has_token}")
        
        if is_enabled and has_token:
            enabled_destinations.append(dest_name)
    
    upload_logger.info(f"Enabled destinations for user {user_id}: {enabled_destinations}")
    
    if not enabled_destinations:
        error_msg = "No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        upload_logger.error(error_msg)
        raise HTTPException(400, error_msg)
    
    # Get videos that can be uploaded: pending, failed (retry), or uploading (retry if stuck)
    user_videos = db_helpers.get_user_videos(user_id)
    pending_videos = [v for v in user_videos if v.status in ['pending', 'failed', 'uploading']]
    
    upload_logger.info(f"Videos ready to upload for user {user_id}: {len(pending_videos)}")
    
    # Get global settings for upload behavior
    global_settings = db_helpers.get_user_settings(user_id, "global")
    upload_immediately = global_settings.get("upload_immediately", True)
    
    if not pending_videos:
        # Check what statuses videos actually have
        statuses = {}
        for v in user_videos:
            status = v.status or 'unknown'
            statuses[status] = statuses.get(status, 0) + 1
        error_msg = f"No videos ready to upload. Add videos first. Current video statuses: {statuses}"
        upload_logger.error(error_msg)
        raise HTTPException(400, error_msg)
    
    # If upload immediately is enabled, upload all at once to all enabled destinations
    if upload_immediately:
        for video in pending_videos:
            video_id = video.id
            
            # Set status to uploading before starting
            db_helpers.update_video(video_id, user_id, status="uploading")
            
            # Track which destinations succeeded/failed
            succeeded_destinations = []
            failed_destinations = []
            
            # Build a temporary session-like structure for uploader functions
            # TODO: Refactor uploader functions to work directly with database
            temp_session = {
                "user_id": user_id,
                "youtube_creds": None,
                "tiktok_creds": None,
                "instagram_creds": None,
                "youtube_settings": db_helpers.get_user_settings(user_id, "youtube") or {},
                "tiktok_settings": db_helpers.get_user_settings(user_id, "tiktok") or {},
                "instagram_settings": db_helpers.get_user_settings(user_id, "instagram") or {},
            }
            
            # Load OAuth tokens for enabled destinations
            for dest_name in enabled_destinations:
                token = db_helpers.get_oauth_token(user_id, dest_name)
                if token:
                    creds = {
                        "access_token": decrypt(token.access_token),
                        "refresh_token": decrypt(token.refresh_token) if token.refresh_token else None,
                        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                    }
                    # Add extra_data fields
                    if token.extra_data:
                        creds.update(token.extra_data)
                    temp_session[f"{dest_name}_creds"] = creds
            
            # Convert video object to dict for uploader functions (they expect dict format)
            video_dict = {
                "id": video.id,
                "filename": video.filename,
                "path": video.path,
                "status": video.status,
                "generated_title": video.generated_title,
                "youtube_id": getattr(video, 'youtube_id', None),
                "tiktok_id": getattr(video, 'tiktok_id', None),
                "tiktok_publish_id": getattr(video, 'tiktok_publish_id', None),
                "instagram_id": getattr(video, 'instagram_id', None),
                "instagram_container_id": getattr(video, 'instagram_container_id', None),
                "error": getattr(video, 'error', None),
            }
            
            # Upload to all enabled destinations
            for dest_name in enabled_destinations:
                uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                if uploader_func:
                    upload_logger.info(f"Uploading {video.filename} to {dest_name} for user {user_id}")
                    
                    try:
                        # Pass appropriate parameters based on destination
                        if dest_name == "instagram":
                            await uploader_func(video_dict, temp_session)
                        else:
                            uploader_func(video_dict, temp_session)
                        
                        # Check if this destination succeeded by looking for success markers
                        if dest_name == 'youtube' and video_dict.get('youtube_id'):
                            succeeded_destinations.append(dest_name)
                            upload_logger.info(f"YouTube upload succeeded for {video.filename}")
                        elif dest_name == 'tiktok' and (video_dict.get('tiktok_id') or video_dict.get('tiktok_publish_id')):
                            succeeded_destinations.append(dest_name)
                            upload_logger.info(f"TikTok upload succeeded for {video.filename}")
                        elif dest_name == 'instagram' and (video_dict.get('instagram_id') or video_dict.get('instagram_container_id')):
                            succeeded_destinations.append(dest_name)
                            upload_logger.info(f"Instagram upload succeeded for {video.filename}")
                        else:
                            failed_destinations.append(dest_name)
                            upload_logger.error(f"{dest_name} upload failed for {video.filename}")
                    except Exception as e:
                        failed_destinations.append(dest_name)
                        upload_logger.error(f"{dest_name} upload exception for {video.filename}: {str(e)}")
                        video_dict['error'] = str(e)
            
            # Determine final status based on results
            update_data = {}
            if len(succeeded_destinations) == len(enabled_destinations):
                update_data['status'] = 'uploaded'
                if 'error' in video_dict:
                    update_data['error'] = None
            elif len(succeeded_destinations) > 0:
                update_data['status'] = 'failed'
                update_data['error'] = f"Partial upload: succeeded ({', '.join(succeeded_destinations)}), failed ({', '.join(failed_destinations)})"
            else:
                update_data['status'] = 'failed'
                if 'error' not in video_dict or not video_dict['error']:
                    update_data['error'] = f"Upload failed for all destinations: {', '.join(failed_destinations)}"
            
            # Update any additional fields that might have been set by uploaders
            for key in ['youtube_id', 'tiktok_id', 'tiktok_publish_id', 'instagram_id', 'instagram_container_id']:
                if key in video_dict and video_dict[key]:
                    update_data[key] = video_dict[key]
            
            # Update video in database
            db_helpers.update_video(video_id, user_id, **update_data)
        
        # Count videos that are fully uploaded
        user_videos_updated = db_helpers.get_user_videos(user_id)
        uploaded_count = len([v for v in user_videos_updated if v.status == 'uploaded'])
        return {
            "uploaded": uploaded_count,
            "message": f"Videos uploaded immediately to: {', '.join(enabled_destinations)}"
        }
    
    # Otherwise, mark for scheduled upload
    schedule_mode = global_settings.get("schedule_mode", "immediate")
    
    if schedule_mode == 'spaced':
        # Calculate interval in minutes
        value = global_settings.get("schedule_interval_value", 60)
        unit = global_settings.get("schedule_interval_unit", "minutes")
        
        if unit == 'minutes':
            interval_minutes = value
        elif unit == 'hours':
            interval_minutes = value * 60
        elif unit == 'days':
            interval_minutes = value * 1440
        else:
            interval_minutes = 60  # default to 1 hour
        
        # Set scheduled time for each video (use timezone-aware datetime)
        current_time = datetime.now(timezone.utc)
        for i, video in enumerate(pending_videos):
            video_id = video.id
            scheduled_time = current_time + timedelta(minutes=interval_minutes * i)
            db_helpers.update_video(video_id, user_id, scheduled_time=scheduled_time.isoformat(), status="scheduled")
        
        return {
            "scheduled": len(pending_videos),
            "message": f"Videos scheduled with {value} {unit} interval"
        }
    
    elif schedule_mode == 'specific_time':
        # Schedule all for a specific time
        schedule_start_time = global_settings.get("schedule_start_time")
        if schedule_start_time:
            for video in pending_videos:
                video_id = video.id
                db_helpers.update_video(video_id, user_id, scheduled_time=schedule_start_time, status="scheduled")
            
            return {
                "scheduled": len(pending_videos),
                "message": f"Videos scheduled for {schedule_start_time}"
            }
        else:
            raise HTTPException(400, "No start time specified for scheduled upload")
    
    return {"message": "Upload processing"}

@app.get("/terms", response_class=HTMLResponse)
def terms_of_service():
    """Terms of Service page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Terms of Service</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 2rem;
                line-height: 1.6;
                color: #333;
            }
            h1 {
                color: #222;
                border-bottom: 2px solid #eee;
                padding-bottom: 0.5rem;
            }
            h2 {
                color: #444;
                margin-top: 2rem;
            }
            p {
                margin: 1rem 0;
            }
            a {
                color: #0066cc;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>Terms of Service</h1>
        <p><strong>Last updated:</strong> {date}</p>
        
        <h2>1. Acceptance of Terms</h2>
        <p>By accessing and using this service, you accept and agree to be bound by these Terms of Service.</p>
        
        <h2>2. Use of Service</h2>
        <p>You agree to use this service only for lawful purposes and in accordance with these Terms. You are responsible for all content you upload or transmit through the service.</p>
        
        <h2>3. User Responsibilities</h2>
        <p>You are responsible for maintaining the confidentiality of your account credentials and for all activities that occur under your account.</p>
        
        <h2>4. Limitation of Liability</h2>
        <p>The service is provided "as is" without warranties of any kind. We are not liable for any damages arising from your use of the service.</p>
        
        <h2>5. Changes to Terms</h2>
        <p>We reserve the right to modify these Terms at any time. Continued use of the service after changes constitutes acceptance of the modified Terms.</p>
        
        <p><a href="/privacy">Privacy Policy</a> | <a href="/">Home</a></p>
    </body>
    </html>
    """.format(date=datetime.now().strftime("%B %d, %Y"))

@app.get("/privacy", response_class=HTMLResponse)
def privacy_policy():
    """Privacy Policy page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Privacy Policy</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 2rem;
                line-height: 1.6;
                color: #333;
            }
            h1 {
                color: #222;
                border-bottom: 2px solid #eee;
                padding-bottom: 0.5rem;
            }
            h2 {
                color: #444;
                margin-top: 2rem;
            }
            p {
                margin: 1rem 0;
            }
            a {
                color: #0066cc;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>Privacy Policy</h1>
        <p><strong>Last updated:</strong> {date}</p>
        
        <h2>1. Information We Collect</h2>
        <p>We collect information you provide directly to us, including account credentials and content you upload. We also collect usage data and technical information automatically when you use the service.</p>
        
        <h2>2. How We Use Information</h2>
        <p>We use the information we collect to provide, maintain, and improve our services, process your requests, and communicate with you.</p>
        
        <h2>3. Information Sharing</h2>
        <p>We do not sell your personal information. We may share information with third-party service providers who assist us in operating our service, subject to confidentiality obligations.</p>
        
        <h2>4. Data Security</h2>
        <p>We implement appropriate technical and organizational measures to protect your information. However, no method of transmission over the internet is 100% secure.</p>
        
        <h2>5. Your Rights</h2>
        <p>You have the right to access, update, or delete your personal information. You may also opt out of certain data collection practices.</p>
        
        <h2>6. Changes to Privacy Policy</h2>
        <p>We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page.</p>
        
        <p><a href="/terms">Terms of Service</a> | <a href="/">Home</a></p>
    </body>
    </html>
    """.format(date=datetime.now().strftime("%B %d, %Y"))

if __name__ == "__main__":
    # Use reload=True in development for hot reload
    # Must pass app as import string for reload to work
    reload = os.getenv("ENVIRONMENT", "development") == "development"
    if reload:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)

