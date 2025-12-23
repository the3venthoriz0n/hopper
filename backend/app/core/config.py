"""Application configuration using Pydantic BaseSettings"""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    DATABASE_URL: str = "postgresql://hopper:hopper_dev_password@localhost:5432/hopper"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Domain & URLs
    DOMAIN: str = "localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    # OpenTelemetry
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "hopper-backend"
    OTEL_ENVIRONMENT: str = "development"
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_PROJECT_ID: str = ""
    
    # TikTok OAuth
    TIKTOK_CLIENT_KEY: str = ""
    TIKTOK_CLIENT_SECRET: str = ""
    
    # Instagram/Facebook OAuth
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    
    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    
    # Email (Resend)
    RESEND_API_KEY: str = ""
    
    # Security
    SECRET_KEY: str = ""  # For session encryption
    CSRF_SECRET: str = ""  # For CSRF tokens
    ENCRYPTION_KEY: str = ""  # For OAuth token encryption
    
    # File uploads
    UPLOAD_DIR: Path = Path("uploads").resolve()
    MAX_FILE_SIZE: int = 10 * 1024 * 1024 * 1024  # 10GB in bytes
    
    # TikTok API Configuration
    TIKTOK_AUTH_URL: str = "https://www.tiktok.com/v2/auth/authorize"
    TIKTOK_TOKEN_URL: str = "https://open.tiktokapis.com/v2/oauth/token/"
    TIKTOK_API_BASE: str = "https://open.tiktokapis.com/v2"
    TIKTOK_RATE_LIMIT_REQUESTS: int = 6
    TIKTOK_RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # Instagram API Configuration
    INSTAGRAM_AUTH_URL: str = "https://www.facebook.com/v21.0/dialog/oauth"
    INSTAGRAM_TOKEN_URL: str = "https://graph.facebook.com/v21.0/oauth/access_token"
    INSTAGRAM_GRAPH_API_BASE: str = "https://graph.facebook.com"
    
    # Redis locking
    TOKEN_REFRESH_LOCK_TIMEOUT: int = 10  # seconds
    DATA_REFRESH_COOLDOWN: int = 60  # seconds
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Create global settings instance
settings = Settings()

# Derived constants
TIKTOK_SCOPES = ["user.info.basic", "video.upload", "video.publish"]
TIKTOK_CREATOR_INFO_URL = f"{settings.TIKTOK_API_BASE}/post/publish/creator_info/query/"
TIKTOK_INIT_UPLOAD_URL = f"{settings.TIKTOK_API_BASE}/post/publish/video/init/"
TIKTOK_STATUS_URL = f"{settings.TIKTOK_API_BASE}/post/publish/video/status/fetch/"

INSTAGRAM_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_read_engagement",
    "pages_show_list"
]

