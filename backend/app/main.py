"""FastAPI application entry point"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
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

# Configure logging first
setup_logging()
logger = get_logger(__name__)

# Import routers
from app.api import auth, oauth, videos, subscriptions, tokens, admin, monitoring, email, websocket
from app.api import settings as settings_router


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
    
    # Validate email service configuration
    from app.services.email_service import validate_email_config
    
    is_valid, error = validate_email_config()
    if not is_valid:
        logger.warning(f"Email service not configured: {error}")
        logger.warning("Password reset emails will not be sent")
    else:
        logger.info("Email service configured successfully")
    
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
    
    # Start WebSocket manager Redis subscription
    logger.info("Starting WebSocket manager...")
    from app.services.websocket_service import websocket_manager
    asyncio.create_task(websocket_manager.start_listening())
    logger.info("WebSocket manager started")
    
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
app.include_router(settings_router.destinations_router)  # Separate router for /api/destinations
app.include_router(settings_router.router)
app.include_router(videos.router)
app.include_router(videos.upload_router)  # Separate router for /api/upload
app.include_router(subscriptions.router)
app.include_router(subscriptions.stripe_router)  # Separate router for /api/stripe
app.include_router(tokens.router)
app.include_router(admin.router)
app.include_router(monitoring.router)
app.include_router(email.router)
app.include_router(websocket.router)

# Security middleware
app.middleware("http")(security_middleware)

# Global exception handler
app.exception_handler(Exception)(global_exception_handler)
