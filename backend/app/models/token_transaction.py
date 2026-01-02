"""TokenTransaction model"""
from sqlalchemy import Column, Integer, String, ForeignKey, JSON, Index, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


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

