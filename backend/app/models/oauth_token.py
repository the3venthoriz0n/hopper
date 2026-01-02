"""OAuthToken model"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


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

