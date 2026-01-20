"""Video model"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


class Video(Base):
    """Video queue"""
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)  # R2 object key (e.g., "user_{user_id}/video_{video_id}_{filename}")
    status = Column(String(50), default="pending", nullable=False)  # pending, uploading, completed, failed
    generated_title = Column(Text)
    generated_description = Column(Text)  # Generated description to prevent re-randomization
    custom_settings = Column(JSON, default=dict)  # JSON for per-video settings
    error = Column(Text)  # Error message if failed
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    scheduled_time = Column(DateTime(timezone=True))  # For scheduled uploads
    file_size_bytes = Column(BigInteger, nullable=True)  # File size for token calculation
    tokens_required = Column(Integer, nullable=True)  # Tokens required for this upload (calculated once when added to queue)
    tokens_consumed = Column(Integer, nullable=True)  # Tokens consumed for this upload
    
    # Relationship
    user = relationship("User", back_populates="videos")
    token_transactions = relationship("TokenTransaction", back_populates="video")
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('ix_videos_user_status', 'user_id', 'status'),
        Index('ix_videos_status_scheduled_time', 'status', 'scheduled_time'),
    )

