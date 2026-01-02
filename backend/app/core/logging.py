"""Logging configuration for the application"""
import logging

from app.core.config import settings


def setup_logging():
    """Configure logging for the application"""
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


# Create specific loggers (available after setup_logging() is called)
def get_logger(name: str = __name__):
    """Get a logger by name"""
    return logging.getLogger(name)


# Export commonly used loggers
# These will be created when the module is imported, after setup_logging() is called
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
tiktok_logger = logging.getLogger("tiktok")
youtube_logger = logging.getLogger("youtube")
instagram_logger = logging.getLogger("instagram")
security_logger = logging.getLogger("security")
api_access_logger = logging.getLogger("api_access")
