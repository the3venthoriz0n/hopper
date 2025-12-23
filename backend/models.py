"""Database models for Hopper - DEPRECATED: Models have been moved to app/models/"""
# This file is kept temporarily for backward compatibility during migration
# All models have been moved to app/models/ - import from there instead

from app.models.user import User
from app.models.video import Video
from app.models.setting import Setting
from app.models.oauth_token import OAuthToken
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.models.token_transaction import TokenTransaction
from app.models.stripe_event import StripeEvent
from app.db.session import engine, SessionLocal, init_db, get_db
from app.models.base import Base

# Re-export for backward compatibility
__all__ = [
    "User", "Video", "Setting", "OAuthToken",
    "Subscription", "TokenBalance", "TokenTransaction", "StripeEvent",
    "Base", "engine", "SessionLocal", "init_db", "get_db"
]
