"""WordbankWord model"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


class WordbankWord(Base):
    """User wordbank words - one row per word"""
    __tablename__ = "wordbank_words"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    word = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="wordbank_words")
    
    # Composite index and unique constraint for common query patterns
    __table_args__ = (
        Index('ix_wordbank_words_user_word', 'user_id', 'word'),
        UniqueConstraint('user_id', 'word', name='uq_wordbank_words_user_word'),
    )

