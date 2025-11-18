from urllib.parse import urlencode, unquote
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path
import uvicorn
import os
import asyncio
import json
import secrets
import random
import re
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

# Get domain from environment or default to localhost for development
DOMAIN = os.getenv("DOMAIN", "localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# OAuth Credentials from environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")

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

# CORS - allow production domain or all origins for development
if ENVIRONMENT == "production":
    allowed_origins = [FRONTEND_URL]
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage
UPLOAD_DIR = Path("uploads")
SESSIONS_DIR = Path("sessions")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Directory already exists or mounted

# Session storage: {session_id: {youtube_creds, videos, youtube_settings, upload_progress}}
sessions = {}

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

def get_default_global_settings():
    """Return default global settings"""
    return {
        "title_template": "{filename}",
        "description_template": "Uploaded via Hopper",
        "wordbank": []
    }

def get_default_youtube_settings():
    """Return default YouTube-specific settings"""
    return {
        "visibility": "private",
        "made_for_kids": False,
        "tags_template": "",
        "title_template": "",  # Empty means use global
        "description_template": "",  # Empty means use global
        "upload_immediately": True,
        "schedule_mode": "spaced",
        "schedule_interval_value": 1,
        "schedule_interval_unit": "hours",
        "schedule_start_time": "",
        "allow_duplicates": False
    }

def get_default_tiktok_settings():
    """Return default TikTok-specific settings"""
    return {
        "privacy_level": "private",  # private, friends, public
        "allow_comments": True,
        "allow_duet": True,
        "allow_stitch": True,
        "title_template": "",  # Empty means use global
        "description_template": "",  # Empty means use global (TikTok combines title+description)
        "upload_immediately": True,
        "schedule_mode": "spaced",
        "schedule_interval_value": 1,
        "schedule_interval_unit": "hours",
        "schedule_start_time": "",
        "allow_duplicates": False
    }

def get_session(session_id: str):
    """Get or create a session"""
    if session_id not in sessions:
        sessions[session_id] = {
            "youtube_creds": None,
            "tiktok_creds": None,
            "videos": [],
            "global_settings": get_default_global_settings(),
            "youtube_settings": get_default_youtube_settings(),
            "tiktok_settings": get_default_tiktok_settings(),
            "upload_progress": {},
            "destinations": {
                "youtube": {
                    "enabled": False
                },
                "tiktok": {
                    "enabled": False
                }
            }
        }
        # Try to load from disk
        load_session(session_id)
    
    return sessions[session_id]

def save_session(session_id: str):
    """Save session to disk"""
    if session_id not in sessions:
        return
    
    session_data = sessions[session_id].copy()
    
    # Convert Credentials object to dict for JSON serialization
    if session_data["youtube_creds"]:
        creds = session_data["youtube_creds"]
        session_data["youtube_creds"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
    
    session_file = SESSIONS_DIR / f"{session_id}.json"
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
    except Exception as e:
        print(f"Error saving session: {e}")

def load_session(session_id: str):
    """Load session from disk"""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return
    
    try:
        with open(session_file, 'r') as f:
            session_data = json.load(f)
        
        # Convert credentials dict back to Credentials object
        if session_data.get("youtube_creds"):
            creds_data = session_data["youtube_creds"]
            # For old sessions that might be missing fields, use env vars as fallback
            # New sessions will always have these fields from the OAuth callback
            client_id = creds_data.get("client_id") or GOOGLE_CLIENT_ID
            client_secret = creds_data.get("client_secret") or GOOGLE_CLIENT_SECRET
            token_uri = creds_data.get("token_uri") or "https://oauth2.googleapis.com/token"
            
            # Construct Credentials object with all required fields
            # For old sessions missing fields, use env vars (they'll be saved on next save_session call)
            session_data["youtube_creds"] = Credentials(
                token=creds_data.get("token"),
                refresh_token=creds_data.get("refresh_token"),
                token_uri=token_uri,
                client_id=client_id,
                client_secret=client_secret,
                scopes=creds_data.get("scopes")
            )
            
            # If old session was missing fields, update the session file now
            if not creds_data.get("client_id") or not creds_data.get("client_secret"):
                creds_data["client_id"] = client_id
                creds_data["client_secret"] = client_secret
                creds_data["token_uri"] = token_uri
                # Save immediately to fix the session file
                try:
                    with open(SESSIONS_DIR / f"{session_id}.json", 'w') as f:
                        json.dump(session_data, f, indent=2)
                except Exception as e:
                    print(f"[Session Load] Failed to update session file: {e}")
        
        # Backwards compatibility: add destinations if missing
        if "destinations" not in session_data:
            session_data["destinations"] = {
                "youtube": {
                    "enabled": False
                },
                "tiktok": {
                    "enabled": False
                }
            }
        
        # Add tiktok if missing from old sessions
        if "tiktok" not in session_data["destinations"]:
            session_data["destinations"]["tiktok"] = {"enabled": False}
        
        # Add tiktok_creds if missing
        if "tiktok_creds" not in session_data:
            session_data["tiktok_creds"] = None
        
        # Add tiktok_settings if missing
        if "tiktok_settings" not in session_data:
            session_data["tiktok_settings"] = get_default_tiktok_settings()
        
        # Ensure all required fields exist
        if "upload_progress" not in session_data:
            session_data["upload_progress"] = {}
        
        # Migrate old sessions to new structure
        if "youtube_settings" not in session_data:
            session_data["youtube_settings"] = get_default_youtube_settings()
        if "global_settings" not in session_data:
            # Migrate from old structure: move global fields from youtube_settings to global_settings
            session_data["global_settings"] = {
                "title_template": session_data["youtube_settings"].get("title_template", "{filename}"),
                "description_template": session_data["youtube_settings"].get("description_template", "Uploaded via Hopper"),
                "wordbank": session_data["youtube_settings"].get("wordbank", [])
            }
            # Clear these from youtube_settings so they use global by default
            session_data["youtube_settings"]["title_template"] = ""
            session_data["youtube_settings"]["description_template"] = ""
            if "wordbank" in session_data["youtube_settings"]:
                del session_data["youtube_settings"]["wordbank"]
        
        # Add missing settings for backwards compatibility
        if "allow_duplicates" not in session_data["youtube_settings"]:
            session_data["youtube_settings"]["allow_duplicates"] = False
        if "tags_template" not in session_data["youtube_settings"]:
            session_data["youtube_settings"]["tags_template"] = ""
        
        sessions[session_id] = session_data
        print(f"Loaded session {session_id}")
    except Exception as e:
        print(f"Error loading session: {e}")

def get_or_create_session_id(request: Request, response: Response) -> str:
    """Get existing session ID from cookie or create new one"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,  # 30 days
            samesite="lax"
        )
    return session_id

@app.get("/api/auth/youtube")
def auth_youtube(request: Request, response: Response):
    """Start YouTube OAuth"""
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
    # Ensure session exists
    session_id = get_or_create_session_id(request, response)
    
    # Build redirect URI dynamically based on request
    # Check for HTTPS from cloudflared (X-Forwarded-Proto) or use environment
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
    # Remove port if present (cloudflared doesn't expose ports)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/youtube/callback"
    
    # Create Flow from config dict instead of file
    flow = Flow.from_client_config(
        google_config,
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    # Store session_id in state parameter
    url, state = flow.authorization_url(access_type='offline', state=session_id)
    return {"url": url}

@app.get("/api/auth/youtube/callback")
def auth_callback(code: str, state: str, request: Request, response: Response):
    """OAuth callback"""
    # Get session from state parameter
    session_id = state
    session = get_session(session_id)
    
    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=30*24*60*60,
        samesite="lax"
    )
    
    # Build redirect URI dynamically
    # Check for HTTPS from cloudflared (X-Forwarded-Proto) or use environment
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
    # Remove port if present (cloudflared doesn't expose ports)
    if ":" in host:
        host = host.split(":")[0]
    redirect_uri = f"{protocol}://{host}/api/auth/youtube/callback"
    
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured")
    
    flow = Flow.from_client_config(
        google_config,
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    flow.fetch_token(code=code)
    
    # Create a complete Credentials object with all required fields for token refresh
    # The flow.credentials might not have client_id/client_secret, so we construct it properly
    flow_creds = flow.credentials
    session["youtube_creds"] = Credentials(
        token=flow_creds.token,
        refresh_token=flow_creds.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=flow_creds.scopes
    )
    save_session(session_id)
    
    # Redirect back to frontend using environment variable or construct from request
    if ENVIRONMENT == "production":
        frontend_url = f"{FRONTEND_URL}?connected=youtube"
    else:
        # Development: use request host and replace port
        host = request.headers.get("host", "localhost:8000")
        frontend_url = f"http://{host.replace(':8000', ':3000')}?connected=youtube"
    return RedirectResponse(frontend_url)

@app.get("/api/destinations")
def get_destinations(request: Request, response: Response):
    """Get destination status"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    scheduled_count = len([v for v in session["videos"] if v['status'] == 'scheduled'])
    return {
        "youtube": {
            "connected": session["youtube_creds"] is not None,
            "enabled": session["destinations"]["youtube"]["enabled"]
        },
        "tiktok": {
            "connected": session["tiktok_creds"] is not None,
            "enabled": session["destinations"]["tiktok"]["enabled"]
        },
        "scheduled_videos": scheduled_count
    }

@app.post("/api/global/wordbank")
def add_wordbank_word(request: Request, response: Response, word: str):
    """Add a word to the global wordbank"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Strip whitespace and capitalize (first letter uppercase, rest lowercase)
    word = word.strip().capitalize()
    if not word:
        raise HTTPException(400, "Word cannot be empty")
    
    if word not in session["global_settings"]["wordbank"]:
        session["global_settings"]["wordbank"].append(word)
        save_session(session_id)
    
    return {"wordbank": session["global_settings"]["wordbank"]}

@app.delete("/api/global/wordbank/{word}")
def remove_wordbank_word(request: Request, response: Response, word: str):
    """Remove a word from the global wordbank"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    if word in session["global_settings"]["wordbank"]:
        session["global_settings"]["wordbank"].remove(word)
        save_session(session_id)
    
    return {"wordbank": session["global_settings"]["wordbank"]}

@app.delete("/api/global/wordbank")
def clear_wordbank(request: Request, response: Response):
    """Clear all words from the global wordbank"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["global_settings"]["wordbank"] = []
    save_session(session_id)
    
    return {"wordbank": []}

@app.post("/api/destinations/youtube/toggle")
def toggle_youtube(request: Request, response: Response, enabled: bool):
    """Toggle YouTube destination on/off"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["destinations"]["youtube"]["enabled"] = enabled
    save_session(session_id)
    
    return {
        "youtube": {
            "connected": session["youtube_creds"] is not None,
            "enabled": session["destinations"]["youtube"]["enabled"]
        }
    }

@app.post("/api/destinations/tiktok/toggle")
def toggle_tiktok(request: Request, response: Response, enabled: bool):
    """Toggle TikTok destination on/off"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["destinations"]["tiktok"]["enabled"] = enabled
    save_session(session_id)
    
    return {
        "tiktok": {
            "connected": session["tiktok_creds"] is not None,
            "enabled": session["destinations"]["tiktok"]["enabled"]
        }
    }

@app.post("/api/auth/youtube/disconnect")
def disconnect_youtube(request: Request, response: Response):
    """Disconnect YouTube account"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["youtube_creds"] = None
    session["destinations"]["youtube"]["enabled"] = False
    save_session(session_id)
    return {"message": "Disconnected"}

@app.get("/api/auth/tiktok")
def auth_tiktok(request: Request, response: Response):
    """Initiate TikTok OAuth flow"""
    
    # Validate configuration
    if not TIKTOK_CLIENT_KEY:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing TIKTOK_CLIENT_KEY."
        )
    
    # Get or create session
    session_id = get_or_create_session_id(request, response)
    
    # Generate CSRF token (using session_id for state)
    state = session_id
    
    # Build redirect URI (must match TikTok Developer Portal exactly)
    # Ensure no trailing slash and proper URL format
    # This must match EXACTLY in the token exchange request
    redirect_uri = f"{BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
    
    # Build scope string (comma-separated, no spaces)
    scope_string = ",".join(TIKTOK_SCOPES)
    
    # Build authorization URL with proper encoding
    params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": scope_string,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    
    # Use urlencode with doseq=False (default) to properly encode all params
    query_string = urlencode(params, doseq=False)
    auth_url = f"{TIKTOK_AUTH_URL}?{query_string}"
    
    # Debug logging
    print(f"[TikTok OAuth] Initiating auth flow")
    print(f"  Client Key: {TIKTOK_CLIENT_KEY[:4]}...{TIKTOK_CLIENT_KEY[-4:]}")
    print(f"  Redirect URI: {redirect_uri}")
    print(f"  Scope: {scope_string}")
    print(f"  State: {state[:16]}...")
    print(f"  Full Auth URL: {auth_url}")
    
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
    
    print(f"[TikTok Callback] Received callback")
    print(f"  Code: {'present' if code else 'MISSING'}")
    print(f"  State: {state[:16] + '...' if state else 'MISSING'}")
    print(f"  Error: {error or 'none'}")
    
    # Check for errors from TikTok
    if error:
        error_msg = f"TikTok OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        print(f"  ERROR: {error_msg}")
        # Redirect to frontend with error
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate required parameters
    if not code or not state:
        print("  ERROR: Missing code or state")
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")
    
    # Validate configuration
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="TikTok OAuth not configured. Missing credentials."
        )
    
    # Validate state (CSRF protection)
    session_id = state
    session = get_session(session_id)
    
    try:
        # Exchange authorization code for access token
        # IMPORTANT: redirect_uri must match EXACTLY what was used in auth request
        # Ensure no trailing slash on BACKEND_URL
        redirect_uri = f"{BACKEND_URL.rstrip('/')}/api/auth/tiktok/callback"
        
        # URL decode the code if needed (FastAPI should do this, but be explicit)
        decoded_code = unquote(code) if code else None
        
        token_data = {
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "code": decoded_code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        
        print(f"  Exchanging code for token...")
        print(f"  Token URL: {TIKTOK_TOKEN_URL}")
        print(f"  Redirect URI: {redirect_uri}")
        print(f"  Client Key: {TIKTOK_CLIENT_KEY[:4]}...{TIKTOK_CLIENT_KEY[-4:]}")
        
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                TIKTOK_TOKEN_URL,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            print(f"  Token response status: {token_response.status_code}")
            print(f"  Token response headers: {dict(token_response.headers)}")
            
            if token_response.status_code != 200:
                error_text = token_response.text
                print(f"  Token exchange failed: {error_text}")
                print(f"  Full response: {error_text[:500]}")
                return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_token_failed")
            
            token_json = token_response.json()
            
            # Validate response
            if "access_token" not in token_json:
                print(f"  ERROR: No access_token in response")
                return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_token_failed")
            
            print(f"  Token exchange successful!")
            print(f"  Open ID: {token_json.get('open_id', 'N/A')}")
            print(f"  Expires in: {token_json.get('expires_in', 'N/A')} seconds")
            
            # Store credentials in session
            session["tiktok_creds"] = {
                "access_token": token_json["access_token"],
                "refresh_token": token_json.get("refresh_token"),
                "expires_in": token_json.get("expires_in"),
                "refresh_expires_in": token_json.get("refresh_expires_in"),
                "token_type": token_json.get("token_type"),
                "open_id": token_json.get("open_id"),
                "scope": token_json.get("scope"),
            }
            
            session["destinations"]["tiktok"]["enabled"] = True
            save_session(session_id)
            
            # Set session cookie
            response.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                max_age=30*24*60*60,  # 30 days
                samesite="lax"
            )
            
            print(f"  Session saved: {session_id[:16]}...")
            
            # Redirect to frontend with success
            return RedirectResponse(f"{FRONTEND_URL}?connected=tiktok")
            
    except Exception as e:
        print(f"[TikTok Callback] Exception: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")


@app.post("/api/auth/tiktok/disconnect")
def disconnect_tiktok(request: Request, response: Response):
    """Disconnect TikTok account"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["tiktok_creds"] = None
    session["destinations"]["tiktok"]["enabled"] = False
    save_session(session_id)
    
    print(f"[TikTok] Disconnected session: {session_id[:16]}...")
    
    return {"message": "TikTok disconnected successfully"}


# Helper: Refresh TikTok access token
async def refresh_tiktok_token(session_id: str) -> dict:
    """Refresh TikTok access token using refresh token"""
    session = get_session(session_id)
    creds = session.get("tiktok_creds")
    
    if not creds or not creds.get("refresh_token"):
        raise HTTPException(400, "No TikTok credentials to refresh")
    
    refresh_data = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TIKTOK_TOKEN_URL,
            data=refresh_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code != 200:
            raise HTTPException(400, f"Token refresh failed: {response.text}")
        
        token_json = response.json()
        
        # Update session with new tokens
        session["tiktok_creds"].update({
            "access_token": token_json["access_token"],
            "refresh_token": token_json.get("refresh_token", creds["refresh_token"]),
            "expires_in": token_json.get("expires_in"),
        })
        save_session(session_id)
        
        return session["tiktok_creds"]

@app.get("/api/global/settings")
def get_global_settings(request: Request, response: Response):
    """Get global settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    return session["global_settings"]

@app.post("/api/global/settings")
def update_global_settings(
    request: Request,
    response: Response,
    title_template: str = None,
    description_template: str = None
):
    """Update global settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    settings = session["global_settings"]
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        settings["title_template"] = title_template
    
    if description_template is not None:
        settings["description_template"] = description_template
    
    save_session(session_id)
    return settings

@app.get("/api/youtube/settings")
def get_youtube_settings(request: Request, response: Response):
    """Get YouTube upload settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    return session["youtube_settings"]

@app.post("/api/youtube/settings")
def update_youtube_settings(
    request: Request,
    response: Response,
    visibility: str = None, 
    made_for_kids: bool = None,
    title_template: str = None,
    description_template: str = None,
    tags_template: str = None,
    upload_immediately: bool = None,
    schedule_mode: str = None,
    schedule_interval_value: int = None,
    schedule_interval_unit: str = None,
    schedule_start_time: str = None,
    allow_duplicates: bool = None
):
    """Update YouTube upload settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    settings = session["youtube_settings"]
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        settings["visibility"] = visibility
    
    if made_for_kids is not None:
        settings["made_for_kids"] = made_for_kids
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        settings["title_template"] = title_template
    
    if description_template is not None:
        settings["description_template"] = description_template
    
    if tags_template is not None:
        settings["tags_template"] = tags_template
    
    if upload_immediately is not None:
        settings["upload_immediately"] = upload_immediately
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        settings["schedule_mode"] = schedule_mode
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        settings["schedule_interval_value"] = schedule_interval_value
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        settings["schedule_interval_unit"] = schedule_interval_unit
    
    if schedule_start_time is not None:
        settings["schedule_start_time"] = schedule_start_time
    
    if allow_duplicates is not None:
        settings["allow_duplicates"] = allow_duplicates
    
    save_session(session_id)
    return settings

# TikTok settings endpoints
@app.get("/api/tiktok/settings")
def get_tiktok_settings(request: Request, response: Response):
    """Get TikTok upload settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    return session["tiktok_settings"]

@app.post("/api/tiktok/settings")
def update_tiktok_settings(
    request: Request,
    response: Response,
    privacy_level: str = None,
    allow_comments: bool = None,
    allow_duet: bool = None,
    allow_stitch: bool = None,
    title_template: str = None,
    description_template: str = None,
    upload_immediately: bool = None,
    schedule_mode: str = None,
    schedule_interval_value: int = None,
    schedule_interval_unit: str = None,
    schedule_start_time: str = None,
    allow_duplicates: bool = None
):
    """Update TikTok upload settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    settings = session["tiktok_settings"]
    
    if privacy_level is not None:
        if privacy_level not in ["public", "private", "friends"]:
            raise HTTPException(400, "Invalid privacy level")
        settings["privacy_level"] = privacy_level
    
    if allow_comments is not None:
        settings["allow_comments"] = allow_comments
    
    if allow_duet is not None:
        settings["allow_duet"] = allow_duet
    
    if allow_stitch is not None:
        settings["allow_stitch"] = allow_stitch
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        settings["title_template"] = title_template
    
    if description_template is not None:
        settings["description_template"] = description_template
    
    if upload_immediately is not None:
        settings["upload_immediately"] = upload_immediately
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        settings["schedule_mode"] = schedule_mode
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        settings["schedule_interval_value"] = schedule_interval_value
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        settings["schedule_interval_unit"] = schedule_interval_unit
    
    if schedule_start_time is not None:
        settings["schedule_start_time"] = schedule_start_time
    
    if allow_duplicates is not None:
        settings["allow_duplicates"] = allow_duplicates
    
    save_session(session_id)
    return settings

@app.post("/api/videos")
async def add_video(file: UploadFile = File(...), request: Request = None, response: Response = None):
    """Add video to queue"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Check for duplicates if not allowed
    if not session["youtube_settings"].get("allow_duplicates", False):
        existing_filenames = [v["filename"] for v in session["videos"]]
        if file.filename in existing_filenames:
            raise HTTPException(400, f"Duplicate video: {file.filename} is already in the queue")
    
    path = UPLOAD_DIR / file.filename
    
    with open(path, "wb") as f:
        f.write(await file.read())
    
    # Generate YouTube title once when video is added
    # Priority: YouTube-specific template > Global template
    filename_no_ext = file.filename.rsplit('.', 1)[0]
    title_template = session["youtube_settings"].get('title_template', '') or session["global_settings"]['title_template']
    youtube_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        session["global_settings"].get('wordbank', [])
    )
    
    video = {
        "id": len(session["videos"]) + 1,
        "filename": file.filename,
        "path": str(path),
        "status": "pending",
        "generated_title": youtube_title  # Store the generated title
    }
    session["videos"].append(video)
    save_session(session_id)
    return video

@app.get("/api/videos")
def get_videos(request: Request, response: Response):
    """Get video queue with progress and computed titles"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Add progress info and computed YouTube titles to videos
    videos_with_info = []
    for video in session["videos"]:
        video_copy = video.copy()
        
        # Add upload progress if available
        if video['id'] in session["upload_progress"]:
            video_copy['upload_progress'] = session["upload_progress"][video['id']]
        
        # Compute YouTube title - Priority: custom > generated_title > destination > global
        custom_settings = video.get('custom_settings', {})
        if 'title' in custom_settings:
            # User has set a custom title - use it
            youtube_title = custom_settings['title']
        elif 'generated_title' in video:
            # Use the title that was generated when video was added
            youtube_title = video['generated_title']
        else:
            # Fallback for old videos without generated_title (backwards compatibility)
            # Priority: YouTube-specific template > Global template
            filename_no_ext = video['filename'].rsplit('.', 1)[0]
            title_template = session["youtube_settings"].get('title_template', '') or session["global_settings"]['title_template']
            youtube_title = replace_template_placeholders(
                title_template,
                filename_no_ext,
                session["global_settings"].get('wordbank', [])
            )
        
        # Enforce YouTube's 100 character limit
        video_copy['youtube_title'] = youtube_title[:100] if len(youtube_title) > 100 else youtube_title
        video_copy['title_too_long'] = len(youtube_title) > 100
        video_copy['title_original_length'] = len(youtube_title)
        
        videos_with_info.append(video_copy)
    return videos_with_info

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, request: Request, response: Response):
    """Remove from queue"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["videos"] = [v for v in session["videos"] if v['id'] != video_id]
    save_session(session_id)
    return {"ok": True}

@app.patch("/api/videos/{video_id}")
def update_video(
    video_id: int,
    request: Request,
    response: Response,
    title: str = None,
    description: str = None,
    tags: str = None,
    visibility: str = None,
    made_for_kids: bool = None,
    scheduled_time: str = None
):
    """Update video settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Find the video
    video = None
    for v in session["videos"]:
        if v['id'] == video_id:
            video = v
            break
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Update custom settings (these override global settings)
    if "custom_settings" not in video:
        video["custom_settings"] = {}
    
    if title is not None:
        if len(title) > 100:
            raise HTTPException(400, "Title must be 100 characters or less")
        video["custom_settings"]["title"] = title
    
    if description is not None:
        video["custom_settings"]["description"] = description
    
    if tags is not None:
        video["custom_settings"]["tags"] = tags
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        video["custom_settings"]["visibility"] = visibility
    
    if made_for_kids is not None:
        video["custom_settings"]["made_for_kids"] = made_for_kids
    
    # Handle scheduled_time - can be set or cleared
    if 'scheduled_time' in request.query_params:
        if scheduled_time:  # If it has a value, set the schedule
            video["scheduled_time"] = scheduled_time
            if video["status"] == "pending":
                video["status"] = "scheduled"
        else:  # If empty or null, clear the schedule
            if "scheduled_time" in video:
                del video["scheduled_time"]
            if video["status"] == "scheduled":
                video["status"] = "pending"
    
    save_session(session_id)
    return video

@app.post("/api/videos/reorder")
async def reorder_videos(request: Request, response: Response):
    """Reorder videos in the queue"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    try:
        # Parse JSON body
        body = await request.json()
        video_ids = body.get("video_ids", [])
        
        if not video_ids:
            raise HTTPException(400, "video_ids required")
        
        # Create a mapping of video IDs to video objects
        video_map = {v['id']: v for v in session["videos"]}
        
        # Reorder videos based on the provided IDs
        reordered_videos = []
        for vid in video_ids:
            if vid in video_map:
                reordered_videos.append(video_map[vid])
        
        # Add any videos that weren't in the reorder list (shouldn't happen, but safety)
        for video in session["videos"]:
            if video not in reordered_videos:
                reordered_videos.append(video)
        
        session["videos"] = reordered_videos
        save_session(session_id)
        
        return {"ok": True, "count": len(reordered_videos)}
    except Exception as e:
        print(f"Error reordering videos: {e}")
        raise HTTPException(500, f"Error reordering videos: {str(e)}")

@app.post("/api/videos/cancel-scheduled")
def cancel_scheduled_videos(request: Request, response: Response):
    """Cancel all scheduled videos and return them to pending status"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    cancelled_count = 0
    for video in session["videos"]:
        if video['status'] == 'scheduled':
            video['status'] = 'pending'
            if 'scheduled_time' in video:
                del video['scheduled_time']
            cancelled_count += 1
    
    save_session(session_id)
    
    return {"ok": True, "cancelled": cancelled_count}

# Destination upload functions registry
# This allows easy addition of new destinations in the future
DESTINATION_UPLOADERS = {
    "youtube": None,  # Will be set below
    "tiktok": None,   # Will be set below
}

def upload_video_to_youtube(video, session):
    """Helper function to upload a single video to YouTube"""
    youtube_creds = session["youtube_creds"]
    youtube_settings = session["youtube_settings"]
    upload_progress = session["upload_progress"]
    
    print(f"[YouTube Upload] Starting upload for {video['filename']}")
    
    if not youtube_creds:
        video['status'] = 'failed'
        video['error'] = 'No YouTube credentials'
        print(f"[YouTube Upload] ERROR: No YouTube credentials")
        return
    
    # Credentials should always be complete (fixed in load_session if old session)
    if not youtube_creds.client_id or not youtube_creds.client_secret or not youtube_creds.token_uri:
        video['status'] = 'failed'
        error_msg = 'YouTube credentials are incomplete. Please disconnect and reconnect YouTube.'
        video['error'] = error_msg
        print(f"[YouTube Upload] ERROR: {error_msg}")
        return
    
    try:
        video['status'] = 'uploading'
        upload_progress[video['id']] = 0
        
        print(f"[YouTube Upload] Building YouTube API client...")
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
        
        print(f"[YouTube Upload] Preparing upload request...")
        print(f"  Title: {title[:50]}...")
        print(f"  Visibility: {visibility}")
        print(f"  Video path: {video['path']}")
        
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
        
        print(f"[YouTube Upload] Starting resumable upload...")
        response = None
        chunk_count = 0
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                upload_progress[video['id']] = progress
                chunk_count += 1
                if chunk_count % 10 == 0 or progress == 100:  # Log every 10 chunks or at completion
                    print(f"[YouTube Upload] Progress: {progress}%")
        
        video['status'] = 'uploaded'
        video['youtube_id'] = response['id']
        upload_progress[video['id']] = 100
        print(f"[YouTube Upload] Successfully uploaded {video['filename']}, YouTube ID: {response['id']}")
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = str(e)
        print(f"[YouTube Upload] ERROR uploading {video['filename']}: {str(e)}")
        import traceback
        print(f"[YouTube Upload] Traceback: {traceback.format_exc()}")
        if video['id'] in upload_progress:
            del upload_progress[video['id']]

def check_tiktok_rate_limit(session_id):
    """Check if TikTok API rate limit is exceeded (6 requests per minute)"""
    import time
    current_time = time.time()
    
    if session_id not in tiktok_rate_limiter:
        tiktok_rate_limiter[session_id] = []
    
    # Remove timestamps older than the rate limit window
    tiktok_rate_limiter[session_id] = [
        ts for ts in tiktok_rate_limiter[session_id]
        if current_time - ts < TIKTOK_RATE_LIMIT_WINDOW
    ]
    
    # Check if we've exceeded the limit
    if len(tiktok_rate_limiter[session_id]) >= TIKTOK_RATE_LIMIT_REQUESTS:
        oldest_request = min(tiktok_rate_limiter[session_id])
        wait_time = TIKTOK_RATE_LIMIT_WINDOW - (current_time - oldest_request)
        raise Exception(f"TikTok rate limit exceeded. Wait {int(wait_time)} seconds before trying again.")
    
    # Record this request
    tiktok_rate_limiter[session_id].append(current_time)

def get_tiktok_creator_info(session):
    """Query TikTok creator info and cache it in session"""
    tiktok_creds = session.get("tiktok_creds")
    if not tiktok_creds:
        raise Exception("No TikTok credentials")
    
    access_token = tiktok_creds.get("access_token")
    if not access_token:
        raise Exception("No TikTok access token")
    
    # Check if we have cached creator info
    if "tiktok_creator_info" in session and session["tiktok_creator_info"]:
        return session["tiktok_creator_info"]
    
    # Query creator info
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8"
    }
    
    response = httpx.post(TIKTOK_CREATOR_INFO_URL, headers=headers, json={}, timeout=30.0)
    
    if response.status_code != 200:
        error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        error_code = error_data.get("error", {}).get("code", "unknown")
        error_msg = error_data.get("error", {}).get("message", response.text)
        raise Exception(f"Failed to query creator info: {error_code} - {error_msg}")
    
    creator_info = response.json()
    
    # Cache it in session
    session["tiktok_creator_info"] = creator_info.get("data", {})
    
    return session["tiktok_creator_info"]

def map_privacy_level_to_tiktok(privacy_level, creator_info):
    """Map our privacy level to TikTok's format"""
    # Get available privacy options from creator info
    available_options = creator_info.get("privacy_level_options", [])
    
    # Mapping
    mapping = {
        "public": "PUBLIC_TO_EVERYONE",
        "private": "SELF_ONLY",
        "friends": "MUTUAL_FOLLOW_FRIENDS"
    }
    
    tiktok_privacy = mapping.get(privacy_level, "PUBLIC_TO_EVERYONE")
    
    # Verify it's available, fallback to first available option
    if tiktok_privacy not in available_options and available_options:
        tiktok_privacy = available_options[0]
    elif not available_options:
        # Default if no options available
        tiktok_privacy = "PUBLIC_TO_EVERYONE"
    
    return tiktok_privacy

def upload_video_to_tiktok(video, session, session_id=None):
    """
    Upload video to TikTok using Content Posting API - Direct Post flow:
    1. Initialize the posting request
    2. Upload video file
    3. Check status (done separately)
    """
    tiktok_creds = session.get("tiktok_creds")
    tiktok_settings = session.get("tiktok_settings", {})
    upload_progress = session["upload_progress"]
    
    if not session_id:
        for sid, sess in sessions.items():
            if sess == session:
                session_id = sid
                break
        if not session_id:
            session_id = "unknown"
    
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
        
        # Prepare metadata
        custom_settings = video.get('custom_settings', {})
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        
        # Get title
        if 'title' in custom_settings:
            title = custom_settings['title']
        elif 'generated_title' in video:
            title = video['generated_title']
        else:
            global_settings = session.get("global_settings", {})
            title_template = tiktok_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            title = replace_template_placeholders(title_template, filename_no_ext, global_settings.get('wordbank', []))
        
        title = title[:2200]  # TikTok limit
        
        # Get privacy settings
        privacy_level = custom_settings.get('privacy_level', tiktok_settings.get('privacy_level', 'public'))
        tiktok_privacy = map_privacy_level_to_tiktok(privacy_level, creator_info)
        allow_comments = custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', True))
        allow_duet = custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', True))
        allow_stitch = custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', True))
        
        # Get video file
        video_path = Path(video['path'])
        if not video_path.exists():
            raise Exception(f"Video file not found: {video['path']}")
        
        video_size = video_path.stat().st_size
        if video_size == 0:
            raise Exception("Video file is empty")
        
        print(f"[TikTok Upload] Uploading {video['filename']} ({video_size / (1024*1024):.2f} MB)")
        upload_progress[video['id']] = 5
        
        # Step 1: Initialize upload - TikTok recommends chunk_size = video_size for simplicity
        init_body = {
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
                "chunk_size": video_size,  # Single chunk upload
                "total_chunk_count": 1
            }
        }
        
        init_response = httpx.post(
            TIKTOK_INIT_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8"
            },
            json=init_body,
            timeout=30.0
        )
        
        if init_response.status_code != 200:
            error_data = init_response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            raise Exception(f"Init failed: {error_msg}")
        
        init_data = init_response.json()
        publish_id = init_data["data"]["publish_id"]
        upload_url = init_data["data"]["upload_url"]
        
        print(f"[TikTok Upload] Initialized, publish_id: {publish_id}")
        upload_progress[video['id']] = 10
        
        # Step 2: Upload video file (single PUT request)
        print(f"[TikTok Upload] Uploading video...")
        
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        # Determine content type
        file_ext = video['filename'].rsplit('.', 1)[-1].lower()
        content_type = {'mp4': 'video/mp4', 'mov': 'video/quicktime', 'webm': 'video/webm'}.get(file_ext, 'video/mp4')
        
        upload_response = httpx.put(
            upload_url,
            headers={
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                "Content-Type": content_type
            },
            content=video_data,
            timeout=300.0
        )
        
        if upload_response.status_code not in [200, 201]:
            raise Exception(f"Upload failed: {upload_response.status_code} - {upload_response.text}")
        
        upload_progress[video['id']] = 100
        
        # Store for status checking
        video['tiktok_publish_id'] = publish_id
        video['status'] = 'uploaded'
        video['tiktok_id'] = publish_id
        
        print(f"[TikTok Upload] Success! publish_id: {publish_id}")
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = f'TikTok upload failed: {str(e)}'
        print(f"[TikTok Upload] Error: {str(e)}")
        if video['id'] in upload_progress:
            del upload_progress[video['id']]

            
# Register upload functions
DESTINATION_UPLOADERS["youtube"] = upload_video_to_youtube
DESTINATION_UPLOADERS["tiktok"] = upload_video_to_tiktok

async def scheduler_task():
    """Background task that checks for scheduled videos and uploads them to all enabled destinations"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = datetime.now(timezone.utc)
            
            # Check all sessions for scheduled videos
            for session_id, session in list(sessions.items()):
                for video in session["videos"]:
                    if video['status'] == 'scheduled' and 'scheduled_time' in video:
                        try:
                            scheduled_time = datetime.fromisoformat(video['scheduled_time'])
                            
                            # If scheduled time has passed, upload the video to all enabled destinations
                            if current_time >= scheduled_time:
                                print(f"Uploading scheduled video for session {session_id}: {video['filename']}")
                                
                                # Upload to all enabled destinations
                                destinations = session.get("destinations", {})
                                for dest_name, uploader_func in DESTINATION_UPLOADERS.items():
                                    if uploader_func and destinations.get(dest_name, {}).get("enabled", False):
                                        # Check if credentials exist for this destination
                                        creds_key = f"{dest_name}_creds"
                                        if session.get(creds_key):
                                            print(f"  Uploading to {dest_name}...")
                                            # Pass session_id for TikTok rate limiting
                                            if dest_name == "tiktok":
                                                uploader_func(video, session, session_id)
                                            else:
                                                uploader_func(video, session)
                                
                                save_session(session_id)
                        except Exception as e:
                            print(f"Error processing scheduled video {video['filename']}: {e}")
                            video['status'] = 'failed'
                            video['error'] = str(e)
                            save_session(session_id)
        except Exception as e:
            print(f"Error in scheduler task: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    """Start the scheduler when the app starts"""
    asyncio.create_task(scheduler_task())
    print("Scheduler task started")

@app.post("/api/upload")
def upload_videos(request: Request, response: Response):
    """Upload all pending videos to all enabled destinations (immediate or scheduled)"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Check if at least one destination is enabled and connected
    destinations = session.get("destinations", {})
    enabled_destinations = []
    
    print(f"[Upload] Checking destinations for session {session_id[:16]}...")
    print(f"  Destinations config: {destinations}")
    
    for dest_name, uploader_func in DESTINATION_UPLOADERS.items():
        if not uploader_func:
            continue
        
        dest_config = destinations.get(dest_name, {})
        is_enabled = dest_config.get("enabled", False)
        creds_key = f"{dest_name}_creds"
        has_creds = session.get(creds_key) is not None
        
        print(f"  {dest_name}: enabled={is_enabled}, has_creds={has_creds}")
        
        if is_enabled and has_creds:
            enabled_destinations.append(dest_name)
    
    print(f"[Upload] Enabled destinations: {enabled_destinations}")
    
    if not enabled_destinations:
        error_msg = "No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        print(f"[Upload] ERROR: {error_msg}")
        raise HTTPException(400, error_msg)
    
    # Debug: Show all videos and their statuses
    print(f"[Upload] Total videos in session: {len(session['videos'])}")
    for v in session["videos"]:
        print(f"  Video {v.get('id', '?')}: {v.get('filename', '?')} - status: {v.get('status', '?')}")
    
    # Get videos that can be uploaded: pending, failed (retry), or uploading (retry if stuck)
    # Exclude: 'uploaded' (already done), 'scheduled' (will be handled by scheduler)
    pending_videos = [v for v in session["videos"] 
                      if v['status'] in ['pending', 'failed', 'uploading']]
    
    print(f"[Upload] Videos ready to upload: {len(pending_videos)}")
    
    if not pending_videos:
        # Check what statuses videos actually have
        statuses = {}
        for v in session["videos"]:
            status = v.get('status', 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        error_msg = f"No videos ready to upload. Add videos first. Current video statuses: {statuses}"
        print(f"[Upload] ERROR: {error_msg}")
        raise HTTPException(400, error_msg)
    
    # Use YouTube settings for scheduling (can be made destination-agnostic later)
    # For now, all destinations follow the same schedule settings
    upload_immediately = session["youtube_settings"].get('upload_immediately', True)
    
    # If upload immediately is enabled, upload all at once to all enabled destinations
    if upload_immediately:
        for video in pending_videos:
            # Set status to uploading before starting
            video['status'] = 'uploading'
            
            # Track which destinations succeeded/failed
            succeeded_destinations = []
            failed_destinations = []
            
            # Upload to all enabled destinations
            for dest_name in enabled_destinations:
                uploader_func = DESTINATION_UPLOADERS[dest_name]
                if uploader_func:
                    print(f"[Upload] Uploading {video['filename']} to {dest_name}")
                    
                    # Store status before upload (might be 'uploading' or 'pending')
                    status_before = video.get('status', 'pending')
                    
                    # Pass session_id for TikTok rate limiting
                    if dest_name == "tiktok":
                        uploader_func(video, session, session_id)
                    else:
                        uploader_func(video, session)
                    
                    # Check if this destination succeeded by looking for success markers
                    # YouTube success: has 'youtube_id'
                    # TikTok success: has 'tiktok_id' or 'tiktok_publish_id'
                    print(f"[Upload] Checking upload result for {dest_name}...")
                    print(f"  Video status: {video.get('status', 'unknown')}")
                    print(f"  Has youtube_id: {'youtube_id' in video}")
                    print(f"  Has tiktok_id: {'tiktok_id' in video}")
                    print(f"  Has tiktok_publish_id: {'tiktok_publish_id' in video}")
                    print(f"  Has error: {'error' in video}")
                    
                    if dest_name == 'youtube' and 'youtube_id' in video:
                        succeeded_destinations.append(dest_name)
                        print(f"[Upload] ✓ YouTube upload succeeded")
                    elif dest_name == 'tiktok' and ('tiktok_id' in video or 'tiktok_publish_id' in video):
                        succeeded_destinations.append(dest_name)
                        print(f"[Upload] ✓ TikTok upload succeeded")
                    else:
                        # Check if upload function set an error
                        if video.get('status') == 'failed' or 'error' in video:
                            failed_destinations.append(dest_name)
                            # Store per-destination error
                            if 'upload_errors' not in video:
                                video['upload_errors'] = {}
                            video['upload_errors'][dest_name] = video.get('error', 'Upload failed')
                            print(f"[Upload] ✗ {dest_name} upload failed: {video.get('error', 'Unknown error')}")
                        else:
                            # Upload might still be in progress or status unclear
                            print(f"[Upload] ⚠ {dest_name} upload status unclear - checking status...")
                            # If status is 'uploading', it might still be in progress
                            # But since we're synchronous, this shouldn't happen
                            if video.get('status') == 'uploading':
                                print(f"[Upload] ⚠ {dest_name} still shows 'uploading' - may have failed silently")
                                failed_destinations.append(dest_name)
                            else:
                                # Status is neither success nor failed - treat as failed
                                failed_destinations.append(dest_name)
                                print(f"[Upload] ✗ {dest_name} upload failed: no success marker and status is '{video.get('status', 'unknown')}'")
            
            # Determine final status based on results
            # Only mark as 'uploaded' if ALL enabled destinations succeeded
            if len(succeeded_destinations) == len(enabled_destinations):
                video['status'] = 'uploaded'
                # Clear any errors since all succeeded
                if 'error' in video:
                    del video['error']
                if 'upload_errors' in video:
                    del video['upload_errors']
            elif len(succeeded_destinations) > 0:
                # Partial success - some destinations succeeded, some failed
                video['status'] = 'failed'
                video['error'] = f"Partial upload: succeeded ({', '.join(succeeded_destinations)}), failed ({', '.join(failed_destinations)})"
            else:
                # All failed
                video['status'] = 'failed'
                if 'error' not in video:
                    video['error'] = f"Upload failed for all destinations: {', '.join(failed_destinations)}"
        
        save_session(session_id)
        # Count videos that are fully uploaded
        uploaded_count = len([v for v in session["videos"] if v['status'] == 'uploaded'])
        return {
            "uploaded": uploaded_count,
            "message": f"Videos uploaded immediately to: {', '.join(enabled_destinations)}"
        }
    
    # Otherwise, mark for scheduled upload
    if session["youtube_settings"]['schedule_mode'] == 'spaced':
        # Calculate interval in minutes
        value = session["youtube_settings"]['schedule_interval_value']
        unit = session["youtube_settings"]['schedule_interval_unit']
        
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
            scheduled_time = current_time + timedelta(minutes=interval_minutes * i)
            video['scheduled_time'] = scheduled_time.isoformat()
            video['status'] = 'scheduled'
        
        save_session(session_id)
        return {
            "scheduled": len(pending_videos),
            "message": f"Videos scheduled with {value} {unit} interval"
        }
    
    elif session["youtube_settings"]['schedule_mode'] == 'specific_time':
        # Schedule all for a specific time
        if session["youtube_settings"]['schedule_start_time']:
            for video in pending_videos:
                video['scheduled_time'] = session["youtube_settings"]['schedule_start_time']
                video['status'] = 'scheduled'
            
            save_session(session_id)
            return {
                "scheduled": len(pending_videos),
                "message": f"Videos scheduled for {session['youtube_settings']['schedule_start_time']}"
            }
        else:
            raise HTTPException(400, "No start time specified for scheduled upload")
    
    return {"message": "Upload processing"}

if __name__ == "__main__":
    # Use reload=True in development for hot reload
    # Must pass app as import string for reload to work
    reload = os.getenv("ENVIRONMENT", "development") == "development"
    if reload:
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)

