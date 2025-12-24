"""FastAPI application entry point"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.otel import (
    initialize_otel, setup_otel_logging,
    instrument_fastapi, instrument_httpx, instrument_sqlalchemy
)
from app.core.middleware import (
    setup_cors_middleware, security_middleware, global_exception_handler
)
from app.db.session import engine, init_db
from app.db.redis import redis_client
from app.models import Base  # Import all models to register with Base.metadata

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
    instrument_sqlalchemy(engine)
    
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
instrument_fastapi(app)

# Instrument HTTPX
instrument_httpx()

# Setup CORS middleware
setup_cors_middleware(app)

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
app.middleware("http")(security_middleware)

# Global exception handler
app.exception_handler(Exception)(global_exception_handler)


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

