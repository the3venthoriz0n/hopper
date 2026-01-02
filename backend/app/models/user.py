"""User model"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


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
    wordbank_words = relationship("WordbankWord", back_populates="user", cascade="all, delete-orphan")

