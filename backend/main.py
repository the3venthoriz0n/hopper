# Standard library imports
import asyncio
import json
import logging
import os
import random
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlencode

# Third-party imports
import httpx
import stripe
import uvicorn
from fastapi import (
    Cookie, Depends, FastAPI, File, Header, HTTPException,
    Query, Request, Response, UploadFile
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response as FastAPIResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session

# Google API imports
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# OpenTelemetry imports
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, generate_latest

# Local imports - Database
from models import (
    OAuthToken, SessionLocal, Setting, StripeEvent, Subscription,
    TokenBalance, User, Video, get_db, init_db
)

# Local imports - Auth & Utils
import db_helpers
import redis_client
from auth import (
    authenticate_user, create_user, get_or_create_oauth_user,
    get_user_by_id, hash_password, set_user_password, verify_password
)
from encryption import decrypt, encrypt

# Local imports - Token & Stripe
from stripe_config import (
    PLANS, calculate_tokens_from_bytes, ensure_stripe_products,
    get_plan_price_id, get_plans
)
from stripe_helpers import (
    create_checkout_session, create_free_subscription,
    create_stripe_customer, create_unlimited_subscription,
    get_customer_portal_url, get_subscription_info,
    log_stripe_event, mark_stripe_event_processed,
    update_subscription_from_stripe
)
from token_helpers import (
    add_tokens, check_tokens_available, deduct_tokens,
    ensure_tokens_synced_for_subscription, get_token_balance,
    get_token_transactions, reset_tokens_for_subscription
)
# ============================================================================
# OPENTELEMETRY INITIALIZATION
# ============================================================================

# Get environment for OTEL (before ENVIRONMENT is set)
OTEL_ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

def initialize_otel():
    """Initialize OpenTelemetry providers - called during application startup, not at import time"""
    if not OTEL_ENDPOINT:
        return False
    
    try:
        # Initialize OpenTelemetry
        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "hopper-backend"),
            "service.version": "1.0.0",
            "deployment.environment": OTEL_ENVIRONMENT
        })

        # Trace provider
        trace_provider = TracerProvider(resource=resource)
        otlp_trace_exporter = OTLPSpanExporter(
            endpoint=OTEL_ENDPOINT,
            insecure=True
        )
        trace_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))
        trace.set_tracer_provider(trace_provider)

        # Metrics provider
        otlp_metric_exporter = OTLPMetricExporter(
            endpoint=OTEL_ENDPOINT,
            insecure=True
        )
        metric_reader = PeriodicExportingMetricReader(
            otlp_metric_exporter, 
            export_interval_millis=5000,
            export_timeout_millis=30000
        )
        metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(metrics_provider)
        
        return True
    except Exception as e:
        # Log but don't fail if OTEL setup fails
        print(f"Warning: Failed to initialize OpenTelemetry: {e}")
        return False

# Get tracer and meter (will use defaults if OTEL not initialized)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

# Custom Prometheus metrics - use try/except to handle duplicate registration on module reload
try:
    login_attempts_counter = Counter(
        'hopper_login_attempts_total',
        'Total number of login attempts',
        ['status', 'method']  # status: success or failure, method: email or google
    )
except ValueError:
    login_attempts_counter = REGISTRY._names_to_collectors.get('hopper_login_attempts_total')

try:
    active_users_gauge = Gauge(
        'hopper_active_users',
        'Number of active users (logged in within last hour)'
    )
except ValueError:
    active_users_gauge = REGISTRY._names_to_collectors.get('hopper_active_users')

try:
    current_uploads_gauge = Gauge(
        'hopper_current_uploads',
        'Number of videos currently being uploaded'
    )
except ValueError:
    current_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_current_uploads')

try:
    queued_uploads_gauge = Gauge(
        'hopper_queued_uploads',
        'Number of videos queued for upload (pending)'
    )
except ValueError:
    queued_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_queued_uploads')

try:
    scheduled_uploads_gauge = Gauge(
        'hopper_scheduled_uploads',
        'Number of videos scheduled for upload'
    )
except ValueError:
    scheduled_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_scheduled_uploads')

try:
    failed_uploads_gauge = Gauge(
        'hopper_failed_uploads',
        'Number of failed uploads'
    )
except ValueError:
    failed_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_failed_uploads')

try:
    user_uploads_gauge = Gauge(
        'hopper_user_uploads',
        'Number of uploads per user by status',
        ['user_id', 'user_email', 'status']
    )
except ValueError:
    user_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_user_uploads')

try:
    scheduled_uploads_detail_gauge = Gauge(
        'hopper_scheduled_uploads_detail',
        'Scheduled uploads with scheduled time and created date',
        ['user_id', 'user_email', 'filename', 'scheduled_time', 'created_at', 'status']
    )
except ValueError:
    scheduled_uploads_detail_gauge = REGISTRY._names_to_collectors.get('hopper_scheduled_uploads_detail')

try:
    orphaned_videos_gauge = Gauge(
        'hopper_orphaned_videos',
        'Number of orphaned video files (files without database records)'
    )
except ValueError:
    orphaned_videos_gauge = REGISTRY._names_to_collectors.get('hopper_orphaned_videos')

try:
    cleanup_runs_counter = Counter(
        'hopper_cleanup_runs_total',
        'Total number of cleanup job runs',
        ['status']  # status: success or failure
    )
except ValueError:
    cleanup_runs_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_runs_total')

try:
    cleanup_files_removed_counter = Counter(
        'hopper_cleanup_files_removed_total',
        'Total number of files removed by cleanup job'
    )
except ValueError:
    cleanup_files_removed_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_files_removed_total')

try:
    scheduler_runs_counter = Counter(
        'hopper_scheduler_runs_total',
        'Total number of scheduler job runs',
        ['status']  # status: success or failure
    )
except ValueError:
    scheduler_runs_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_runs_total')

try:
    scheduler_videos_processed_counter = Counter(
        'hopper_scheduler_videos_processed_total',
        'Total number of videos processed by scheduler'
    )
except ValueError:
    scheduler_videos_processed_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_videos_processed_total')

try:
    active_subscriptions_gauge = Gauge(
        'hopper_active_subscriptions',
        'Number of active subscriptions by plan type',
        ['plan_type']  # plan_type: free, medium, pro, unlimited
    )
except ValueError:
    active_subscriptions_gauge = REGISTRY._names_to_collectors.get('hopper_active_subscriptions')

try:
    successful_uploads_counter = Counter(
        'hopper_successful_uploads_total',
        'Total number of successful video uploads'
    )
except ValueError:
    successful_uploads_counter = REGISTRY._names_to_collectors.get('hopper_successful_uploads_total')

try:
    storage_size_gauge = Gauge(
        'hopper_storage_size_bytes',
        'Storage size in bytes',
        ['type']  # type: upload_dir, database, etc.
    )
except ValueError:
    storage_size_gauge = REGISTRY._names_to_collectors.get('hopper_storage_size_bytes')

# ============================================================================
# DATABASE AND REDIS INITIALIZATION (Lifespan Events)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    
    # Initialize OpenTelemetry providers (if configured)
    otel_initialized = initialize_otel()
    otel_logging_initialized = False
    
    if otel_initialized:
        # Setup OTEL logging handler
        otel_logging_initialized = setup_otel_logging()
        if otel_logging_initialized:
            logger.info(f"OpenTelemetry fully initialized (LOG_LEVEL={LOG_LEVEL}), exporting to {OTEL_ENDPOINT}")
        else:
            logger.warning("OpenTelemetry metrics/traces initialized but logging setup failed")
    else:
        logger.info("OpenTelemetry not configured (OTEL_EXPORTER_OTLP_ENDPOINT not set) - running without distributed tracing")
    
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
    
    # Instrument SQLAlchemy after database initialization
    try:
        from models import engine
        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as e:
        logger.warning(f"Failed to instrument SQLAlchemy: {e}")
    
    # Start the scheduler tasks
    logger.info("Starting scheduler tasks...")
    asyncio.create_task(scheduler_task())
    asyncio.create_task(token_reset_scheduler_task())
    logger.info("Scheduler tasks started")
    
    # Start the cleanup task
    logger.info("Starting cleanup task...")
    asyncio.create_task(cleanup_task())
    logger.info("Cleanup task started")
    
    # Start the metrics update task
    logger.info("Starting metrics update task...")
    asyncio.create_task(update_metrics_task())
    logger.info("Metrics update task started")
    
    yield
    
    # Shutdown (if needed in the future)
    logger.info("Shutting down...")

app = FastAPI(lifespan=lifespan)

# Instrument FastAPI with OpenTelemetry
# FastAPI instrumentation automatically generates HTTP metrics (duration, size, status codes)
FastAPIInstrumentor.instrument_app(app)

# Instrument SQLAlchemy (will be done after db initialization)
# Instrument HTTPX - automatically generates HTTP client metrics
HTTPXClientInstrumentor().instrument()

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class SetPasswordRequest(BaseModel):
    password: str


class CheckoutRequest(BaseModel):
    plan_key: str

class GrantTokensRequest(BaseModel):
    amount: int
    reason: Optional[str] = None

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

def setup_otel_logging():
    """Setup OTEL logging handler - called during application startup, NOT at import time"""
    if not OTEL_ENDPOINT:
        return False
        
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource as LogResource
        
        # Initialize the logger provider with resource attributes
        log_resource = LogResource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "hopper-backend"),
            "deployment.environment": OTEL_ENVIRONMENT
        })
        logger_provider = LoggerProvider(resource=log_resource)
        set_logger_provider(logger_provider)
        
        # Set up the OTLP log exporter
        log_exporter = OTLPLogExporter(
            endpoint=OTEL_ENDPOINT,
            insecure=True
        )
        log_processor = BatchLogRecordProcessor(
            log_exporter,
            max_queue_size=2048,
            export_timeout_millis=30000,
            schedule_delay_millis=5000
        )
        logger_provider.add_log_record_processor(log_processor)
        
        # Add OTEL handler to root logger
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        logging.getLogger().addHandler(handler)
        
        return True
    except Exception as e:
        print(f"Warning: Failed to setup OTEL logging: {e}")
        return False

# Configure basic logging (console only) at module import time
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)

# Create logger instance (OTEL handler will be added during app startup if configured)
logger = logging.getLogger(__name__)

# Create specific loggers for different components
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
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


def build_upload_context(user_id: int, db: Session) -> Dict[str, Any]:
    """Build upload context for a user (enabled destinations, settings, tokens)
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Dictionary with:
            - enabled_destinations: List of enabled destination names
            - dest_settings: Destination settings dict
            - all_tokens: All OAuth tokens dict
    """
    # Batch load destination settings and OAuth tokens to prevent N+1 queries
    dest_settings = db_helpers.get_user_settings(user_id, "destinations", db=db)
    all_tokens = db_helpers.get_all_oauth_tokens(user_id, db=db)
    
    # Determine enabled destinations
    enabled_destinations = []
    for dest_name in ["youtube", "tiktok", "instagram"]:
        is_enabled = dest_settings.get(f"{dest_name}_enabled", False)
        has_token = all_tokens.get(dest_name) is not None
        if is_enabled and has_token:
            enabled_destinations.append(dest_name)
    
    return {
        "enabled_destinations": enabled_destinations,
        "dest_settings": dest_settings,
        "all_tokens": all_tokens
    }


def build_video_response(video: Video, all_settings: Dict[str, Dict], all_tokens: Dict[str, Optional[OAuthToken]], user_id: int) -> Dict[str, Any]:
    """Build video response dictionary with computed titles and upload properties
    
    Args:
        video: Video object
        all_settings: Dictionary of all user settings by category
        all_tokens: Dictionary of all OAuth tokens by platform
        user_id: User ID for Redis progress lookup
        
    Returns:
        Dictionary with video data in the same format as GET /api/videos
    """
    global_settings = all_settings.get("global", {})
    youtube_settings = all_settings.get("youtube", {})
    tiktok_settings = all_settings.get("tiktok", {})
    instagram_settings = all_settings.get("instagram", {})
    dest_settings = all_settings.get("destinations", {})
    
    youtube_token = all_tokens.get("youtube")
    tiktok_token = all_tokens.get("tiktok")
    instagram_token = all_tokens.get("instagram")
    
    video_dict = {
        "id": video.id,
        "filename": video.filename,
        "path": video.path,
        "status": video.status,
        "generated_title": video.generated_title,
        "custom_settings": video.custom_settings or {},
        "error": video.error,
        "scheduled_time": video.scheduled_time.isoformat() if video.scheduled_time else None,
        "file_size_bytes": video.file_size_bytes,
        "tokens_consumed": video.tokens_consumed or 0
    }
    
    # Add upload progress from Redis if available
    upload_progress = redis_client.get_upload_progress(user_id, video.id)
    if upload_progress is not None:
        video_dict['upload_progress'] = upload_progress
    
    filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
    
    # Compute YouTube title - Priority: custom > generated_title > template
    custom_settings = video.custom_settings or {}
    if 'title' in custom_settings:
        youtube_title = custom_settings['title']
    elif video.generated_title:
        youtube_title = video.generated_title
    else:
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
        video_dict['tiktok_title'] = tiktok_title[:2200] if len(tiktok_title) > 2200 else tiktok_title
    else:
        video_dict['tiktok_title'] = None
    
    # Instagram properties
    if dest_settings.get("instagram_enabled") and instagram_token:
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
            'location_id': custom_settings.get('location_id', instagram_settings.get('location_id', '')),
            'disable_comments': instagram_settings.get('disable_comments', False),
            'disable_likes': instagram_settings.get('disable_likes', False)
        }
        video_dict['instagram_caption'] = caption[:2200] if len(caption) > 2200 else caption
    else:
        video_dict['instagram_caption'] = None
    
    video_dict['upload_properties'] = upload_props
    
    return video_dict


def check_upload_success(video: Video, dest_name: str) -> bool:
    """Check if upload to a destination succeeded based on video state
    
    Args:
        video: Video object to check
        dest_name: Destination name (youtube, tiktok, instagram)
        
    Returns:
        True if upload succeeded, False otherwise
    """
    custom_settings = video.custom_settings or {}
    
    if dest_name == 'youtube':
        return bool(custom_settings.get('youtube_id'))
    elif dest_name == 'tiktok':
        return bool(custom_settings.get('tiktok_id') or custom_settings.get('tiktok_publish_id'))
    elif dest_name == 'instagram':
        return bool(custom_settings.get('instagram_id') or custom_settings.get('instagram_container_id'))
    return False


def cleanup_video_file(video: Video) -> bool:
    """Delete video file from disk after successful upload
    
    This is called after all destinations succeed. The database record
    is kept for history, but the physical file is removed to save space.
    
    Args:
        video: Video object with path to file
        
    Returns:
        True if cleanup succeeded or file already gone, False on error
    """
    try:
        # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
        video_path = Path(video.path).resolve()
        if video_path.exists():
            video_path.unlink()
            upload_logger.info(f"Cleaned up video file: {video.filename} ({video_path})")
            return True
        else:
            upload_logger.debug(f"Video file already removed: {video.filename}")
            return True
    except Exception as e:
        upload_logger.error(f"Failed to cleanup video file {video.filename}: {str(e)}")
        return False


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

# Rate limiting configuration: more permissive for production (real users), reasonable for development
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
    """Check if request is within rate limit using Redis. Returns True if allowed, False if rate limited."""
    window = RATE_LIMIT_STRICT_WINDOW if strict else RATE_LIMIT_WINDOW
    max_requests = RATE_LIMIT_STRICT_REQUESTS if strict else RATE_LIMIT_REQUESTS
    
    # Increment counter in Redis (with TTL)
    current_count = redis_client.increment_rate_limit(identifier, window)
    
    # Check if limit exceeded
    if current_count > max_requests:
        return False
    
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
        # Skip security checks for OAuth callbacks and public endpoints
        path = request.url.path
        is_callback = (
            "/api/auth/google/login/callback" in path or
            "/api/auth/youtube/callback" in path or
            "/api/auth/tiktok/callback" in path or
            "/api/auth/instagram/callback" in path or
            "/api/auth/instagram/complete" in path
        )
        
        # Public endpoints that should not require origin validation
        is_public_endpoint = (
            path == "/api/auth/csrf" or
            path == "/api/auth/register" or
            path == "/api/auth/login" or
            path == "/api/auth/logout" or
            path == "/api/auth/me" or
            path == "/api/auth/google/login" or
            path == "/api/stripe/webhook" or  # Stripe webhook must be public (no auth)
            path == "/metrics"  # Prometheus metrics endpoint
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
            
            # Origin/Referer validation (skip for GET requests in dev, skip for public endpoints)
            # Note: OAuth callbacks are already excluded by the outer if not is_callback block
            if not is_public_endpoint and (request.method != "GET" or ENVIRONMENT == "production"):
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
# ROOT CAUSE FIX: Use absolute path to prevent path resolution issues
UPLOAD_DIR = Path("uploads").resolve()
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Directory already exists or mounted

# Helper function for setting authentication cookies
def set_auth_cookie(response: Response, session_id: str, request: Request) -> None:
    """Set session cookie with proper domain for cross-subdomain sharing
    
    Args:
        response: FastAPI Response object
        session_id: Session ID to store in cookie
        request: FastAPI Request object (used to extract domain)
    """
    # Extract host from request
    host = request.headers.get("host", DOMAIN)
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
    
    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        domain=cookie_domain,
        httponly=True,
        max_age=30*24*60*60,  # 30 days
        samesite="lax",
        secure=ENVIRONMENT == "production"
    )
    
    # Log cookie domain for debugging
    logger.debug(f"Set session cookie with domain={cookie_domain}")


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
def register(request_data: RegisterRequest, request: Request, response: Response):
    """Register a new user"""
    try:
        # Validate password strength (minimum 8 characters)
        if len(request_data.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters long")
        
        # Create user
        user = create_user(request_data.email, request_data.password)
        
        # Create Stripe customer and free subscription (non-blocking, log errors but don't fail registration)
        try:
            db = SessionLocal()
            try:
                create_stripe_customer(user.email, user.id, db)
                # Create free subscription automatically
                create_free_subscription(user.id, db)
            except Exception as e:
                logger.warning(f"Failed to create Stripe customer/subscription for user {user.id}: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Error creating Stripe customer/subscription during registration: {e}")
        
        # Create session
        session_id = secrets.token_urlsafe(32)
        redis_client.set_session(session_id, user.id)
        
        # Set session cookie with proper domain handling
        set_auth_cookie(response, session_id, request)
        
        logger.info(f"User registered: {user.email} (ID: {user.id})")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
                "is_admin": user.is_admin
            }
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(500, "Registration failed")


@app.post("/api/auth/login")
def login(request_data: LoginRequest, request: Request, response: Response):
    """Login user"""
    try:
        # Authenticate user
        user = authenticate_user(request_data.email, request_data.password)
        if not user:
            # Track failed login attempt
            login_attempts_counter.labels(status="failure", method="email").inc()
            raise HTTPException(401, "Invalid email or password")
        
        # Create session
        session_id = secrets.token_urlsafe(32)
        redis_client.set_session(session_id, user.id)
        
        # Set session cookie with proper domain handling
        set_auth_cookie(response, session_id, request)
        
        # Track successful login attempt
        login_attempts_counter.labels(status="success", method="email").inc()
        
        logger.info(f"User logged in: {user.email} (ID: {user.id})")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
                "is_admin": user.is_admin
            }
        }
    except HTTPException as e:
        # Track failed login attempt if not already tracked
        if e.status_code == 401:
            login_attempts_counter.labels(status="failure", method="email").inc()
        raise
    except Exception as e:
        # Track failed login attempt
        login_attempts_counter.labels(status="failure", method="email").inc()
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(500, "Login failed")


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """Logout user"""
    session_id = request.cookies.get("session_id")
    if session_id:
        redis_client.delete_session(session_id)
        # Also delete CSRF token for this session
        redis_client.redis_client.delete(f"csrf:{session_id}")
        response.delete_cookie("session_id")
        logger.info(f"User logged out (session: {session_id[:16]}...)")
        
        # Immediately update active users count after logout
        # Count unique users with active sessions in Redis
        # Only count sessions that actually exist (not expired)
        session_keys = redis_client.redis_client.keys("session:*")
        active_user_ids = set()
        for key in session_keys:
            user_id = redis_client.redis_client.get(key)
            if user_id:  # Only count if session exists (not expired)
                try:
                    active_user_ids.add(int(user_id))
                except (ValueError, TypeError):
                    # Skip invalid user_id values
                    continue
        active_users = len(active_user_ids)
        active_users_gauge.set(active_users)
        logger.debug(f"Updated active users count after logout: {active_users}")
    
    return {"message": "Logged out successfully"}


@app.delete("/api/auth/account")
def delete_account(request: Request, response: Response, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete user account and all associated data (user-initiated)
    
    This endpoint performs a complete data deletion (GDPR compliant):
    - Deletes all videos from database
    - Deletes all video files from disk
    - Deletes all settings
    - Deletes all OAuth tokens
    - Deletes user account
    - Clears all sessions and caches
    
    This action is irreversible.
    """
    security_logger.info(f"User {user_id} requested account deletion")
    
    try:
        # Delete user account and get cleanup info
        result = db_helpers.delete_user_account(user_id, db=db)
        
        if not result["success"]:
            security_logger.error(f"Failed to delete user {user_id}: {result.get('error')}")
            raise HTTPException(500, f"Failed to delete account: {result.get('error')}")
        
        # Clean up video files from disk
        video_paths = result.get("video_file_paths", [])
        files_deleted = 0
        files_failed = 0
        
        for video_path in video_paths:
            try:
                # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
                path = Path(video_path).resolve()
                if path.exists():
                    path.unlink()
                    files_deleted += 1
                    upload_logger.debug(f"Deleted video file: {video_path}")
            except Exception as e:
                files_failed += 1
                upload_logger.warning(f"Failed to delete video file {video_path}: {e}")
        
        # Log current session to delete it
        session_id = request.cookies.get("session_id")
        if session_id:
            redis_client.delete_session(session_id)
            redis_client.redis_client.delete(f"csrf:{session_id}")
        
        # Clear session cookie
        response.delete_cookie("session_id")
        
        # Log deletion
        stats = result.get("stats", {})
        security_logger.info(
            f"Account deleted: user_id={user_id}, "
            f"email={stats.get('user_email')}, "
            f"videos={stats.get('videos_deleted', 0)}, "
            f"settings={stats.get('settings_deleted', 0)}, "
            f"oauth_tokens={stats.get('oauth_tokens_deleted', 0)}, "
            f"files_deleted={files_deleted}, "
            f"files_failed={files_failed}"
        )
        
        return {
            "message": "Account deleted successfully",
            "stats": {
                **stats,
                "files_deleted": files_deleted,
                "files_failed": files_failed
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        security_logger.error(f"Error deleting account for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to delete account: {str(e)}")


@app.post("/api/auth/set-password")
def set_password(request_data: SetPasswordRequest, user_id: int = Depends(require_auth)):
    """Set password for OAuth user (allows them to use email/password login)"""
    try:
        # Validate password strength (minimum 8 characters)
        if len(request_data.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters long")
        
        # Set password for user
        success = set_user_password(user_id, request_data.password)
        if not success:
            raise HTTPException(404, "User not found")
        
        logger.info(f"Password set for OAuth user (ID: {user_id})")
        return {"message": "Password set successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set password error: {e}", exc_info=True)
        raise HTTPException(500, "Failed to set password")


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
                "created_at": user.created_at.isoformat(),
                "is_admin": user.is_admin
            }
        }
    except Exception as e:
        logger.error(f"Error in /api/auth/me: {e}", exc_info=True)
        # Return None user instead of raising error to prevent 500
        return {"user": None}


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
# GOOGLE OAUTH LOGIN ENDPOINTS (for user authentication)
# ============================================================================

@app.get("/api/auth/google/login")
def auth_google_login(request: Request):
    """Start Google OAuth login flow (for user authentication, not YouTube)"""
    google_config = get_google_client_config()
    if not google_config:
        raise HTTPException(400, "Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_PROJECT_ID environment variables.")
    
    # Build redirect URI dynamically based on request
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
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
    redis_client.redis_client.setex(f"{ENVIRONMENT}:google_login_state:{state}", 300, "pending")
    
    return {"url": url}


@app.get("/api/auth/google/login/callback")
def auth_google_login_callback(code: str, state: str, request: Request, response: Response):
    """Google OAuth login callback - creates or logs in user"""
    # Verify state to prevent CSRF
    # Prefix with environment to prevent collisions between dev/prod
    state_key = f"{ENVIRONMENT}:google_login_state:{state}"
    state_value = redis_client.redis_client.get(state_key)
    if not state_value:
        # Track failed login attempt (invalid state)
        login_attempts_counter.labels(status="failure", method="google").inc()
        # Redirect to frontend with error instead of showing HTML
        frontend_redirect = f"{FRONTEND_URL}/?google_login=error&reason=invalid_state"
        return RedirectResponse(url=frontend_redirect)
    
    # Delete state after verification
    redis_client.redis_client.delete(state_key)
    
    # Build redirect URI dynamically
    protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" or ENVIRONMENT == "production" else "http"
    host = request.headers.get("host", DOMAIN)
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
        user, is_new = get_or_create_oauth_user(email)
        
        # Create session
        session_id = secrets.token_urlsafe(32)
        redis_client.set_session(session_id, user.id)
        
        # Create redirect response
        frontend_redirect = f"{FRONTEND_URL}/?google_login=success"
        redirect_response = RedirectResponse(url=frontend_redirect)
        
        # Set session cookie on the redirect response
        set_auth_cookie(redirect_response, session_id, request)
        
        # Track successful login attempt
        login_attempts_counter.labels(status="success", method="google").inc()
        
        action = "registered" if is_new else "logged in"
        logger.info(f"User {action} via Google OAuth: {user.email} (ID: {user.id})")
        
        return redirect_response
        
    except HTTPException:
        raise
    except Exception as e:
        # Track failed login attempt
        login_attempts_counter.labels(status="failure", method="google").inc()
        logger.error(f"Google login error: {e}", exc_info=True)
        # Redirect to frontend with error
        frontend_redirect = f"{FRONTEND_URL}/?google_login=error"
        return RedirectResponse(url=frontend_redirect)


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
    # ROOT CAUSE FIX: Add prompt='consent' to force Google to always return refresh_token
    # Without this, Google only returns refresh_token on first authorization
    url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=str(user_id)
    )
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
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=flow_creds.scopes
    )
    
    # ROOT CAUSE FIX: Fetch and cache account info immediately during OAuth
    # This prevents "Loading account..." from showing on refresh when there are API issues
    token_data = db_helpers.credentials_to_oauth_token_data(creds, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
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
            import httpx
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
    db_helpers.save_oauth_token(
        user_id=user_id,
        platform="youtube",
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
        extra_data=extra_data
    )
    
    # Enable YouTube destination by default
    db_helpers.set_user_setting(user_id, "destinations", "youtube_enabled", True)
    
    youtube_logger.info(f"YouTube OAuth completed for user {user_id}")
    
    # ROOT CAUSE FIX: Return connection status directly from authoritative source
    # This eliminates race conditions - no need for separate API call
    youtube_status = {"connected": True, "enabled": True}
    status_param = quote(json.dumps(youtube_status))
    
    # Redirect to frontend with status
    if FRONTEND_URL:
        frontend_url = f"{FRONTEND_URL}?connected=youtube&status={status_param}"
    else:
        host = request.headers.get("host", "localhost:8000")
        protocol = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
        frontend_url = f"{protocol}://{host.replace(':8000', ':3000')}?connected=youtube&status={status_param}"
    
    return RedirectResponse(frontend_url)

@app.get("/api/destinations")
def get_destinations(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get destination status for current user"""
    # Batch load OAuth tokens and settings to prevent N+1 queries
    all_tokens = db_helpers.get_all_oauth_tokens(user_id, db=db)
    settings = db_helpers.get_user_settings(user_id, "destinations", db=db)
    
    # Extract OAuth tokens
    youtube_token = all_tokens.get("youtube")
    tiktok_token = all_tokens.get("tiktok")
    instagram_token = all_tokens.get("instagram")
    
    # Check token expiration status
    youtube_expiry = db_helpers.check_token_expiration(youtube_token)
    tiktok_expiry = db_helpers.check_token_expiration(tiktok_token)
    instagram_expiry = db_helpers.check_token_expiration(instagram_token)
    
    # Get scheduled video count
    videos = db_helpers.get_user_videos(user_id, db=db)
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

@app.get("/api/auth/youtube/account")
def get_youtube_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube account information (channel name/email)"""
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube", db=db)
    
    if not youtube_token:
        return {"account": None}
    
    try:
        # Check for cached account info in extra_data first (prevents "Loading account..." on refresh)
        extra_data = youtube_token.extra_data or {}
        cached_channel_name = extra_data.get("channel_name")
        cached_email = extra_data.get("email")
        cached_channel_id = extra_data.get("channel_id")
        
        # If we have cached account info with channel_name or email, return it immediately
        if cached_channel_name or cached_email:
            account_info = {}
            if cached_channel_name:
                account_info["channel_name"] = cached_channel_name
            if cached_channel_id:
                account_info["channel_id"] = cached_channel_id
            if cached_email:
                account_info["email"] = cached_email
            youtube_logger.debug(f"Returning cached YouTube account info for user {user_id}")
            return {"account": account_info}
        
        # Convert to Credentials object (automatically decrypts)
        youtube_creds = db_helpers.oauth_token_to_credentials(youtube_token, db=db)
        if not youtube_creds:
            # If credentials can't be converted (e.g., decryption failed), 
            # the token is likely corrupted or encrypted with a different key
            # Return None so user can reconnect
            youtube_logger.warning(f"Could not convert YouTube token to credentials for user {user_id}. Token may need to be refreshed or reconnected.")
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
                    extra_data=token_data["extra_data"],
                    db=db
                )
            except Exception as refresh_error:
                youtube_logger.warning(f"Token refresh failed for user {user_id}: {str(refresh_error)}")
        
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get channel info with timeout
        account_info = None
        try:
            channels_response = youtube.channels().list(
                part='snippet',
                mine=True
            ).execute()
            
            if channels_response.get('items') and len(channels_response['items']) > 0:
                channel = channels_response['items'][0]
                account_info = {
                    "channel_name": channel['snippet']['title'],
                    "channel_id": channel['id'],
                    "thumbnail": channel['snippet'].get('thumbnails', {}).get('default', {}).get('url')
                }
        except Exception as channel_error:
            youtube_logger.warning(f"Could not fetch channel info for user {user_id}: {str(channel_error)}")
            # Continue without channel info, try to get email
        
        # Get email from Google OAuth2 userinfo with timeout
        try:
            if youtube_creds.expired and youtube_creds.refresh_token:
                youtube_creds.refresh(GoogleRequest())
            
            with httpx.Client(timeout=5.0) as client:
                userinfo_response = client.get(
                    'https://www.googleapis.com/oauth2/v2/userinfo',
                    headers={'Authorization': f'Bearer {youtube_creds.token}'}
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
        
        # Cache the account info for future requests (if we have channel_name or email)
        if account_info and (account_info.get("channel_name") or account_info.get("email")):
            extra_data["channel_name"] = account_info.get("channel_name")
            extra_data["channel_id"] = account_info.get("channel_id")
            extra_data["email"] = account_info.get("email")
            
            # Save updated extra_data back to database
            token_data = db_helpers.credentials_to_oauth_token_data(
                youtube_creds, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
            )
            db_helpers.save_oauth_token(
                user_id=user_id,
                platform="youtube",
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=token_data["expires_at"],
                extra_data=extra_data,
                db=db
            )
        
        return {"account": account_info}
    except Exception as e:
        youtube_logger.error(f"Error getting YouTube account info for user {user_id}: {str(e)}", exc_info=True)
        # Try to return cached account info even on exception
        try:
            extra_data = youtube_token.extra_data or {}
            cached_channel_name = extra_data.get("channel_name")
            cached_email = extra_data.get("email")
            if cached_channel_name or cached_email:
                account_info = {}
                if cached_channel_name:
                    account_info["channel_name"] = cached_channel_name
                if extra_data.get("channel_id"):
                    account_info["channel_id"] = extra_data["channel_id"]
                if cached_email:
                    account_info["email"] = cached_email
                return {"account": account_info}
        except:
            pass
        return {"account": None, "error": str(e)}

@app.post("/api/global/wordbank")
def add_wordbank_word(word: str, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Add a word to the global wordbank"""
    # Strip whitespace and capitalize
    word = word.strip().capitalize()
    if not word:
        raise HTTPException(400, "Word cannot be empty")
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word not in wordbank:
        wordbank.append(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    # Return updated settings
    return db_helpers.get_user_settings(user_id, "global", db=db)

@app.delete("/api/global/wordbank/{word}")
def remove_wordbank_word(word: str, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove a word from the global wordbank"""
    # Decode URL-encoded word
    word = unquote(word)
    
    # Get current wordbank
    settings = db_helpers.get_user_settings(user_id, "global", db=db)
    wordbank = settings.get("wordbank", [])
    
    if word in wordbank:
        wordbank.remove(word)
        db_helpers.set_user_setting(user_id, "global", "wordbank", wordbank, db=db)
    
    return {"wordbank": wordbank}

@app.delete("/api/global/wordbank")
def clear_wordbank(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Clear all words from the global wordbank"""
    db_helpers.set_user_setting(user_id, "global", "wordbank", [], db=db)
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
def toggle_instagram(enabled: bool, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Toggle Instagram destination on/off"""
    db_helpers.set_user_setting(user_id, "destinations", "instagram_enabled", enabled, db=db)
    
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram", db=db)
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
            
            # ROOT CAUSE FIX: Fetch account info immediately and cache it
            # This prevents "Loading account..." from showing on refresh when token expires
            access_token = token_json["access_token"]
            open_id = token_json.get("open_id")
            extra_data = {
                "open_id": open_id,
                "scope": token_json.get("scope"),
                "token_type": token_json.get("token_type"),
                "refresh_expires_in": token_json.get("refresh_expires_in")
            }
            
            # Try to fetch creator info to cache display_name and username
            try:
                creator_info_response = await client.post(
                    TIKTOK_CREATOR_INFO_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8"
                    },
                    json={},
                    timeout=5.0
                )
                
                if creator_info_response.status_code == 200:
                    creator_data = creator_info_response.json()
                    creator_info = creator_data.get("data", {})
                    
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
                    
                    tiktok_logger.info(f"Cached TikTok account info during OAuth: {extra_data.get('display_name')} (@{extra_data.get('username')})")
                else:
                    tiktok_logger.warning(f"Could not fetch creator info during OAuth (status {creator_info_response.status_code}), will try later")
            except Exception as fetch_error:
                tiktok_logger.warning(f"Could not fetch creator info during OAuth: {fetch_error}, will try later")
            
            # Store in database (encrypted) with cached account info
            db_helpers.save_oauth_token(
                user_id=user_id,
                platform="tiktok",
                access_token=access_token,
                refresh_token=token_json.get("refresh_token"),
                expires_at=expires_at,
                extra_data=extra_data
            )
            
            # Enable TikTok destination
            db_helpers.set_user_setting(user_id, "destinations", "tiktok_enabled", True)
            
            tiktok_logger.info(f"TikTok OAuth completed for user {user_id}")
            
            # ROOT CAUSE FIX: Return connection status directly from authoritative source
            # This eliminates race conditions - no need for separate API call
            tiktok_status = {"connected": True, "enabled": True}
            status_param = quote(json.dumps(tiktok_status))
            
            # Redirect to frontend with status
            return RedirectResponse(f"{FRONTEND_URL}?connected=tiktok&status={status_param}")
            
    except Exception as e:
        tiktok_logger.error(f"Callback exception: {e}", exc_info=True)
        return RedirectResponse(f"{FRONTEND_URL}?error=tiktok_auth_failed")


@app.get("/api/auth/tiktok/account")
def get_tiktok_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get TikTok account information (display name/username)"""
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok", db=db)
    
    if not tiktok_token:
        return {"account": None}
    
    try:
        # Check for cached account info in extra_data first (like Instagram)
        extra_data = tiktok_token.extra_data or {}
        cached_display_name = extra_data.get("display_name")
        cached_username = extra_data.get("username")
        cached_avatar_url = extra_data.get("avatar_url")
        open_id = extra_data.get("open_id")
        
        # Build account info from cached data (always preserve what we have)
        account_info = {}
        if open_id:
            account_info["open_id"] = open_id
        if cached_display_name:
            account_info["display_name"] = cached_display_name
        if cached_username:
            account_info["username"] = cached_username
        if cached_avatar_url:
            account_info["avatar_url"] = cached_avatar_url
        
        # ROOT CAUSE FIX: If we have cached account info with display_name or username,
        # ALWAYS return it immediately and NEVER call the API.
        # This prevents the account name from being lost when API fails.
        if cached_display_name or cached_username:
            tiktok_logger.debug(f"Returning cached TikTok account info for user {user_id}")
            return {"account": account_info}
        
        # If no cached display_name/username but we have open_id, try to fetch from API
        if not open_id:
            tiktok_logger.warning(f"No open_id found for user {user_id}")
            # Return None if we don't have open_id (can't identify account)
            return {"account": None}
        
        # Get access token (decrypted)
        access_token = decrypt(tiktok_token.access_token)
        if not access_token:
            tiktok_logger.warning(f"Failed to decrypt TikTok token for user {user_id}")
            # Return None if we don't have complete account info (need display_name or username)
            return {"account": None}
        
        # Call TikTok creator info API with timeout (must use POST, not GET)
        # Only call API if we don't have cached display_name/username
        try:
            with httpx.Client(timeout=5.0) as client:
                creator_info_response = client.post(
                    TIKTOK_CREATOR_INFO_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8"
                    },
                    json={}
                )
                
                if creator_info_response.status_code != 200:
                    tiktok_logger.warning(f"TikTok creator info request failed: {creator_info_response.status_code}")
                    # ROOT CAUSE FIX: Re-check database for cached data before returning
                    # This handles race conditions where cache might have been updated
                    tiktok_token_refresh = db_helpers.get_oauth_token(user_id, "tiktok", db=db)
                    if tiktok_token_refresh and tiktok_token_refresh.extra_data:
                        refresh_extra_data = tiktok_token_refresh.extra_data
                        refresh_display_name = refresh_extra_data.get("display_name")
                        refresh_username = refresh_extra_data.get("username")
                        if refresh_display_name or refresh_username:
                            # We have cached data - return it instead of incomplete data
                            account_info = {}
                            if open_id:
                                account_info["open_id"] = open_id
                            if refresh_display_name:
                                account_info["display_name"] = refresh_display_name
                            if refresh_username:
                                account_info["username"] = refresh_username
                            if refresh_extra_data.get("avatar_url"):
                                account_info["avatar_url"] = refresh_extra_data.get("avatar_url")
                            tiktok_logger.debug(f"Found cached account info after API failure, returning it")
                            return {"account": account_info}
                    # If no cached data with display_name/username, return None (don't return incomplete data)
                    return {"account": None}
                
                creator_data = creator_info_response.json()
                creator_info = creator_data.get("data", {})
                
                # Extract account information
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
                
                # Cache the account info in extra_data for future requests
                if account_info.get("display_name") or account_info.get("username"):
                    extra_data["display_name"] = account_info.get("display_name")
                    extra_data["username"] = account_info.get("username")
                    extra_data["avatar_url"] = account_info.get("avatar_url")
                    db_helpers.save_oauth_token(
                        user_id=user_id,
                        platform="tiktok",
                        access_token=tiktok_token.access_token,  # Already encrypted
                        refresh_token=tiktok_token.refresh_token,
                        expires_at=tiktok_token.expires_at,
                        extra_data=extra_data,
                        db=db
                    )
                
                # Only return if we have complete account info (display_name or username)
                if account_info.get("display_name") or account_info.get("username"):
                    return {"account": account_info}
                else:
                    # Incomplete data - return None
                    return {"account": None}
                    
        except Exception as api_error:
            tiktok_logger.warning(f"Error calling TikTok API for user {user_id}: {str(api_error)}")
            # Return cached account info only if it's complete (has display_name or username)
            if account_info.get("display_name") or account_info.get("username"):
                return {"account": account_info}
            # Don't return incomplete account data (only open_id)
            return {"account": None}
        
    except Exception as e:
        tiktok_logger.error(f"Error getting TikTok account info for user {user_id}: {str(e)}", exc_info=True)
        # Try to return cached account info even on exception - but only if complete
        try:
            extra_data = tiktok_token.extra_data or {}
            cached_display_name = extra_data.get("display_name")
            cached_username = extra_data.get("username")
            # Only return if we have display_name or username (complete data)
            if cached_display_name or cached_username:
                account_info = {}
                open_id = extra_data.get("open_id")
                if open_id:
                    account_info["open_id"] = open_id
                if cached_display_name:
                    account_info["display_name"] = cached_display_name
                if cached_username:
                    account_info["username"] = cached_username
                return {"account": account_info}
        except:
            pass
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
    instagram_logger.info(f"Redirect URI: {redirect_uri}")
    instagram_logger.info(f"Scopes: {scope_string}")
    instagram_logger.info(f"Facebook App ID: {FACEBOOK_APP_ID[:8]}...")
    instagram_logger.debug(f"Full auth URL: {auth_url}")
    
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
    instagram_logger.debug(f"Callback query params: state={state}, error={error}, error_description={error_description}")
    instagram_logger.debug(f"Full callback URL: {request.url}")
    
    # Check for errors from Facebook
    if error:
        error_msg = f"Facebook OAuth error: {error}"
        if error_description:
            error_msg += f" - {error_description}"
        instagram_logger.error(error_msg)
        return RedirectResponse(f"{FRONTEND_URL}?error=instagram_auth_failed&reason={error}")
    
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
                        // ROOT CAUSE FIX: Pass connection status from authoritative source via URL
                        // This eliminates race conditions - no need for separate API call
                        const status = data.instagram ? encodeURIComponent(JSON.stringify(data.instagram)) : '';
                        window.location.href = '{FRONTEND_URL}?connected=instagram' + (status ? '&status=' + status : '');
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
        user = get_user_by_id(app_user_id)
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
            # ROOT CAUSE FIX: Use different variable name to avoid overwriting app_user_id
            facebook_user_id = None
            user_name = None
            me_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/me"
            me_params = {"fields": "id,name,email", "access_token": access_token_to_use}
            me_response = await client.get(me_url, params=me_params)
            if me_response.status_code == 200:
                me_data = me_response.json()
                facebook_user_id = me_data.get('id')
                user_name = me_data.get('name', 'Unknown')
                instagram_logger.info(f"Token belongs to Facebook user: {user_name} (ID: {facebook_user_id})")
                
                # Try alternative: Check if user has any pages by querying /{facebook_user_id}/accounts
                alt_pages_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{facebook_user_id}/accounts"
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
                user_info = f"Logged in as: {user_name} (ID: {facebook_user_id})" if user_name and facebook_user_id else "Could not identify Facebook user"
                user_id_str = str(facebook_user_id) if facebook_user_id else "unknown"
                
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
            
            instagram_logger.info(f"Instagram Username: @{username} for user {app_user_id}")
            
            # Calculate expiry (Instagram tokens are long-lived)
            expires_at = None
            if 'expires_in' in locals():
                from datetime import datetime, timedelta, timezone
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            
            # Store in database (encrypted)
            # ROOT CAUSE FIX: Use app_user_id (from state), not facebook_user_id
            db_helpers.save_oauth_token(
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
            db_helpers.set_user_setting(app_user_id, "destinations", "instagram_enabled", True, db=db)
            
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

@app.get("/api/auth/instagram/account")
async def get_instagram_account(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram account information (username)"""
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram", db=db)
    
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
                db_helpers.save_oauth_token(
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

@app.post("/api/auth/instagram/disconnect")
def disconnect_instagram(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Disconnect Instagram account"""
    db_helpers.delete_oauth_token(user_id, "instagram", db=db)
    db_helpers.set_user_setting(user_id, "destinations", "instagram_enabled", False, db=db)
    return {"message": "Disconnected"}


# Helper: Fetch Instagram profile info (username and Business Account ID)
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


@app.get("/api/global/settings")
def get_global_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get global settings"""
    return db_helpers.get_user_settings(user_id, "global", db=db)

@app.post("/api/global/settings")
def update_global_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    title_template: Optional[str] = Query(None),
    description_template: Optional[str] = Query(None),
    upload_immediately: Optional[bool] = Query(None),
    schedule_mode: Optional[str] = Query(None),
    schedule_interval_value: Optional[int] = Query(None),
    schedule_interval_unit: Optional[str] = Query(None),
    schedule_start_time: Optional[str] = Query(None),
    allow_duplicates: Optional[bool] = Query(None),
    upload_first_immediately: Optional[bool] = Query(None)
):
    """Update global settings"""
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "global", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "global", "description_template", description_template, db=db)
    
    if upload_immediately is not None:
        db_helpers.set_user_setting(user_id, "global", "upload_immediately", upload_immediately, db=db)
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        db_helpers.set_user_setting(user_id, "global", "schedule_mode", schedule_mode, db=db)
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_value", schedule_interval_value, db=db)
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        db_helpers.set_user_setting(user_id, "global", "schedule_interval_unit", schedule_interval_unit, db=db)
    
    if schedule_start_time is not None:
        db_helpers.set_user_setting(user_id, "global", "schedule_start_time", schedule_start_time, db=db)
    
    if allow_duplicates is not None:
        db_helpers.set_user_setting(user_id, "global", "allow_duplicates", allow_duplicates, db=db)
    
    if upload_first_immediately is not None:
        db_helpers.set_user_setting(user_id, "global", "upload_first_immediately", upload_first_immediately, db=db)
    
    return db_helpers.get_user_settings(user_id, "global", db=db)

@app.get("/api/youtube/settings")
def get_youtube_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get YouTube upload settings"""
    return db_helpers.get_user_settings(user_id, "youtube", db=db)

@app.post("/api/youtube/settings")
def update_youtube_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
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
        db_helpers.set_user_setting(user_id, "youtube", "visibility", visibility, db=db)
    
    if made_for_kids is not None:
        db_helpers.set_user_setting(user_id, "youtube", "made_for_kids", made_for_kids, db=db)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "youtube", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "description_template", description_template, db=db)
    
    if tags_template is not None:
        db_helpers.set_user_setting(user_id, "youtube", "tags_template", tags_template, db=db)
    
    return db_helpers.get_user_settings(user_id, "youtube", db=db)

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
def get_tiktok_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get TikTok upload settings"""
    return db_helpers.get_user_settings(user_id, "tiktok", db=db)

@app.post("/api/tiktok/settings")
def update_tiktok_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
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
        db_helpers.set_user_setting(user_id, "tiktok", "privacy_level", privacy_level, db=db)
    
    if allow_comments is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_comments", allow_comments, db=db)
    
    if allow_duet is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_duet", allow_duet, db=db)
    
    if allow_stitch is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "allow_stitch", allow_stitch, db=db)
    
    if title_template is not None:
        if len(title_template) > 100:
            raise HTTPException(400, "Title template must be 100 characters or less")
        db_helpers.set_user_setting(user_id, "tiktok", "title_template", title_template, db=db)
    
    if description_template is not None:
        db_helpers.set_user_setting(user_id, "tiktok", "description_template", description_template, db=db)
    
    return db_helpers.get_user_settings(user_id, "tiktok", db=db)

# Instagram settings endpoints
@app.get("/api/instagram/settings")
def get_instagram_settings(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get Instagram upload settings"""
    return db_helpers.get_user_settings(user_id, "instagram", db=db)

@app.post("/api/instagram/settings")
def update_instagram_settings(
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    caption_template: str = None,
    location_id: str = None,
    disable_comments: bool = None,
    disable_likes: bool = None
):
    """Update Instagram upload settings"""
    if caption_template is not None:
        if len(caption_template) > 2200:
            raise HTTPException(400, "Caption template must be 2200 characters or less")
        db_helpers.set_user_setting(user_id, "instagram", "caption_template", caption_template, db=db)
    
    if location_id is not None:
        db_helpers.set_user_setting(user_id, "instagram", "location_id", location_id, db=db)
    
    if disable_comments is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_comments", disable_comments, db=db)
    
    if disable_likes is not None:
        db_helpers.set_user_setting(user_id, "instagram", "disable_likes", disable_likes, db=db)
    
    return db_helpers.get_user_settings(user_id, "instagram", db=db)

# Maximum file size for uploads (10GB)
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB in bytes

@app.post("/api/videos")
async def add_video(file: UploadFile = File(...), user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Add video to user's queue"""
    # ROOT CAUSE FIX: Validate file size during streaming
    # Note: For multipart/form-data uploads, we cannot reliably get file size before reading
    # because Content-Length includes the entire request (boundaries, field names, etc.), not just the file.
    # FastAPI's UploadFile.size may also not be set. We validate during streaming instead.
    
    upload_logger.info(f"Starting upload for user {user_id}: {file.filename} (Content-Type: {file.content_type})")
    
    # Get user settings
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube", db=db)
    
    # Check for duplicates if not allowed
    if not global_settings.get("allow_duplicates", False):
        existing_videos = db_helpers.get_user_videos(user_id, db=db)
        if any(v.filename == file.filename for v in existing_videos):
            raise HTTPException(400, f"Duplicate video: {file.filename} is already in the queue")
    
    # Save file to disk with streaming and size validation
    # ROOT CAUSE FIX: Use streaming to handle large files without loading entire file into memory
    path = UPLOAD_DIR / file.filename
    file_size = 0
    start_time = asyncio.get_event_loop().time()
    last_log_time = start_time
    chunk_count = 0
    
    try:
        chunk_size = 1024 * 1024  # 1MB chunks
        
        with open(path, "wb") as f:
            while True:
                # Read chunk with explicit timeout to detect connection issues
                try:
                    chunk = await asyncio.wait_for(file.read(chunk_size), timeout=300.0)  # 5 minute timeout per chunk
                except asyncio.TimeoutError:
                    upload_logger.error(f"Chunk read timeout for user {user_id}: {file.filename} (received {file_size / (1024*1024):.2f} MB)")
                    raise
                
                if not chunk:
                    break
                
                file_size += len(chunk)
                chunk_count += 1
                current_time = asyncio.get_event_loop().time()
                
                # Log progress every 10MB or every 30 seconds
                if file_size % (10 * 1024 * 1024) < chunk_size or (current_time - last_log_time) >= 30:
                    elapsed = current_time - start_time
                    speed_mbps = (file_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    upload_logger.info(
                        f"Upload progress for user {user_id}: {file.filename} - "
                        f"{file_size / (1024*1024):.2f} MB received ({chunk_count} chunks, "
                        f"{speed_mbps:.2f} MB/s, {elapsed:.1f}s elapsed)"
                    )
                    last_log_time = current_time
                
                # Validate file size during streaming (before writing entire file)
                if file_size > MAX_FILE_SIZE:
                    # Clean up partial file
                    try:
                        path.unlink()
                    except:
                        pass
                    size_mb = file_size / (1024 * 1024)
                    size_gb = file_size / (1024 * 1024 * 1024)
                    max_mb = MAX_FILE_SIZE / (1024 * 1024)
                    max_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
                    raise HTTPException(
                        413,
                        f"File too large: {file.filename} is {size_mb:.2f} MB ({size_gb:.2f} GB). Maximum file size is {max_mb:.0f} MB ({max_gb:.0f} GB)."
                    )
                
                f.write(chunk)
        
        elapsed_total = asyncio.get_event_loop().time() - start_time
        avg_speed = (file_size / (1024 * 1024)) / elapsed_total if elapsed_total > 0 else 0
        upload_logger.info(
            f"Video added for user {user_id}: {file.filename} "
            f"({file_size / (1024*1024):.2f} MB, {chunk_count} chunks, "
            f"{avg_speed:.2f} MB/s, {elapsed_total:.1f}s total)"
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError as e:
        # Clean up partial file on timeout
        try:
            if path.exists():
                path.unlink()
        except:
            pass
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        upload_logger.error(
            f"Upload timeout for user {user_id}: {file.filename} "
            f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks) - "
            f"Likely caused by proxy/reverse proxy timeout (Cloudflare default: 100s free, 600s paid)",
            exc_info=True
        )
        raise HTTPException(
            504, 
            f"Upload timeout: The file upload was interrupted after {elapsed:.0f} seconds. "
            f"This is likely due to a proxy timeout (e.g., Cloudflare). "
            f"Please try again or contact support if the issue persists."
        )
    except HTTPException:
        raise
    except Exception as e:
        # Clean up partial file on error
        try:
            if path.exists():
                path.unlink()
        except:
            pass
        error_type = type(e).__name__
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        
        # Check for connection-related errors that might indicate proxy timeout
        error_str = str(e).lower()
        is_connection_error = any(keyword in error_str for keyword in [
            'connection', 'reset', 'closed', 'broken', 'timeout', 
            'gateway', 'proxy', 'cloudflare'
        ])
        
        if is_connection_error:
            upload_logger.error(
                f"Connection error during upload for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks) - "
                f"Error: {error_type}: {str(e)} - Likely proxy/reverse proxy timeout",
                exc_info=True
            )
            raise HTTPException(
                504,
                f"Upload failed: Connection was interrupted after {elapsed:.0f} seconds. "
                f"This may be due to a proxy timeout. Please try again."
            )
        else:
            upload_logger.error(
                f"Failed to save video file for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks, "
                f"error: {error_type}: {str(e)})",
                exc_info=True
            )
            raise HTTPException(500, f"Failed to save video file: {str(e)}")
    
    # Calculate tokens required for this upload (1 token = 10MB)
    tokens_required = calculate_tokens_from_bytes(file_size)
    
    # NOTE: We don't check tokens here - tokens are deducted when video is successfully uploaded to platforms
    # This allows users to queue videos and manage their uploads without immediately consuming tokens
    
    # Generate YouTube title
    filename_no_ext = file.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    youtube_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Add to database with file size and tokens
    # ROOT CAUSE FIX: Store absolute path to prevent path resolution issues
    # 
    # TOKEN DEDUCTION STRATEGY:
    # Tokens are NOT deducted when adding to queue - only when successfully uploaded to platforms.
    # This allows users to queue videos, reorder, edit, and remove without losing tokens.
    # When a video is uploaded to multiple platforms (YouTube + TikTok + Instagram), tokens are
    # only charged ONCE (on first successful platform upload). The video.tokens_consumed field
    # tracks this to prevent double-charging across multiple platforms.
    # NOTE: Tokens are NOT deducted here - they're deducted when video is successfully uploaded to platforms
    video = db_helpers.add_user_video(
        user_id=user_id,
        filename=file.filename,
        path=str(path.resolve()),  # Ensure absolute path
        generated_title=youtube_title,
        file_size_bytes=file_size,
        tokens_consumed=0,  # Don't consume tokens yet - only on successful upload
        db=db
    )
    
    upload_logger.info(f"Video added to queue for user {user_id}: {file.filename} ({file_size / (1024*1024):.2f} MB, will cost {tokens_required} tokens on upload)")
    
    # Return the same format as GET /api/videos for consistency
    # Get settings and tokens to compute titles (batch load to prevent N+1)
    all_settings = db_helpers.get_all_user_settings(user_id, db=db)
    all_tokens = db_helpers.get_all_oauth_tokens(user_id, db=db)
    
    # Build video response using the same helper function as GET endpoint
    return build_video_response(video, all_settings, all_tokens, user_id)

# ============================================================================
# SUBSCRIPTION & TOKEN MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/api/subscription/plans")
def get_subscription_plans():
    """Get available subscription plans (excludes hidden/dev-only plans)"""
    from stripe_config import get_price_info
    
    plans_list = []
    for plan_key, plan_config in PLANS.items():
        if plan_config.get("hidden", False):
            continue
        
        plan_data = {
            "key": plan_key,
            "name": plan_config["name"],
            "monthly_tokens": plan_config["monthly_tokens"],
            "stripe_price_id": plan_config.get("stripe_price_id"),
        }
        
        # Get price information from Stripe if price_id exists
        price_id = plan_config.get("stripe_price_id")
        if price_id:
            price_info = get_price_info(price_id)
            if price_info:
                plan_data["price"] = price_info
            else:
                # If we can't get price info, set to free for free plan, or None for others
                if plan_key == 'free':
                    plan_data["price"] = {
                        "amount": 0,
                        "amount_dollars": 0,
                        "currency": "USD",
                        "formatted": "Free"
                    }
                else:
                    plan_data["price"] = None
        elif plan_key == 'free':
            # Free plan doesn't have a Stripe price
            plan_data["price"] = {
                "amount": 0,
                "amount_dollars": 0,
                "currency": "USD",
                "formatted": "Free"
            }
        else:
            plan_data["price"] = None
        
        plans_list.append(plan_data)
    
    return {"plans": plans_list}


@app.get("/api/subscription/current")
def get_current_subscription(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get user's current subscription.
    
    This is a lightweight GET endpoint that returns current state.
    Subscription syncing is handled by:
    - Webhooks (primary mechanism)
    - Background scheduler (periodic sync for missed webhooks)
    """
    subscription_info = get_subscription_info(user_id, db)
    
    # If user doesn't have a subscription, create a free one
    if not subscription_info:
        logger.info(f"User {user_id} has no subscription, creating free subscription")
        free_sub = create_free_subscription(user_id, db)
        if free_sub:
            subscription_info = get_subscription_info(user_id, db)
        else:
            # If creation fails, return a default response
            logger.error(f"Failed to create free subscription for user {user_id}")
            return {
                "subscription": None,
                "token_balance": {
                    "tokens_remaining": 0,
                    "tokens_used_this_period": 0,
                    "unlimited": False,
                    "period_start": None,
                    "period_end": None,
                }
            }
    
    token_balance = get_token_balance(user_id, db)
    
    return {
        "subscription": subscription_info,
        "token_balance": token_balance,
    }


@app.post("/api/subscription/create-checkout")
def create_subscription_checkout(
    checkout_request: CheckoutRequest,
    request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for subscription"""
    plan_key = checkout_request.plan_key
    plans = get_plans()
    if plan_key not in plans:
        raise HTTPException(400, f"Invalid plan: {plan_key}")
    
    plan = plans[plan_key]
    if not plan.get("stripe_price_id"):
        raise HTTPException(400, f"Plan {plan_key} is not configured with a Stripe price")
    
    # Check if user already has an active paid subscription
    existing_subscription = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active'
    ).first()
    
    # Determine if we should cancel existing subscription (upgrade/change scenario)
    cancel_existing = False
    if existing_subscription:
        # If user has a paid subscription (not free/unlimited), allow upgrade/change by canceling existing
        if existing_subscription.stripe_subscription_id and not existing_subscription.stripe_subscription_id.startswith(('free_', 'unlimited_')):
            # Always allow changing plans - cancel existing and create new
            cancel_existing = True
            current_plan = plans.get(existing_subscription.plan_type, {})
            new_plan = plan
            current_tokens = current_plan.get('monthly_tokens', 0)
            new_tokens = new_plan.get('monthly_tokens', 0)
            logger.info(f"User {user_id} changing from {existing_subscription.plan_type} ({current_tokens} tokens) to {plan_key} ({new_tokens} tokens)")
    
    # Get frontend URL from environment or request
    frontend_url = os.getenv("FRONTEND_URL", str(request.base_url).rstrip("/"))
    success_url = f"{frontend_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_url}/subscription"
    
    try:
        session_data = create_checkout_session(user_id, plan["stripe_price_id"], success_url, cancel_url, db, cancel_existing=cancel_existing)
        
        if not session_data:
            raise HTTPException(500, "Failed to create checkout session")
        
        return session_data
    except ValueError as e:
        # User already has subscription (caught by create_checkout_session)
        frontend_url = os.getenv("FRONTEND_URL", str(request.base_url).rstrip("/"))
        portal_url = get_customer_portal_url(user_id, f"{frontend_url}/subscription", db)
        if portal_url:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "User already has an active subscription",
                    "message": str(e),
                    "portal_url": portal_url
                }
            )
        else:
            raise HTTPException(400, str(e))


@app.get("/api/subscription/checkout-status")
def check_checkout_status(
    session_id: str = Query(..., description="Stripe checkout session ID"),
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """
    Check the status of a Stripe checkout session and verify if subscription was created.
    This endpoint allows the frontend to verify payment completion without polling subscription state.
    """
    import stripe
    from stripe_config import STRIPE_SECRET_KEY
    
    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured")
    
    try:
        # Retrieve checkout session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        # Verify this session belongs to the current user
        session_user_id = None
        if session.metadata and session.metadata.get("user_id"):
            session_user_id = int(session.metadata["user_id"])
        elif session.customer:
            # Fallback: check if customer matches current user
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.stripe_customer_id == session.customer:
                session_user_id = user_id
        
        if session_user_id != user_id:
            raise HTTPException(403, "Checkout session does not belong to current user")
        
        # Check session status
        if session.payment_status != "paid":
            return {
                "status": "pending",
                "payment_status": session.payment_status,
                "subscription_created": False
            }
        
        # If subscription mode, check if subscription exists
        # Note: We do NOT create/update subscriptions here - that's handled by webhook events
        # This endpoint only checks status and resets tokens if subscription exists and period doesn't match
        subscription_created = False
        subscription_id = None
        if session.mode == "subscription" and session.subscription:
            subscription_id = session.subscription
            # Check if subscription exists in our database
            sub = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == subscription_id
            ).first()
            
            if sub:
                subscription_created = True
                # Ensure tokens are synced for this subscription (idempotent)
                # This handles cases where tokens weren't reset by webhook
                ensure_tokens_synced_for_subscription(user_id, subscription_id, db)
            else:
                # Subscription doesn't exist yet - webhook should create it
                logger.warning(f"Subscription {subscription_id} not found in database. Webhook may not have fired yet or failed.")
        
        return {
            "status": "completed" if session.payment_status == "paid" else "pending",
            "payment_status": session.payment_status,
            "subscription_created": subscription_created,
            "subscription_id": subscription_id,
            "mode": session.mode
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error checking checkout session {session_id}: {e}")
        raise HTTPException(500, f"Error checking checkout session: {str(e)}")
    except Exception as e:
        logger.error(f"Error checking checkout session {session_id}: {e}", exc_info=True)
        raise HTTPException(500, "Error checking checkout session")


@app.get("/api/subscription/portal")
def get_subscription_portal(
    request: Request,
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Get subscription management URL.
    - If user is on free plan, redirects to purchase/upgrade page
    - If user has paid subscription, opens Stripe customer portal
    """
    from stripe_helpers import get_subscription_info
    
    subscription_info = get_subscription_info(user_id, db)
    
    # If user is on free plan or has no subscription, redirect to purchase page
    if not subscription_info or subscription_info.get('plan_type') == 'free':
        frontend_url = os.getenv("FRONTEND_URL", str(request.base_url).rstrip("/"))
        # Return URL to subscription page where they can see plans and purchase
        purchase_url = f"{frontend_url}/subscription"
        return {"url": purchase_url, "action": "purchase"}
    
    # If user has a paid subscription, open Stripe customer portal
    frontend_url = os.getenv("FRONTEND_URL", str(request.base_url).rstrip("/"))
    return_url = f"{frontend_url}/subscription"
    
    portal_url = get_customer_portal_url(user_id, return_url, db)
    
    if not portal_url:
        raise HTTPException(500, "Failed to create portal session")
    
    return {"url": portal_url, "action": "manage"}


@app.post("/api/subscription/cancel")
def cancel_subscription(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Cancel the user's subscription and switch to free plan.
    Cancels the Stripe subscription immediately and creates a new free Stripe subscription.
    Preserves the user's current token balance.
    """
    from token_helpers import get_or_create_token_balance
    from stripe_helpers import create_free_subscription
    
    # Get current subscription
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    if not subscription:
        raise HTTPException(404, "No subscription found")
    
    # If already on free plan, nothing to do
    if subscription.plan_type == 'free':
        return {
            "status": "success",
            "message": "Already on free plan",
            "plan_type": "free"
        }
    
    # Get current token balance to preserve it
    token_balance = get_or_create_token_balance(user_id, db)
    current_tokens = token_balance.tokens_remaining
    
    # Cancel existing Stripe subscription (all subscriptions are now Stripe subscriptions)
    if subscription.stripe_subscription_id:
        try:
            # Cancel immediately (not at period end)
            stripe.Subscription.delete(subscription.stripe_subscription_id)
            logger.info(f"Canceled Stripe subscription {subscription.stripe_subscription_id} for user {user_id}")
        except stripe.error.StripeError as e:
            logger.warning(f"Failed to cancel Stripe subscription {subscription.stripe_subscription_id}: {e}")
            # Continue anyway - we'll create the free subscription
    
    # Delete old subscription record
    old_subscription_id = subscription.stripe_subscription_id
    db.delete(subscription)
    db.commit()
    
    # Create new free Stripe subscription
    free_subscription = create_free_subscription(user_id, db)
    if not free_subscription:
        raise HTTPException(500, "Failed to create free subscription")
    
    logger.info(f"User {user_id} canceled subscription {old_subscription_id} and switched to free plan, preserved {current_tokens} tokens")
    return {
        "status": "success",
        "message": "Subscription canceled and switched to free plan",
        "plan_type": "free",
        "tokens_preserved": current_tokens
    }


@app.post("/api/subscription/switch-to-free")
def switch_to_free_plan(
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Switch user to free plan (alias for cancel subscription).
    This is the same as canceling the subscription.
    """
    return cancel_subscription(user_id=user_id, db=db)


@app.get("/api/tokens/balance")
def get_tokens_balance(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get current token balance"""
    balance = get_token_balance(user_id, db)
    return balance


@app.get("/api/tokens/transactions")
def get_tokens_transactions(
    limit: int = 50,
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get token transaction history"""
    transactions = get_token_transactions(user_id, limit, db)
    return {"transactions": transactions}


# ============================================================================
# STRIPE WEBHOOK ENDPOINT
# ============================================================================


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    import stripe
    from stripe_config import STRIPE_WEBHOOK_SECRET
    from stripe_helpers import (
        log_stripe_event, 
        mark_stripe_event_processed,
        update_subscription_from_stripe
    )
    from token_helpers import ensure_tokens_synced_for_subscription
    
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe webhook secret not configured")
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload in Stripe webhook: {e}")
        raise HTTPException(400, "Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature in Stripe webhook: {e}")
        raise HTTPException(400, "Invalid signature")
    
    # Check if event already processed (idempotency)
    stripe_event = log_stripe_event(event["id"], event["type"], event, db)
    if stripe_event.processed:
        logger.info(f"Stripe event {event['id']} (type: {event['type']}) already processed")
        return {"status": "already_processed"}
    
    logger.info(f"📥 Processing Stripe webhook event {event['id']} (type: {event['type']})")
    
    try:
        event_type = event["type"]
        event_data = event["data"]["object"]
        
        # Route to appropriate handler
        if event_type == "checkout.session.completed":
            logger.info(f"Routing to handle_checkout_completed")
            handle_checkout_completed(event_data, db)
            
        elif event_type == "customer.subscription.created":
            logger.info(f"Routing to handle_subscription_created")
            handle_subscription_created(event_data, db)
            
        elif event_type == "customer.subscription.updated":
            logger.info(f"Routing to handle_subscription_updated for subscription {event_data.get('id', 'unknown')}")
            handle_subscription_updated(event_data, db)
            
        elif event_type == "customer.subscription.deleted":
            handle_subscription_deleted(event_data, db)
            
        elif event_type == "invoice.payment_succeeded":
            handle_invoice_payment_succeeded(event_data, db)
            
        elif event_type == "invoice.payment_failed":
            handle_invoice_payment_failed(event_data, db)
        
        # Mark event as processed
        mark_stripe_event_processed(event["id"], db)
        
        return {"status": "success"}
        
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Error processing Stripe webhook event {event['id']} "
            f"(type: {event.get('type')}): {error_msg}", 
            exc_info=True
        )
        mark_stripe_event_processed(event["id"], db, error_message=error_msg)
        # Return 200 to prevent Stripe retries for unrecoverable errors
        return {"status": "error", "message": error_msg}


def handle_checkout_completed(session_data: Dict[str, Any], db: Session):
    """Handle checkout.session.completed event."""
    if session_data["mode"] != "subscription":
        return
    
    subscription_id = session_data.get("subscription")
    if not subscription_id:
        logger.warning("Checkout session has no subscription ID")
        return
    
    # Get user_id
    user_id = _get_user_id_from_session(session_data, db)
    if not user_id:
        logger.error(f"Could not determine user_id for checkout session {session_data['id']}")
        return
    
    # Cancel any existing paid subscriptions (prevent duplicates)
    _cancel_existing_subscriptions(user_id, subscription_id, db)
    
    # Note: Subscription creation is handled by customer.subscription.created event
    # We don't sync tokens here because subscription may not exist in DB yet
    # Tokens will be synced by customer.subscription.created handler
    
    logger.info(f"Checkout completed for user {user_id}, subscription {subscription_id}")


def handle_subscription_created(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.created event.
    
    This fires when a NEW subscription is created. However, during upgrades,
    Stripe may fire both .created and .updated events. We need to ensure
    tokens are only added once.
    """
    import stripe
    from token_helpers import ensure_tokens_synced_for_subscription
    
    # Retrieve full subscription with expanded items
    subscription = stripe.Subscription.retrieve(
        subscription_data["id"], 
        expand=['items.data.price']
    )
    
    user_id = _get_user_id_from_subscription(subscription, db)
    if not user_id:
        logger.error(
            f"Could not determine user_id for subscription {subscription.id}"
        )
        return
    
    # Check if subscription already exists in DB (might have been created by .updated event first)
    existing_sub = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription.id
    ).first()
    
    # Create or update subscription in database
    updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
    if not updated_sub:
        logger.error(
            f"Failed to create/update subscription {subscription.id} for user {user_id}"
        )
        return
    
    # Only sync tokens if this is truly a NEW subscription (didn't exist before)
    # If it already existed, it means .updated event already processed it, so don't add tokens again
    if not existing_sub:
        logger.info(f"New subscription created for user {user_id}: {updated_sub.plan_type} - syncing tokens")
        ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
    else:
        logger.info(f"Subscription {subscription.id} already existed in DB (likely processed by .updated event first) - skipping token sync to avoid double-adding")
    
    logger.info(f"Subscription created for user {user_id}: {updated_sub.plan_type}")


def handle_subscription_updated(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.updated event.
    
    This is the PRIMARY event for subscription state changes, including renewals.
    Stripe fires this event when:
    - Subscription renews (period advances)
    - Plan changes
    - Status changes
    - Other subscription property changes
    
    For renewals, the current_period_start and current_period_end advance.
    """
    import stripe
    from token_helpers import handle_subscription_renewal, ensure_tokens_synced_for_subscription
    
    try:
        subscription_id = subscription_data.get("id")
        if not subscription_id:
            logger.error("customer.subscription.updated event missing subscription ID")
            return
        
        logger.info(f"Processing customer.subscription.updated event for subscription {subscription_id}")
        
        # Retrieve full subscription with expanded items
        subscription = stripe.Subscription.retrieve(
            subscription_id, 
            expand=['items.data.price']
        )
        
        user_id = _get_user_id_from_subscription(subscription, db)
        if not user_id:
            logger.error(
                f"Could not determine user_id for subscription {subscription.id} in customer.subscription.updated"
            )
            return
        
        logger.info(f"Found user_id={user_id} for subscription {subscription.id}")
        
        # Get the old subscription data BEFORE update (critical for renewal detection)
        old_sub = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == subscription.id
        ).first()
        
        # Also get user's current subscription (might be different if this is a new subscription during upgrade)
        user_current_sub = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).first()
        
        old_period_end = old_sub.current_period_end if old_sub else None
        old_period_start = old_sub.current_period_start if old_sub else None
        old_plan_type = old_sub.plan_type if old_sub else None
        
        # If this is a new subscription (old_sub is None) but user has an existing subscription,
        # check if it's a plan switch (upgrade/downgrade)
        is_new_subscription = old_sub is None
        is_plan_switch = False
        
        # Get plan type from Stripe subscription (before updating DB)
        from stripe_helpers import _get_plan_type_from_price
        price_id = None
        items_data = []
        if hasattr(subscription, 'items') and subscription.items:
            items_data = subscription.items.data if hasattr(subscription.items, 'data') else []
        if items_data and len(items_data) > 0:
            first_item = items_data[0]
            if hasattr(first_item, 'price') and first_item.price:
                price_id = first_item.price.id if hasattr(first_item.price, 'id') else None
        new_plan_type = _get_plan_type_from_price(price_id) if price_id else None
        
        if is_new_subscription and user_current_sub and user_current_sub.stripe_subscription_id != subscription.id:
            # New subscription created, but user had a different subscription - this is an upgrade/downgrade
            is_plan_switch = user_current_sub.plan_type != new_plan_type if new_plan_type else True
            old_plan_type = user_current_sub.plan_type
            logger.info(
                f"New subscription {subscription.id} created for user {user_id} who had subscription {user_current_sub.stripe_subscription_id} "
                f"(plan: {user_current_sub.plan_type} -> {new_plan_type}). This is likely an upgrade/downgrade."
            )
        
        if old_sub:
            logger.info(
                f"Subscription update for user {user_id} (subscription {subscription.id}): "
                f"old_period_end={old_period_end}, old_period_start={old_period_start}, "
                f"old_plan={old_sub.plan_type}, old_status={old_sub.status}"
            )
        else:
            logger.info(
                f"Subscription update for user {user_id} (subscription {subscription.id}): "
                f"No existing subscription found in DB (new subscription or first webhook)"
            )
        
        # Update subscription in database (this updates period_end if it changed)
        updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
        if not updated_sub:
            logger.error(
                f"Failed to update subscription {subscription.id} for user {user_id}"
            )
            return
        
        logger.info(
            f"Subscription updated in DB for user {user_id}: "
            f"new_period_start={updated_sub.current_period_start}, "
            f"new_period_end={updated_sub.current_period_end}, "
            f"plan={updated_sub.plan_type}, status={updated_sub.status}"
        )
        
        # Handle renewal if detected (single source of truth for renewal logic)
        renewal_handled = handle_subscription_renewal(user_id, updated_sub, old_period_end, db)
        
        if renewal_handled:
            logger.info(f"✅ Renewal was handled for user {user_id}, subscription {subscription.id}")
        else:
            # Not a renewal - check what type of change this is
            if is_new_subscription and not is_plan_switch:
                # Truly new subscription (first time) - .created event should handle tokens
                # But if .updated fires first, handle it here
                logger.info(f"ℹ️  New subscription for user {user_id} (subscription {subscription.id}) - syncing tokens")
                ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
            elif is_plan_switch or (old_sub and old_sub.plan_type != updated_sub.plan_type):
                # Plan switch detected (plan changed) - preserve tokens, only update period
                # This handles upgrades/downgrades where tokens should be preserved
                from token_helpers import get_token_balance, get_or_create_token_balance
                token_balance = get_token_balance(user_id, db)
                current_tokens = token_balance.get('tokens_remaining', 0) if token_balance else 0
                logger.info(
                    f"🔄 Plan switch detected for user {user_id}: {old_plan_type} -> {updated_sub.plan_type}. "
                    f"Preserving tokens (current: {current_tokens}), updating period only."
                )
                # Just update the period, preserve tokens
                balance = get_or_create_token_balance(user_id, db)
                balance.period_start = updated_sub.current_period_start
                balance.period_end = updated_sub.current_period_end
                balance.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"✅ Plan switch completed - tokens preserved: {balance.tokens_remaining}")
            elif old_period_end and updated_sub.current_period_end == old_period_end:
                # Period didn't change and plan didn't change - status change or other update
                logger.info(f"ℹ️  Status/other change for user {user_id}, subscription {subscription.id} - syncing tokens")
                ensure_tokens_synced_for_subscription(user_id, subscription.id, db)
            else:
                # Period changed but wasn't detected as renewal and plan didn't change
                period_diff = (updated_sub.current_period_end - old_period_end).total_seconds() / 86400 if old_period_end else 0
                
                # If period advanced significantly (more than a day), it's likely a renewal that wasn't caught
                if period_diff > 1:
                    logger.warning(
                        f"⚠️  Period changed for user {user_id} (diff: {period_diff:.1f} days) but renewal not detected. "
                        f"Attempting to handle as renewal anyway (period advanced significantly)."
                    )
                    if period_diff >= 1:
                        logger.info(f"🔄 Treating period change as renewal (safety net) for user {user_id}")
                        handle_subscription_renewal(user_id, updated_sub, old_period_end, db)
                else:
                    logger.info(
                        f"ℹ️  Period changed slightly for user {user_id} (diff: {period_diff:.1f} days) - likely status change, not renewal"
                    )
        
        logger.info(f"✅ customer.subscription.updated processing completed for user {user_id}, subscription {subscription.id}")
        
    except Exception as e:
        logger.error(
            f"❌ ERROR in handle_subscription_updated for subscription {subscription_data.get('id', 'unknown')}: {e}",
            exc_info=True
        )
        # Don't re-raise - let webhook handler mark as processed with error
        # This prevents infinite retries but logs the error for debugging


def handle_subscription_deleted(subscription_data: Dict[str, Any], db: Session):
    """Handle customer.subscription.deleted event."""
    subscription = db.query(Subscription).filter(
        Subscription.stripe_subscription_id == subscription_data["id"]
    ).first()
    
    if subscription:
        subscription.status = "canceled"
        db.commit()
        logger.info(f"Marked subscription {subscription_data['id']} as canceled")


def handle_invoice_payment_succeeded(invoice_data: Dict[str, Any], db: Session):
    """Handle invoice.payment_succeeded event.
    
    This event fires when an invoice payment succeeds. It can be for:
    - New subscription (billing_reason: 'subscription_create')
    - Renewal (billing_reason: 'subscription_cycle')
    - Plan change (billing_reason: 'subscription_update')
    - Manual invoice (billing_reason: 'manual')
    
    IMPORTANT: Token renewal is handled by customer.subscription.updated, not here.
    This handler only ensures the subscription state is updated. If the subscription
    period has advanced, customer.subscription.updated will have already fired and
    handled the renewal. This is a safety net to ensure subscription state is current.
    """
    import stripe
    from token_helpers import ensure_tokens_synced_for_subscription
    
    subscription_id = invoice_data.get("subscription")
    if not subscription_id:
        # Not a subscription invoice, skip
        return
    
    # Update subscription state from Stripe (ensures we have latest period info)
    subscription = stripe.Subscription.retrieve(
        subscription_id,
        expand=['items.data.price']
    )
    user_id = _get_user_id_from_subscription(subscription, db)
    
    if not user_id:
        logger.error(f"Could not determine user_id for subscription {subscription_id} in invoice.payment_succeeded")
        return
    
    # Update subscription in database (this may trigger customer.subscription.updated if period changed)
    updated_sub = update_subscription_from_stripe(subscription, db, user_id=user_id)
    if not updated_sub:
        logger.error(f"Failed to update subscription {subscription_id} for user {user_id}")
        return
    
    # Note: We don't handle token renewal here because:
    # 1. customer.subscription.updated is the canonical event for subscription state changes
    # 2. It fires when the period advances, which is the definitive signal for renewal
    # 3. invoice.payment_succeeded can fire before the period advances in some edge cases
    # 4. This separation ensures single responsibility and prevents duplicate processing
    
    # Only sync tokens as a safety net (handles edge cases where subscription.updated didn't fire)
    # This is idempotent and won't double-process renewals
    ensure_tokens_synced_for_subscription(user_id, subscription_id, db)
    
    billing_reason = invoice_data.get("billing_reason", "unknown")
    logger.info(f"Invoice payment succeeded for subscription {subscription_id} (billing_reason: {billing_reason}), subscription state updated for user {user_id}")


def handle_invoice_payment_failed(invoice_data: Dict[str, Any], db: Session):
    """Handle invoice.payment_failed event."""
    import stripe
    
    subscription_id = invoice_data.get("subscription")
    if not subscription_id:
        return
    
    # Update subscription status with expanded items
    subscription = stripe.Subscription.retrieve(
        subscription_id,
        expand=['items.data.price']
    )
    user_id = _get_user_id_from_subscription(subscription, db)
    
    if user_id:
        update_subscription_from_stripe(subscription, db, user_id=user_id)
        logger.warning(f"Payment failed for subscription {subscription_id}")


def _get_user_id_from_session(session_data: Dict[str, Any], db: Session) -> Optional[int]:
    """Extract user_id from checkout session."""
    # Try metadata first
    if session_data.get("metadata") and session_data["metadata"].get("user_id"):
        return int(session_data["metadata"]["user_id"])
    
    # Fallback to customer lookup
    customer_id = session_data.get("customer")
    if customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user.id
    
    return None


def _get_user_id_from_subscription(subscription: stripe.Subscription, db: Session) -> Optional[int]:
    """Extract user_id from Stripe subscription."""
    # Try metadata first
    if subscription.metadata and subscription.metadata.get("user_id"):
        return int(subscription.metadata["user_id"])
    
    # Fallback to customer lookup
    customer_id = subscription.customer
    if customer_id:
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            return user.id
    
    return None


def _cancel_existing_subscriptions(user_id: int, new_subscription_id: str, db: Session):
    """Cancel any existing Stripe subscriptions for a user."""
    import stripe
    
    existing_subs = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active',
        Subscription.stripe_subscription_id != new_subscription_id
    ).all()
    
    for sub in existing_subs:
        # Cancel all Stripe subscriptions (all subscriptions are now Stripe subscriptions)
        if sub.stripe_subscription_id:
            try:
                stripe.Subscription.delete(sub.stripe_subscription_id)
                sub.status = 'canceled'
                db.commit()
                logger.info(f"Canceled old subscription {sub.stripe_subscription_id}")
            except stripe.error.StripeError as e:
                logger.warning(
                    f"Failed to cancel subscription {sub.stripe_subscription_id}: {e}"
                )

# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

def require_admin(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)) -> User:
    """Dependency: Require admin role, return user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user

def require_admin_get(request: Request, user_id: int = Depends(require_auth), db: Session = Depends(get_db)) -> User:
    """Dependency: Require admin role for GET requests (no CSRF required)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


@app.post("/api/admin/users/{target_user_id}/unlimited-plan")
def enroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Enroll a user in the unlimited plan via Stripe (admin only)."""
    import stripe
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    # Check if user already has a subscription
    existing_subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    
    if existing_subscription:
        # If user already has unlimited plan, return success
        if existing_subscription.plan_type == 'unlimited':
            return {"message": f"User {target_user_id} already has unlimited plan"}
        
        # Cancel existing subscription in Stripe (all subscriptions are now Stripe subscriptions)
        if existing_subscription.stripe_subscription_id:
            try:
                stripe.Subscription.delete(existing_subscription.stripe_subscription_id)
                logger.info(f"Cancelled existing subscription {existing_subscription.stripe_subscription_id} for user {target_user_id}")
            except Exception as e:
                logger.warning(f"Failed to cancel existing Stripe subscription: {e}")
    
    # Preserve current token balance before enrolling in unlimited
    from token_helpers import get_or_create_token_balance
    token_balance = get_or_create_token_balance(target_user_id, db)
    preserved_tokens = token_balance.tokens_remaining
    
    # Create unlimited subscription via Stripe
    subscription = create_unlimited_subscription(target_user_id, preserved_tokens, db)
    
    if not subscription:
        raise HTTPException(500, "Failed to create unlimited subscription")
    
    logger.info(f"Admin {admin_user.id} enrolled user {target_user_id} in unlimited plan (preserved {preserved_tokens} tokens)")
    
    return {"message": f"User {target_user_id} enrolled in unlimited plan"}


@app.delete("/api/admin/users/{target_user_id}/unlimited-plan")
def unenroll_unlimited_plan(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Unenroll a user from the unlimited plan by canceling Stripe subscription (admin only)"""
    from stripe_helpers import create_free_subscription
    import stripe
    
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    subscription = db.query(Subscription).filter(Subscription.user_id == target_user_id).first()
    if not subscription:
        raise HTTPException(404, "User has no subscription")
    
    if subscription.plan_type != 'unlimited':
        raise HTTPException(400, f"User is not on unlimited plan (current: {subscription.plan_type})")
    
    # Get preserved token balance before deleting subscription
    preserved_tokens = subscription.preserved_tokens_balance if subscription.preserved_tokens_balance is not None else 0
    
    # Cancel Stripe subscription (all subscriptions are now Stripe subscriptions)
    if subscription.stripe_subscription_id:
        try:
            stripe.Subscription.delete(subscription.stripe_subscription_id)
            logger.info(f"Cancelled Stripe subscription {subscription.stripe_subscription_id} for user {target_user_id}")
        except stripe.error.StripeError as e:
            logger.warning(f"Failed to cancel Stripe subscription: {e}")
            # Continue anyway - we'll still update the database
    
    # Create free subscription to replace it
    old_subscription_id = subscription.stripe_subscription_id
    db.delete(subscription)
    db.commit()
    
    free_subscription = create_free_subscription(target_user_id, db)
    if not free_subscription:
        raise HTTPException(500, "Failed to create free subscription")
    
    # Restore preserved token balance by ADDING to current balance
    # This ensures any tokens granted while on unlimited are preserved
    from token_helpers import get_or_create_token_balance
    token_balance = get_or_create_token_balance(target_user_id, db)
    current_balance = token_balance.tokens_remaining
    token_balance.tokens_remaining = current_balance + preserved_tokens  # ADD, don't replace
    db.commit()
    
    logger.info(f"Admin {admin_user.id} unenrolled user {target_user_id} from unlimited plan (restored {preserved_tokens} tokens)")
    
    return {"message": f"User {target_user_id} unenrolled from unlimited plan"}


@app.get("/api/admin/users")
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """List users with basic info (admin only)"""
    query = db.query(User)
    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))
    
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page-1)*limit).limit(limit).all()
    
    # Get subscriptions for all users in one query
    user_ids = [u.id for u in users]
    subscriptions = {s.user_id: s for s in db.query(Subscription).filter(Subscription.user_id.in_(user_ids)).all()}
    
    return {
        "users": [{
            "id": u.id,
            "email": u.email,
            "created_at": u.created_at.isoformat(),
            "plan_type": subscriptions.get(u.id).plan_type if subscriptions.get(u.id) else None,
            "is_admin": u.is_admin
        } for u in users],
        "total": total,
        "page": page,
        "limit": limit
    }


@app.get("/api/admin/users/{user_id}")
def get_user_details(
    user_id: int,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get detailed user information (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    # Get token balance
    balance = get_token_balance(user_id, db)
    
    # Get subscription info
    subscription = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    
    # Calculate total tokens used (sum of all positive token transactions)
    from sqlalchemy import func
    from models import TokenTransaction
    total_tokens_used = db.query(func.sum(TokenTransaction.tokens)).filter(
        TokenTransaction.user_id == user_id,
        TokenTransaction.tokens > 0
    ).scalar() or 0
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "plan_type": subscription.plan_type if subscription else None,
            "is_admin": user.is_admin,
            "stripe_customer_id": user.stripe_customer_id
        },
        "token_balance": balance,
        "token_usage": {
            "tokens_used_this_period": balance.get("tokens_used_this_period", 0) if balance else 0,
            "total_tokens_used": int(total_tokens_used)
        },
        "subscription": {
            "plan_type": subscription.plan_type if subscription else None,
            "status": subscription.status if subscription else None
        } if subscription else None
    }


@app.post("/api/admin/users/{user_id}/grant-tokens")
def grant_tokens(
    user_id: int,
    request_data: GrantTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Grant a specific amount of tokens to a user (admin only)"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Token amount must be positive")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(404, "User not found")
    
    success = add_tokens(
        user_id=user_id,
        tokens=request_data.amount,
        transaction_type='grant',
        metadata={'admin_id': admin_user.id, 'reason': request_data.reason or 'admin_grant'},
        db=db
    )
    
    if not success:
        raise HTTPException(500, "Failed to grant tokens")
    
    logger.info(f"Admin {admin_user.id} granted {request_data.amount} tokens to user {user_id}")
    return {"message": f"Granted {request_data.amount} tokens to user {user_id}"}


@app.get("/api/admin/webhooks/events")
def get_webhook_events(
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = None,
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get recent Stripe webhook events for debugging"""
    from models import StripeEvent
    from sqlalchemy import desc
    
    query = db.query(StripeEvent)
    
    if event_type:
        query = query.filter(StripeEvent.event_type == event_type)
    
    events = query.order_by(desc(StripeEvent.id)).limit(limit).all()
    
    return {
        "events": [
            {
                "id": e.id,
                "stripe_event_id": e.stripe_event_id,
                "event_type": e.event_type,
                "processed": e.processed,
                "error_message": e.error_message,
            }
            for e in events
        ],
        "total": len(events)
    }


@app.get("/api/admin/users/{user_id}/transactions")
def get_user_transactions_admin(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin_get),
    db: Session = Depends(get_db)
):
    """Get token transaction history for a user (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    transactions = get_token_transactions(user_id, limit, db)
    return {"transactions": transactions}


@app.get("/api/upload/limits")
async def get_upload_limits():
    """Get upload size limits"""
    max_mb = MAX_FILE_SIZE / (1024 * 1024)
    max_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
    return {
        "max_file_size_bytes": MAX_FILE_SIZE,
        "max_file_size_mb": int(max_mb),
        "max_file_size_gb": max_gb,
        "max_file_size_display": f"{int(max_mb)} MB ({max_gb:.0f} GB)"
    }

@app.get("/api/videos")
def get_videos(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get video queue with progress and computed titles for user"""
    # Get user's videos and settings - batch load to prevent N+1 queries
    videos = db_helpers.get_user_videos(user_id, db=db)
    all_settings = db_helpers.get_all_user_settings(user_id, db=db)
    all_tokens = db_helpers.get_all_oauth_tokens(user_id, db=db)
    
    # Extract settings by category
    global_settings = all_settings.get("global", {})
    youtube_settings = all_settings.get("youtube", {})
    tiktok_settings = all_settings.get("tiktok", {})
    instagram_settings = all_settings.get("instagram", {})
    dest_settings = all_settings.get("destinations", {})
    
    # Extract OAuth tokens
    youtube_token = all_tokens.get("youtube")
    tiktok_token = all_tokens.get("tiktok")
    instagram_token = all_tokens.get("instagram")
    
    videos_with_info = []
    for video in videos:
        # Use the shared helper function to build video response
        video_dict = build_video_response(video, all_settings, all_tokens, user_id)
        videos_with_info.append(video_dict)
    
    return videos_with_info

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove video from user's queue"""
    success = db_helpers.delete_video(video_id, user_id, db=db)
    if not success:
        raise HTTPException(404, "Video not found")
    
    # Clean up file if it exists
    videos = db_helpers.get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
    if video:
        video_path = Path(video.path).resolve()
        if video_path.exists():
            try:
                video_path.unlink()
            except Exception as e:
                upload_logger.warning(f"Could not delete file {video_path}: {e}")
    
    return {"ok": True}

@app.delete("/api/videos")
def delete_all_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete all videos from user's queue"""
    videos = db_helpers.get_user_videos(user_id, db=db)
    deleted_count = 0
    
    # Delete all video files and database records
    for video in videos:
        # Skip videos that are currently uploading
        if video.status == 'uploading':
            continue
            
        # Clean up file if it exists
        video_path = Path(video.path).resolve()
        if video_path.exists():
            try:
                video_path.unlink()
            except Exception as e:
                upload_logger.warning(f"Could not delete file {video_path}: {e}")
        
        # Delete from database
        db.delete(video)
        deleted_count += 1
    
    db.commit()
    upload_logger.info(f"Deleted {deleted_count} videos for user {user_id}")
    
    return {"ok": True, "deleted": deleted_count}

@app.post("/api/videos/{video_id}/recompute-title")
def recompute_video_title(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Recompute video title from current template"""
    # Get video
    videos = db_helpers.get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Get settings
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube", db=db)
    
    # Remove custom title if exists in custom_settings
    custom_settings = video.custom_settings or {}
    if "title" in custom_settings:
        del custom_settings["title"]
        db_helpers.update_video(video_id, user_id, db=db, custom_settings=custom_settings)
    
    # Regenerate title
    filename_no_ext = video.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    
    new_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Update generated_title in database
    db_helpers.update_video(video_id, user_id, db=db, generated_title=new_title)
    
    return {"ok": True, "title": new_title[:100]}

@app.patch("/api/videos/{video_id}")
def update_video(
    video_id: int,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    title: str = None,
    description: str = None,
    tags: str = None,
    visibility: str = None,
    made_for_kids: bool = None,
    scheduled_time: str = None
):
    """Update video settings"""
    # Get video
    videos = db_helpers.get_user_videos(user_id, db=db)
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
    db_helpers.update_video(video_id, user_id, db=db, **update_data)
    
    # Return updated video
    updated_videos = db_helpers.get_user_videos(user_id, db=db)
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
async def cancel_scheduled_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel all scheduled videos for user"""
    videos = db_helpers.get_user_videos(user_id, db=db)
    cancelled_count = 0
    
    for video in videos:
        if video.status == "scheduled":
            video_id = video.id
            db_helpers.update_video(video_id, user_id, db=db, status="pending", scheduled_time=None)
            cancelled_count += 1
    
    return {"ok": True, "cancelled": cancelled_count}


@app.post("/api/admin/cleanup")
async def manual_cleanup(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Manually trigger cleanup of old and orphaned files
    
    This endpoint allows users to clean up their own old uploaded videos.
    Removes video files for videos uploaded more than 24 hours ago.
    """
    try:
        cleanup_logger.info(f"Manual cleanup triggered by user {user_id}")
        
        # Clean up user's old uploaded videos (older than 24 hours)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        old_uploaded_videos = db.query(Video).filter(
            Video.user_id == user_id,
            Video.status == "uploaded",
            Video.created_at < cutoff_time
        ).all()
        
        cleaned_count = 0
        for video in old_uploaded_videos:
            if cleanup_video_file(video):
                cleaned_count += 1
        
        cleanup_logger.info(f"Manual cleanup by user {user_id}: cleaned {cleaned_count} files")
        
        return {
            "success": True,
            "cleaned_files": cleaned_count,
            "message": f"Cleaned up {cleaned_count} old uploaded video files"
        }
        
    except Exception as e:
        cleanup_logger.error(f"Error in manual cleanup for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Cleanup failed: {str(e)}")


def upload_video_to_youtube(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to YouTube - queries database directly"""
    # Get video from database
    videos = db_helpers.get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        youtube_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            db_helpers.update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            youtube_logger.error(error_msg)
            return
    
    # Get YouTube credentials from database
    youtube_token = db_helpers.get_oauth_token(user_id, "youtube", db=db)
    if not youtube_token:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="No YouTube credentials")
        youtube_logger.error("No YouTube credentials")
        return
    
    # Convert OAuth token to Google Credentials
    youtube_creds = db_helpers.oauth_token_to_credentials(youtube_token, db=db)
    if not youtube_creds:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="Failed to convert YouTube token to credentials")
        youtube_logger.error("Failed to convert YouTube token to credentials")
        return
    
    # Check if refresh_token is present (required for token refresh)
    if not youtube_creds.refresh_token:
        error_msg = 'YouTube refresh token is missing. Please disconnect and reconnect YouTube.'
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error=error_msg)
        youtube_logger.error(error_msg)
        return
    
    # Refresh token if expired (must be done before building YouTube client)
    if youtube_creds.expired:
        try:
            youtube_logger.debug("Refreshing expired YouTube token...")
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
                extra_data=token_data["extra_data"],
                db=db
            )
            youtube_logger.debug("YouTube token refreshed successfully")
        except Exception as refresh_error:
            error_msg = f'Failed to refresh YouTube token: {str(refresh_error)}. Please disconnect and reconnect YouTube.'
            db_helpers.update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            youtube_logger.error(error_msg, exc_info=True)
            return
    
    # Get settings from database
    youtube_settings = db_helpers.get_user_settings(user_id, "youtube", db=db)
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
    
    youtube_logger.info(f"Starting upload for {video.filename}")
    
    try:
        db_helpers.update_video(video_id, user_id, db=db, status="uploading")
        redis_client.set_upload_progress(user_id, video_id, 0)
        
        youtube_logger.debug("Building YouTube API client...")
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get video metadata
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        
        # Priority for title: generated_title > destination template > global template
        if video.generated_title:
            title = video.generated_title
        else:
            title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            title = replace_template_placeholders(
                title_template, 
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Enforce YouTube's 100 character limit for titles
        if len(title) > 100:
            title = title[:100]
        
        # Priority for description: destination template > global template
        desc_template = youtube_settings.get('description_template', '') or global_settings.get('description_template', 'Uploaded via Hopper')
        description = replace_template_placeholders(
            desc_template,
            filename_no_ext,
            global_settings.get('wordbank', [])
        )
        
        # Get visibility and made_for_kids from settings
        visibility = youtube_settings.get('visibility', 'private')
        made_for_kids = youtube_settings.get('made_for_kids', False)
        
        # Get tags from template
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
        # ROOT CAUSE FIX: Resolve path to absolute to ensure file is found
        video_path = Path(video.path).resolve()
        youtube_logger.debug(f"Video path: {video_path}")
        
        # Verify file exists before attempting upload
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        request = youtube.videos().insert(
            part='snippet,status',
            body={
                'snippet': snippet_body,
                'status': {
                    'privacyStatus': visibility,
                    'selfDeclaredMadeForKids': made_for_kids
                }
            },
            media_body=MediaFileUpload(str(video_path), resumable=True)
        )
        
        youtube_logger.info("Starting resumable upload...")
        response = None
        chunk_count = 0
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                redis_client.set_upload_progress(user_id, video_id, progress)
                chunk_count += 1
                if chunk_count % 10 == 0 or progress == 100:  # Log every 10 chunks or at completion
                    youtube_logger.info(f"Upload progress: {progress}%")
        
        # Update video in database with success
        db_helpers.update_video(video_id, user_id, db=db, status="uploaded", youtube_id=response['id'])
        redis_client.set_upload_progress(user_id, video_id, 100)
        youtube_logger.info(f"Successfully uploaded {video.filename}, YouTube ID: {response['id']}")
        
        # Increment successful uploads counter
        successful_uploads_counter.inc()
        
        # Deduct tokens after successful upload (only if not already deducted)
        if video.file_size_bytes and video.tokens_consumed == 0:
            tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
            deduct_tokens(
                user_id=user_id,
                tokens=tokens_required,
                transaction_type='upload',
                video_id=video.id,
                metadata={
                    'filename': video.filename,
                    'platform': 'youtube',
                    'youtube_id': response['id'],
                    'file_size_bytes': video.file_size_bytes,
                    'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                },
                db=db
            )
            # Update tokens_consumed in video record to prevent double-charging
            db_helpers.update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            youtube_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            youtube_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
    
    except Exception as e:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error=str(e))
        youtube_logger.error(f"Error uploading {video.filename}: {str(e)}", exc_info=True)
        redis_client.delete_upload_progress(user_id, video_id)


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
    current_count = redis_client.increment_rate_limit(identifier, TIKTOK_RATE_LIMIT_WINDOW)
    
    # Check if limit exceeded
    if current_count > TIKTOK_RATE_LIMIT_REQUESTS:
        # Calculate wait time (approximate, since we're using fixed window)
        wait_time = TIKTOK_RATE_LIMIT_WINDOW
        raise Exception(f"TikTok rate limit exceeded. Wait {wait_time}s before trying again.")


def get_tiktok_creator_info(access_token: str):
    """Query TikTok creator info"""
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
    
    # Extract and return
    creator_info = response_json.get("data", {})
    tiktok_logger.debug(f"Extracted creator_info keys: {list(creator_info.keys())}")
    tiktok_logger.debug(f"Extracted creator_info: {creator_info}")
    
    return creator_info


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


def upload_video_to_tiktok(user_id: int, video_id: int, db: Session = None, session_id: str = None):
    """Upload video to TikTok using Content Posting API - queries database directly"""
    # Get video from database
    videos = db_helpers.get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        tiktok_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            db_helpers.update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            tiktok_logger.error(error_msg)
            return
    
    # Get TikTok credentials from database
    tiktok_token = db_helpers.get_oauth_token(user_id, "tiktok", db=db)
    if not tiktok_token:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="No TikTok credentials")
        tiktok_logger.error("No TikTok credentials")
        return
    
    # Decrypt access token
    access_token = decrypt(tiktok_token.access_token)
    if not access_token:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="Failed to decrypt TikTok token")
        tiktok_logger.error("Failed to decrypt TikTok token")
        return
    
    # Get settings from database
    tiktok_settings = db_helpers.get_user_settings(user_id, "tiktok", db=db)
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
    
    try:
        db_helpers.update_video(video_id, user_id, db=db, status="uploading")
        redis_client.set_upload_progress(user_id, video_id, 0)
        
        # Check rate limit (use user_id if session_id not provided)
        check_tiktok_rate_limit(session_id=session_id, user_id=user_id)
        
        # Get creator info
        creator_info = get_tiktok_creator_info(access_token)
        
        # Get video file
        # ROOT CAUSE FIX: Resolve path to absolute to ensure file is found
        video_path = Path(video.path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        video_size = video_path.stat().st_size
        if video_size == 0:
            raise Exception("Video file is empty")
        
        # Prepare metadata
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        
        # Get title (priority: generated_title > template > filename)
        if video.generated_title:
            title = video.generated_title
        else:
            title_template = tiktok_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
            title = replace_template_placeholders(title_template, filename_no_ext, global_settings.get('wordbank', []))
        
        title = (title or filename_no_ext)[:2200]  # TikTok limit
        
        # Get settings with defaults
        privacy_level = tiktok_settings.get('privacy_level', 'public')
        tiktok_privacy = map_privacy_level_to_tiktok(privacy_level, creator_info)
        allow_comments = tiktok_settings.get('allow_comments', True)
        allow_duet = tiktok_settings.get('allow_duet', True)
        allow_stitch = tiktok_settings.get('allow_stitch', True)
        
        tiktok_logger.info(f"Uploading {video.filename} ({video_size / (1024*1024):.2f} MB)")
        redis_client.set_upload_progress(user_id, video_id, 5)
        
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
        redis_client.set_upload_progress(user_id, video_id, 10)
        
        # Step 2: Upload video file
        tiktok_logger.info("Uploading video file...")
        
        file_ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
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
        
        # Success - update video in database
        db_helpers.update_video(video_id, user_id, db=db, status="uploaded", tiktok_publish_id=publish_id, tiktok_id=publish_id)
        redis_client.set_upload_progress(user_id, video_id, 100)
        tiktok_logger.info(f"Success! publish_id: {publish_id}")
        
        # Increment successful uploads counter
        successful_uploads_counter.inc()
        
        # Deduct tokens after successful upload (only if not already deducted)
        if video.file_size_bytes and video.tokens_consumed == 0:
            tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
            deduct_tokens(
                user_id=user_id,
                tokens=tokens_required,
                transaction_type='upload',
                video_id=video.id,
                metadata={
                    'filename': video.filename,
                    'platform': 'tiktok',
                    'tiktok_publish_id': publish_id,
                    'file_size_bytes': video.file_size_bytes,
                    'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                },
                db=db
            )
            # Update tokens_consumed in video record to prevent double-charging
            db_helpers.update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            tiktok_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            tiktok_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
        
    except Exception as e:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error=f'TikTok upload failed: {str(e)}')
        tiktok_logger.error(f"Upload error: {str(e)}", exc_info=True)
        redis_client.delete_upload_progress(user_id, video_id)
            
async def upload_video_to_instagram(user_id: int, video_id: int, db: Session = None):
    """Upload video to Instagram using Graph API - queries database directly"""
    # Get video from database
    videos = db_helpers.get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        instagram_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.file_size_bytes and video.tokens_consumed == 0:
        tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
        if not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            db_helpers.update_video(video_id, user_id, db=db, status="failed", error=error_msg)
            instagram_logger.error(error_msg)
            return
    
    # Get Instagram credentials from database
    instagram_token = db_helpers.get_oauth_token(user_id, "instagram", db=db)
    if not instagram_token:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="No Instagram credentials")
        instagram_logger.error("No Instagram credentials")
        return
    
    # Decrypt access token
    access_token = decrypt(instagram_token.access_token)
    if not access_token:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="Failed to decrypt Instagram token")
        instagram_logger.error("Failed to decrypt Instagram token")
        return
    
    # Get business account ID from extra_data
    extra_data = instagram_token.extra_data or {}
    business_account_id = extra_data.get("business_account_id")
    if not business_account_id:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error="No Instagram Business Account ID. Please reconnect your Instagram account.")
        instagram_logger.error("No Instagram Business Account ID")
        return
    
    # Get settings from database
    instagram_settings = db_helpers.get_user_settings(user_id, "instagram", db=db)
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
    
    instagram_logger.info(f"Starting upload for {video.filename}")
    instagram_logger.debug(f"Using access token: {access_token[:20]}... (length: {len(access_token)})")
    instagram_logger.debug(f"Using business account ID: {business_account_id}")
    
    try:
        db_helpers.update_video(video_id, user_id, db=db, status="uploading")
        redis_client.set_upload_progress(user_id, video_id, 0)
        
        # Get video file
        # ROOT CAUSE FIX: Resolve path to absolute to ensure file is found
        video_path = Path(video.path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        # Prepare caption
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        
        # Get caption (priority: generated_title > template > filename)
        if video.generated_title:
            caption = video.generated_title
        else:
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
        
        instagram_logger.info(f"Uploading {video.filename} to Instagram")
        redis_client.set_upload_progress(user_id, video_id, 10)
        
        # Instagram Graph API video upload process (per official docs):
        # 1. Create a container with media_type=REELS and upload_type=resumable
        # 2. Upload video to rupload.facebook.com
        # 3. Check container status
        # 4. Publish the container
        
        # Read video file
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        video_size = len(video_data)
        redis_client.set_upload_progress(user_id, video_id, 20)
        
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
            
            instagram_logger.info(f"Creating resumable upload container for {video.filename}")
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
            db_helpers.update_video(video_id, user_id, db=db, instagram_container_id=container_id)
            redis_client.set_upload_progress(user_id, video_id, 40)
            
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
            redis_client.set_upload_progress(user_id, video_id, 70)
            
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
            
            redis_client.set_upload_progress(user_id, video_id, 85)
            
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
            
            # Update video in database with success
            db_helpers.update_video(video_id, user_id, db=db, status="completed", instagram_id=media_id)
            redis_client.set_upload_progress(user_id, video_id, 100)
            
            # Increment successful uploads counter
            successful_uploads_counter.inc()
            
            # Deduct tokens after successful upload (only if not already deducted)
            if video.file_size_bytes and video.tokens_consumed == 0:
                tokens_required = calculate_tokens_from_bytes(video.file_size_bytes)
                deduct_tokens(
                    user_id=user_id,
                    tokens=tokens_required,
                    transaction_type='upload',
                    video_id=video.id,
                    metadata={
                        'filename': video.filename,
                        'platform': 'instagram',
                        'instagram_id': media_id,
                        'file_size_bytes': video.file_size_bytes,
                        'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                    },
                    db=db
                )
                # Update tokens_consumed in video record to prevent double-charging
                db_helpers.update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
                instagram_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
            else:
                instagram_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
            
            # Clean up progress after a delay
            await asyncio.sleep(2)
            redis_client.delete_upload_progress(user_id, video_id)
        
    except Exception as e:
        db_helpers.update_video(video_id, user_id, db=db, status="failed", error=f'Instagram upload failed: {str(e)}')
        instagram_logger.error(f"Error uploading {video.filename}: {str(e)}", exc_info=True)
        redis_client.delete_upload_progress(user_id, video_id)

# Register upload functions
DESTINATION_UPLOADERS["youtube"] = upload_video_to_youtube
DESTINATION_UPLOADERS["tiktok"] = upload_video_to_tiktok
DESTINATION_UPLOADERS["instagram"] = upload_video_to_instagram

async def cleanup_task():
    """Background task that cleans up old uploaded videos and orphaned files
    
    Runs every hour to:
    1. Delete video files for videos uploaded more than 24 hours ago
    2. Remove orphaned files (files on disk without database records)
    """
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            from models import SessionLocal, Video
            db = SessionLocal()
            try:
                cleanup_logger.info("Starting cleanup task...")
                
                # 1. Clean up old uploaded videos (older than 24 hours)
                # ROOT CAUSE FIX: Only clean up videos that:
                # - Have status "uploaded" (never touch pending, scheduled, uploading, or failed)
                # - Were never scheduled (scheduled_time is None) - protects scheduled videos even after upload
                # - Are older than 24 hours (based on created_at)
                # This ensures scheduled videos are NEVER cleaned before or after upload
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                old_uploaded_videos = db.query(Video).filter(
                    Video.status == "uploaded",  # Only uploaded videos
                    Video.scheduled_time.is_(None),  # Never delete files from videos that were scheduled
                    Video.created_at < cutoff_time  # Only old videos
                ).all()
                
                cleaned_count = 0
                for video in old_uploaded_videos:
                    if cleanup_video_file(video):
                        cleaned_count += 1
                
                if cleaned_count > 0:
                    cleanup_logger.info(f"Cleaned up {cleaned_count} old uploaded video files")
                
                # 2. Find and remove orphaned files (files without database records)
                # IMPORTANT: Exclude files that belong to scheduled videos to prevent deletion before upload
                if UPLOAD_DIR.exists():
                    all_files = set(UPLOAD_DIR.glob("*"))
                    # Get all video paths from database - include ALL videos (scheduled, pending, etc.)
                    # ROOT CAUSE FIX: Resolve all paths to absolute to ensure proper comparison
                    all_video_paths = set(Path(v.path).resolve() for v in db.query(Video).all())
                    
                    # Also explicitly get paths of scheduled videos as extra protection
                    scheduled_video_paths = set(
                        Path(v.path).resolve() for v in db.query(Video).filter(
                            Video.status == "scheduled"
                        ).all()
                    )
                    
                    orphaned_files = all_files - all_video_paths
                    orphaned_count = 0
                    for orphaned_file in orphaned_files:
                        # Extra safety: double-check this file doesn't belong to a scheduled video
                        if orphaned_file in scheduled_video_paths:
                            cleanup_logger.warning(f"Skipping file that belongs to scheduled video: {orphaned_file.name}")
                            continue
                            
                        if orphaned_file.is_file():
                            try:
                                orphaned_file.unlink()
                                orphaned_count += 1
                                cleanup_files_removed_counter.inc()
                                cleanup_logger.info(f"Removed orphaned file: {orphaned_file.name}")
                            except Exception as e:
                                cleanup_logger.error(f"Failed to remove orphaned file {orphaned_file.name}: {e}")
                    
                    # Update orphaned videos metric (count remaining orphaned files)
                    remaining_orphaned = len([f for f in (all_files - all_video_paths) if f.is_file() and f not in scheduled_video_paths])
                    orphaned_videos_gauge.set(remaining_orphaned)
                    
                    if orphaned_count > 0:
                        cleanup_logger.info(f"Removed {orphaned_count} orphaned files")
                
                # Update storage metrics
                try:
                    if UPLOAD_DIR.exists():
                        total_size = sum(f.stat().st_size for f in UPLOAD_DIR.glob("*") if f.is_file())
                        storage_size_gauge.labels(type="upload_dir").set(total_size)
                except Exception as e:
                    cleanup_logger.warning(f"Failed to calculate storage size: {e}")
                
                cleanup_runs_counter.labels(status="success").inc()
                cleanup_logger.info("Cleanup task completed")
                
            finally:
                db.close()
                
        except Exception as e:
            cleanup_logger.error(f"Error in cleanup task: {e}", exc_info=True)
            cleanup_runs_counter.labels(status="failure").inc()
            await asyncio.sleep(3600)

async def update_metrics_task():
    """Background task that updates Prometheus metrics periodically"""
    while True:
        try:
            await asyncio.sleep(30)  # Update every 30 seconds
            
            from models import SessionLocal, User, Video
            import redis_client as redis_module
            db = SessionLocal()
            try:
                # Active users: count unique users with active sessions in Redis
                # Sessions are stored as "session:{session_id}" with user_id as value
                # Only count sessions that actually exist (not expired)
                session_keys = redis_module.redis_client.keys("session:*")
                active_user_ids = set()
                for key in session_keys:
                    user_id = redis_module.redis_client.get(key)
                    if user_id:  # Only count if session exists (not expired)
                        try:
                            active_user_ids.add(int(user_id))
                        except (ValueError, TypeError):
                            # Skip invalid user_id values
                            continue
                active_users = len(active_user_ids)
                active_users_gauge.set(active_users)
                
                # Active subscriptions by plan type
                subscriptions = db.query(Subscription).filter(Subscription.status == 'active').all()
                # Reset all plan types to 0 first
                for plan_type in ['free', 'medium', 'pro', 'unlimited']:
                    active_subscriptions_gauge.labels(plan_type=plan_type).set(0)
                # Set current counts
                plan_counts = {}
                for sub in subscriptions:
                    plan_type = sub.plan_type or 'free'
                    plan_counts[plan_type] = plan_counts.get(plan_type, 0) + 1
                for plan_type, count in plan_counts.items():
                    active_subscriptions_gauge.labels(plan_type=plan_type).set(count)
                
                # Note: current_uploads_gauge removed - replaced with successful_uploads_counter
                
                # Queued uploads: videos with status "pending"
                queued_uploads = db.query(Video).filter(Video.status == "pending").count()
                queued_uploads_gauge.set(queued_uploads)
                
                # Scheduled uploads: videos with status "scheduled"
                scheduled_uploads = db.query(Video).filter(Video.status == "scheduled").count()
                scheduled_uploads_gauge.set(scheduled_uploads)
                
                # Failed uploads: videos with status "failed"
                failed_uploads = db.query(Video).filter(Video.status == "failed").count()
                failed_uploads_gauge.set(failed_uploads)
                
                # Per-user upload metrics: reset all to 0 first, then set current values
                # This prevents stale metrics from users who no longer have uploads
                try:
                    user_uploads_gauge.clear()
                except AttributeError:
                    # clear() only works for labeled metrics, but if it doesn't exist yet, that's fine
                    pass
                
                # Get all users with active uploads (uploading, pending, scheduled, failed)
                user_uploads = db.query(
                    User.id,
                    User.email,
                    Video.status,
                    func.count(Video.id).label('count')
                ).join(Video).filter(
                    Video.status.in_(["uploading", "pending", "scheduled", "failed"])
                ).group_by(User.id, User.email, Video.status).all()
                
                # Set metrics for each user/status combination
                for user_id, user_email, status, count in user_uploads:
                    user_uploads_gauge.labels(
                        user_id=str(user_id),
                        user_email=user_email or f"user_{user_id}",
                        status=status
                    ).set(count)
                
                # Get scheduled uploads with scheduled_time and created_at for detailed view
                try:
                    scheduled_uploads_detail_gauge.clear()
                except AttributeError:
                    pass
                
                scheduled_videos = db.query(
                    User.id,
                    User.email,
                    Video.filename,
                    Video.scheduled_time,
                    Video.created_at,
                    Video.status
                ).join(Video).filter(
                    Video.status == "scheduled",
                    Video.scheduled_time.isnot(None)
                ).all()
                
                # Set metrics for each scheduled video
                for user_id, user_email, filename, scheduled_time, created_at, status in scheduled_videos:
                    scheduled_time_str = scheduled_time.isoformat() if scheduled_time else ""
                    created_at_str = created_at.isoformat() if created_at else ""
                    scheduled_uploads_detail_gauge.labels(
                        user_id=str(user_id),
                        user_email=user_email or f"user_{user_id}",
                        filename=filename or "",
                        scheduled_time=scheduled_time_str,
                        created_at=created_at_str,
                        status=status or "scheduled"
                    ).set(1)
                
            except Exception as e:
                logger.error(f"Error updating metrics: {e}", exc_info=True)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in metrics update task: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait longer on error

async def scheduler_task():
    """Background task that checks for scheduled videos and uploads them to all enabled destinations
    Optimized to use batch queries instead of querying per user/video"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = datetime.now(timezone.utc)
            
            # Batch query: Get all scheduled videos across all users in a single query
            from models import SessionLocal, Video
            db = SessionLocal()
            try:
                # Single query to get all scheduled videos, grouped by user_id
                videos_by_user = db_helpers.get_all_scheduled_videos(db=db)
                
                videos_processed = 0
                # Process videos grouped by user (allows batch loading of user settings/tokens)
                for user_id, videos in videos_by_user.items():
                    # Build upload context (enabled destinations, settings, tokens)
                    upload_context = build_upload_context(user_id, db)
                    enabled_destinations = upload_context["enabled_destinations"]
                    
                    if not enabled_destinations:
                        # Skip this user if no destinations are enabled
                        continue
                    
                    # Process each scheduled video for this user
                    for video in videos:
                        try:
                            scheduled_time = datetime.fromisoformat(video.scheduled_time) if isinstance(video.scheduled_time, str) else video.scheduled_time
                            
                            # ROOT CAUSE FIX: Upload if scheduled time has passed
                            # This handles both:
                            # 1. Videos scheduled for future upload (status="scheduled")
                            # 2. Videos that were uploading when server restarted (status="uploading")
                            if current_time >= scheduled_time:
                                video_id = video.id
                                videos_processed += 1
                                scheduler_videos_processed_counter.inc()
                                
                                # Log whether this is a retry or new upload
                                if video.status == "uploading":
                                    upload_logger.info(f"Retrying upload for video that was in progress: {video.filename} (user {user_id})")
                                else:
                                    upload_logger.info(f"Uploading scheduled video for user {user_id}: {video.filename}")
                                
                                # Mark as uploading - use shared session
                                # This is idempotent - safe to call even if already "uploading"
                                db_helpers.update_video(video_id, user_id, db=db, status="uploading")
                                
                                # Upload to each enabled destination - uploader functions query DB directly
                                # Note: Upload functions create their own sessions (backward compatible)
                                success_count = 0
                                for dest_name in enabled_destinations:
                                    uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                                    if uploader_func:
                                        try:
                                            print(f"  Uploading to {dest_name}...")
                                            # Pass user_id and video_id - uploader functions query DB directly
                                            if dest_name == "instagram":
                                                await uploader_func(user_id, video_id)
                                            else:
                                                uploader_func(user_id, video_id)
                                            
                                            # Expire the video object from this session to force fresh query
                                            # The upload function uses its own session, so we need to refresh
                                            db.expire_all()
                                            
                                            # Check if upload succeeded by querying updated video - use shared session
                                            # Note: We could optimize this further by caching the video object, but for now
                                            # we'll query to ensure we have the latest state
                                            updated_video = db.query(Video).filter(Video.id == video_id).first()
                                            if updated_video and check_upload_success(updated_video, dest_name):
                                                success_count += 1
                                        except Exception as upload_err:
                                            print(f"  Error uploading to {dest_name}: {upload_err}")
                                
                                # Update final status - use shared session
                                if success_count == len(enabled_destinations):
                                    db_helpers.update_video(video_id, user_id, db=db, status="uploaded")
                                    
                                    # Increment successful uploads counter
                                    successful_uploads_counter.inc()
                                    
                                    # Cleanup: Delete video file after successful upload to all destinations
                                    # Keep database record for history
                                    updated_video = db.query(Video).filter(Video.id == video_id).first()
                                    if updated_video:
                                        cleanup_video_file(updated_video)
                                else:
                                    db_helpers.update_video(video_id, user_id, db=db, status="failed", error=f"Upload failed for some destinations")
                                    
                        except Exception as e:
                            print(f"Error processing scheduled video {video.filename}: {e}")
                            if 'video_id' in locals():
                                db_helpers.update_video(video_id, user_id, db=db, status="failed", error=str(e))
                
                scheduler_runs_counter.labels(status="success").inc()
            finally:
                db.close()
        except Exception as e:
            print(f"Error in scheduler task: {e}")
            scheduler_runs_counter.labels(status="failure").inc()
            await asyncio.sleep(30)


async def token_reset_scheduler_task():
    """Background task to reset tokens for subscriptions that have reached their period end"""
    logger.info("Starting token reset scheduler task...")
    
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                
                # Find subscriptions that need token reset (period_end has passed, but tokens not reset)
                # This handles both Stripe subscriptions (renewed via webhooks) and free subscriptions (renewed manually)
                subscriptions = db.query(Subscription).filter(
                    Subscription.status == 'active',
                    Subscription.current_period_end <= now
                ).all()
                
                for subscription in subscriptions:
                    # Check if tokens have been reset for this period
                    balance = db.query(TokenBalance).filter(
                        TokenBalance.user_id == subscription.user_id
                    ).first()
                    
                    # Reset if period_end has passed and last_reset_at is before period_end
                    should_reset = False
                    is_renewal = False
                    if not balance:
                        should_reset = True
                        is_renewal = False  # New subscription, add tokens
                    elif not balance.last_reset_at:
                        should_reset = True
                        is_renewal = False  # First time setup, add tokens
                    elif balance.last_reset_at < subscription.current_period_end:
                        should_reset = True
                        # Check if this is a renewal: if token balance period_end exists and is different from subscription period_end
                        # This indicates the subscription period has moved forward (renewal)
                        if balance.period_end and balance.period_end != subscription.current_period_end:
                            # Period changed - check if it's a renewal
                            # Use the same logic as handle_subscription_renewal: period advanced by at least 20 days
                            period_diff_days = (subscription.current_period_end - balance.period_end).total_seconds() / 86400
                            if 20 <= period_diff_days < 365:  # Reasonable billing cycle (monthly, bi-monthly, quarterly, etc.)
                                is_renewal = True
                            else:
                                is_renewal = False  # Period changed but not by a reasonable amount (plan switch or other)
                        else:
                            is_renewal = False  # First time for this period, but not a renewal
                    
                    if should_reset:
                        # For free subscriptions, we need to update the period dates when renewing
                        # Stripe subscriptions have their periods updated via webhooks
                        period_start = subscription.current_period_start
                        period_end = subscription.current_period_end
                        
                        # If period has ended, calculate new period (for free plans or missed renewals)
                        if subscription.current_period_end <= now:
                            # Calculate new period: extend by one month from current period_end
                            from datetime import timedelta
                            period_start = subscription.current_period_end
                            # Add approximately one month (30 days)
                            period_end = period_start + timedelta(days=30)
                            
                            # Update subscription period (especially important for free plans)
                            subscription.current_period_start = period_start
                            subscription.current_period_end = period_end
                            subscription.updated_at = now
                            db.flush()  # Flush to ensure period is updated before token reset
                            
                            logger.info(f"Updated subscription period for user {subscription.user_id}: {period_start} -> {period_end}")
                        
                        logger.info(f"Resetting tokens for user {subscription.user_id} (subscription {subscription.id}, plan: {subscription.plan_type}), is_renewal={is_renewal}")
                        reset_tokens_for_subscription(
                            subscription.user_id,
                            subscription.plan_type,
                            period_start,
                            period_end,
                            db,
                            is_renewal=is_renewal
                        )
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error in token reset scheduler: {e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Fatal error in token reset scheduler: {e}", exc_info=True)
            await asyncio.sleep(3600)  # Wait before retrying

# Scheduler startup is now handled in the lifespan event handler above

@app.post("/api/upload")
async def upload_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Upload all pending videos to all enabled destinations (immediate or scheduled)"""
    
    # Check if at least one destination is enabled and connected
    enabled_destinations = []
    
    upload_logger.debug(f"Checking destinations for user {user_id}...")
    
    # Build upload context (enabled destinations, settings, tokens)
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    destination_settings = upload_context["dest_settings"]
    all_tokens = upload_context["all_tokens"]
    
    upload_logger.info(f"Enabled destinations for user {user_id}: {enabled_destinations}")
    
    if not enabled_destinations:
        error_msg = "No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        upload_logger.error(error_msg)
        raise HTTPException(400, error_msg)
    
    # Get videos that can be uploaded: pending, failed (retry), or uploading (retry if stuck)
    user_videos = db_helpers.get_user_videos(user_id, db=db)
    pending_videos = [v for v in user_videos if v.status in ['pending', 'failed', 'uploading']]
    
    upload_logger.info(f"Videos ready to upload for user {user_id}: {len(pending_videos)}")
    
    # Get global settings for upload behavior
    global_settings = db_helpers.get_user_settings(user_id, "global", db=db)
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
            db_helpers.update_video(video_id, user_id, db=db, status="uploading")
            
            # Track which destinations succeeded/failed
            succeeded_destinations = []
            failed_destinations = []
            
            # Upload to all enabled destinations - uploader functions query DB directly
            for dest_name in enabled_destinations:
                uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                if uploader_func:
                    upload_logger.info(f"Uploading {video.filename} to {dest_name} for user {user_id}")
                    
                    try:
                        # Pass user_id, video_id, and db session - uploader functions query DB directly
                        if dest_name == "instagram":
                            await uploader_func(user_id, video_id, db=db)
                        else:
                            uploader_func(user_id, video_id, db=db)
                        
                        # Assume success for now, will verify after all uploads complete to avoid N+1 queries
                        succeeded_destinations.append(dest_name)
                    except Exception as e:
                        failed_destinations.append(dest_name)
                        upload_logger.error(f"{dest_name} upload exception for {video.filename}: {str(e)}")
                        db_helpers.update_video(video_id, user_id, db=db, error=str(e))
            
            # Determine final status based on results
            # Refresh video in current session to get latest changes (prevents stale data)
            db.refresh(video)
            updated_video = video
            
            # Verify which destinations actually succeeded
            verified_succeeded = []
            verified_failed = []
            for dest_name in succeeded_destinations:
                if updated_video:
                    if check_upload_success(updated_video, dest_name):
                        verified_succeeded.append(dest_name)
                        upload_logger.info(f"{dest_name.capitalize()} upload succeeded for {video.filename}")
                    else:
                        verified_failed.append(dest_name)
                        upload_logger.error(f"{dest_name} upload failed for {video.filename}")
                else:
                    verified_failed.append(dest_name)
                    upload_logger.error(f"{dest_name} upload failed - video not found")
            
            # Update succeeded/failed lists
            succeeded_destinations = verified_succeeded
            failed_destinations.extend(verified_failed)
            
            if updated_video:
                update_data = {}
                if len(succeeded_destinations) == len(enabled_destinations):
                    update_data['status'] = 'uploaded'
                    update_data['error'] = None
                    
                    # Increment successful uploads counter
                    successful_uploads_counter.inc()
                    
                    # Cleanup: Delete video file after successful upload to all destinations
                    # Keep database record for history
                    cleanup_video_file(updated_video)
                elif len(succeeded_destinations) > 0:
                    update_data['status'] = 'failed'
                    update_data['error'] = f"Partial upload: succeeded ({', '.join(succeeded_destinations)}), failed ({', '.join(failed_destinations)})"
                else:
                    update_data['status'] = 'failed'
                    if not updated_video.error:
                        update_data['error'] = f"Upload failed for all destinations: {', '.join(failed_destinations)}"
                
                # Update video in database with final status
                if update_data:
                    db_helpers.update_video(video_id, user_id, db=db, **update_data)
        
        # Count videos that are fully uploaded
        user_videos_updated = db_helpers.get_user_videos(user_id, db=db)
        uploaded_count = len([v for v in user_videos_updated if v.status == 'uploaded'])
        return {
            "uploaded": uploaded_count,
            "message": f"Videos uploaded immediately to: {', '.join(enabled_destinations)}"
        }
    
    # Otherwise, mark for scheduled upload
    schedule_mode = global_settings.get("schedule_mode", "immediate")
    
    if schedule_mode == 'spaced':
        # Calculate interval in minutes
        # Ensure value is an integer (may come from DB as string or None)
        value_raw = global_settings.get("schedule_interval_value")
        if value_raw is None or value_raw == "":
            value = 1  # Default to 1 hour (matching db_helpers default)
        else:
            value = int(value_raw)
        unit = global_settings.get("schedule_interval_unit", "hours")
        
        upload_logger.info(f"Scheduling with interval: {value} {unit} (user {user_id})")
        
        if unit == 'minutes':
            interval_minutes = value
        elif unit == 'hours':
            interval_minutes = value * 60
        elif unit == 'days':
            interval_minutes = value * 1440
        else:
            interval_minutes = 60  # default to 1 hour
        
        upload_logger.info(f"Calculated interval: {interval_minutes} minutes ({interval_minutes / 60:.1f} hours)")
        
        # Check if first video should upload immediately or be offset
        upload_first_immediately = global_settings.get("upload_first_immediately", True)
        
        # Set scheduled time for each video (use timezone-aware datetime)
        current_time = datetime.now(timezone.utc)
        for i, video in enumerate(pending_videos):
            video_id = video.id
            # If upload_first_immediately is True, first video (i=0) uploads immediately
            # If False, first video is also offset by the interval
            if upload_first_immediately:
                offset_multiplier = i  # First video: 0, second: 1, third: 2, etc.
            else:
                offset_multiplier = i + 1  # First video: 1, second: 2, third: 3, etc.
            
            scheduled_time = current_time + timedelta(minutes=interval_minutes * offset_multiplier)
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

# Note: Terms and Privacy pages are served by the frontend React app at /terms and /privacy
# No backend routes needed - handled by React Router and Terms.js/Privacy.js components

if __name__ == "__main__":
    # Use reload=True in development for hot reload
    # Must pass app as import string for reload to work
    reload = os.getenv("ENVIRONMENT", "development") == "development"
    
    # Configure uvicorn for large file uploads
    # - timeout_keep_alive: Keep connections alive for 30 minutes (for very large uploads)
    # - timeout_graceful_shutdown: Allow 30 seconds for graceful shutdown
    # - limit_concurrency: Allow up to 100 concurrent connections
    # - limit_max_requests: No limit on requests per worker
    # Note: Starlette/FastAPI default max request body size is 1MB, but we handle streaming
    # For very large files, we need to ensure timeouts are sufficient
    # IMPORTANT: If behind Cloudflare or other proxy, their timeout may be shorter:
    # - Cloudflare Free: 100 seconds
    # - Cloudflare Paid: 600 seconds (10 minutes)
    # - Consider using Cloudflare Workers or direct connection for large uploads
    config = {
        "host": "0.0.0.0",
        "port": 8000,
        "timeout_keep_alive": 1800,  # 30 minutes - keep connections alive for very large uploads
        "timeout_graceful_shutdown": 30,
        "limit_concurrency": 100,
        "limit_max_requests": None,  # No limit
    }
    
    if reload:
        config["reload"] = True
        uvicorn.run("main:app", **config)
    else:
        uvicorn.run(app, **config)

