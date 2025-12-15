"""Database models for Hopper"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Index, BigInteger, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
import os
import logging

logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://hopper:hopper_dev_password@localhost:5432/hopper")

# Create engine and session
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    """User accounts"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for OAuth-only users
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    stripe_customer_id = Column(String(255), nullable=True, index=True)  # Stripe customer ID
    is_admin = Column(Boolean, default=False, nullable=False)  # Admin role flag
    is_email_verified = Column(Boolean, default=False, nullable=False)  # Email verification status
    
    # Relationships
    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="user", cascade="all, delete-orphan")
    oauth_tokens = relationship("OAuthToken", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    token_balance = relationship("TokenBalance", back_populates="user", uselist=False, cascade="all, delete-orphan")
    token_transactions = relationship("TokenTransaction", back_populates="user", cascade="all, delete-orphan")


class Video(Base):
    """Video queue"""
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    status = Column(String(50), default="pending", nullable=False)  # pending, uploading, completed, failed
    generated_title = Column(Text)
    custom_settings = Column(JSON, default=dict)  # JSON for per-video settings
    error = Column(Text)  # Error message if failed
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    scheduled_time = Column(DateTime(timezone=True))  # For scheduled uploads
    file_size_bytes = Column(BigInteger, nullable=True)  # File size for token calculation
    tokens_consumed = Column(Integer, nullable=True)  # Tokens consumed for this upload
    
    # Relationship
    user = relationship("User", back_populates="videos")
    token_transactions = relationship("TokenTransaction", back_populates="video")
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('ix_videos_user_status', 'user_id', 'status'),
        Index('ix_videos_status_scheduled_time', 'status', 'scheduled_time'),
    )


class Setting(Base):
    """User settings (global, youtube, tiktok, instagram)"""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), nullable=False)  # global, youtube, tiktok, instagram
    key = Column(String(100), nullable=False)
    value = Column(Text)  # Store as JSON string for complex values
    
    # Relationship
    user = relationship("User", back_populates="settings")
    
    # Composite index for common query pattern
    __table_args__ = (
        Index('ix_settings_user_category', 'user_id', 'category'),
    )


class OAuthToken(Base):
    """OAuth credentials (encrypted)"""
    __tablename__ = "oauth_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), nullable=False)  # youtube, tiktok, instagram
    access_token = Column(Text, nullable=False)  # Encrypted
    refresh_token = Column(Text)  # Encrypted
    expires_at = Column(DateTime(timezone=True))
    extra_data = Column(JSON)  # For platform-specific data
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship
    user = relationship("User", back_populates="oauth_tokens")
    
    # Composite index for common query pattern
    __table_args__ = (
        Index('ix_oauth_tokens_user_platform', 'user_id', 'platform'),
    )


class Subscription(Base):
    """Stripe subscription information"""
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    stripe_subscription_id = Column(String(255), unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String(255), nullable=False, index=True)
    plan_type = Column(String(50), nullable=False)  # 'free', 'medium', 'pro', 'unlimited'
    status = Column(String(50), nullable=False)  # 'active', 'canceled', 'past_due', 'unpaid', 'trialing'
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    preserved_tokens_balance = Column(Integer, nullable=True)  # Token balance preserved when enrolling in unlimited plan
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="subscription")


class TokenBalance(Base):
    """User token balance for API usage tracking"""
    __tablename__ = "token_balances"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    # Token tracking
    tokens_remaining = Column(Integer, default=0, nullable=False)  # Current remaining tokens
    tokens_used_this_period = Column(Integer, default=0, nullable=False)  # Tokens used in current period
    
    # Billing period tracking
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    last_reset_at = Column(DateTime(timezone=True), nullable=True)  # Last time tokens were reset
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="token_balance")
    
    def __repr__(self):
        return f"<TokenBalance(user_id={self.user_id}, remaining={self.tokens_remaining}, used={self.tokens_used_this_period})>"


class TokenTransaction(Base):
    """Token transaction audit log"""
    __tablename__ = "token_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    transaction_type = Column(String(50), nullable=False)  # 'upload', 'purchase', 'refund', 'reset', 'grant'
    tokens = Column(Integer, nullable=False)  # Positive for additions, negative for deductions
    balance_before = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    transaction_metadata = Column(JSON, default=dict)  # Store file size, filename, etc.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="token_transactions")
    video = relationship("Video", back_populates="token_transactions")
    
    # Index for common query patterns
    __table_args__ = (
        Index('ix_token_transactions_user_created', 'user_id', 'created_at'),
    )


class StripeEvent(Base):
    """Stripe webhook event log for idempotency"""
    __tablename__ = "stripe_events"
    
    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    processed = Column(Boolean, default=False, nullable=False)
    payload = Column(JSON, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


def init_db():
    """Initialize database (create all tables)"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI endpoints"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()