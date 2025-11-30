"""Database models for Hopper"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import os

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
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="user", cascade="all, delete-orphan")
    oauth_tokens = relationship("OAuthToken", back_populates="user", cascade="all, delete-orphan")


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
    
    # Relationship
    user = relationship("User", back_populates="videos")


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
    
    # Composite unique constraint
    __table_args__ = (
        {'schema': None},
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
    extra_data = Column(JSON)  # For platform-specific data (e.g., TikTok open_id, Instagram business_account_id)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship
    user = relationship("User", back_populates="oauth_tokens")


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

