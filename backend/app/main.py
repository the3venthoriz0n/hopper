"""FastAPI application entry point"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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

from app.core.config import settings
from app.db.session import engine, init_db
from app.db.redis import redis_client
from app.models import Base  # Import all models to register with Base.metadata
from app.core.security import (
    get_client_identifier, check_rate_limit,
    validate_origin_referer, log_api_access
)

# Import routers
from app.api import auth, oauth, videos, subscriptions, tokens, admin
from app.api import settings as settings_router

# Configure logging
LOG_LEVEL = settings.LOG_LEVEL.upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)

# Silence noisy third-party libraries
logging.getLogger("stripe").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Create specific loggers
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
tiktok_logger = logging.getLogger("tiktok")
youtube_logger = logging.getLogger("youtube")
instagram_logger = logging.getLogger("instagram")
security_logger = logging.getLogger("security")
api_access_logger = logging.getLogger("api_access")


def initialize_otel():
    """Initialize OpenTelemetry providers"""
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return False
    
    try:
        resource = Resource.create({
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": "1.0.0",
            "deployment.environment": settings.OTEL_ENVIRONMENT
        })

        # Trace provider
        trace_provider = TracerProvider(resource=resource)
        otlp_trace_exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True
        )
        trace_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))
        trace.set_tracer_provider(trace_provider)

        # Metrics provider
        otlp_metric_exporter = OTLPMetricExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
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
        logger.warning(f"Failed to initialize OpenTelemetry: {e}")
        return False


def setup_otel_logging():
    """Setup OTEL logging handler"""
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return False
        
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource as LogResource
        
        log_resource = LogResource.create({
            "service.name": settings.OTEL_SERVICE_NAME,
            "deployment.environment": settings.OTEL_ENVIRONMENT
        })
        logger_provider = LoggerProvider(resource=log_resource)
        set_logger_provider(logger_provider)
        
        log_exporter = OTLPLogExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True
        )
        log_processor = BatchLogRecordProcessor(
            log_exporter,
            max_queue_size=2048,
            export_timeout_millis=30000,
            schedule_delay_millis=5000
        )
        logger_provider.add_log_record_processor(log_processor)
        
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        logging.getLogger().addHandler(handler)
        
        return True
    except Exception as e:
        logger.warning(f"Failed to setup OTEL logging: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    otel_initialized = initialize_otel()
    otel_logging_initialized = False
    
    if otel_initialized:
        otel_logging_initialized = setup_otel_logging()
        if otel_logging_initialized:
            logger.info(f"OpenTelemetry fully initialized, exporting to {settings.OTEL_EXPORTER_OTLP_ENDPOINT}")
        else:
            logger.warning("OpenTelemetry metrics/traces initialized but logging setup failed")
    else:
        logger.info("OpenTelemetry not configured - running without distributed tracing")
    
    logger.info("Initializing database...")
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    logger.info("Testing Redis connection...")
    try:
        redis_client.ping()
        logger.info("Redis connection successful")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise
    
    # Instrument SQLAlchemy
    try:
        SQLAlchemyInstrumentor().instrument(engine=engine)
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as e:
        logger.warning(f"Failed to instrument SQLAlchemy: {e}")
    
    # Start background tasks
    logger.info("Starting scheduler tasks...")
    from app.tasks.scheduler import scheduler_task, token_reset_scheduler_task
    from app.tasks.cleanup import cleanup_task
    
    asyncio.create_task(scheduler_task())
    asyncio.create_task(token_reset_scheduler_task())
    logger.info("Scheduler tasks started")
    
    # Start the cleanup task
    logger.info("Starting cleanup task...")
    asyncio.create_task(cleanup_task())
    logger.info("Cleanup task started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Hopper Backend",
    description="Video upload and distribution platform",
    version="1.0.0",
    lifespan=lifespan
)

# Instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)

# Instrument HTTPX
HTTPXClientInstrumentor().instrument()

# CORS middleware
allowed_origins = [settings.FRONTEND_URL]
if settings.ENVIRONMENT == "development":
    allowed_origins.extend([
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000"
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(oauth.destinations_router)  # Separate router for /api/destinations
app.include_router(settings_router.router)
app.include_router(videos.router)
app.include_router(videos.upload_router)  # Separate router for /api/upload
app.include_router(subscriptions.router)
app.include_router(subscriptions.stripe_router)  # Separate router for /api/stripe
app.include_router(tokens.router)
app.include_router(admin.router)

# Security middleware
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Middleware for security checks and API access logging"""
    session_id = None
    status_code = 500
    error = None
    
    try:
        path = request.url.path
        is_callback = (
            "/api/auth/google/login/callback" in path or
            "/api/auth/youtube/callback" in path or
            "/api/auth/tiktok/callback" in path or
            "/api/auth/instagram/callback" in path
        )
        
        is_public_endpoint = (
            path == "/api/auth/csrf" or
            path == "/api/auth/register" or
            path == "/api/auth/login" or
            path == "/api/auth/logout" or
            path == "/api/auth/me" or
            path == "/api/auth/google/login" or
            path == "/api/subscriptions/webhook" or
            path == "/metrics" or
            path == "/health"
        )
        
        is_video_file_endpoint = path.startswith("/api/videos/") and path.endswith("/file")
        
        session_id = request.cookies.get("session_id")
        
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
            if not is_public_endpoint and not is_video_file_endpoint and request.method != "OPTIONS" and (request.method != "GET" or settings.ENVIRONMENT == "production"):
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
        
        # FIX: Remove 'request.method == "GET"' so token is sent on POST/PUT too
        if session_id and not is_callback and status_code < 400:
            from app.db.redis import get_csrf_token, set_csrf_token
            import secrets
            
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


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


# Prometheus metrics endpoint
@app.get("/metrics")
def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Health check endpoint
@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

