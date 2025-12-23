"""TokenBalance model"""
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


class TokenBalance(Base):
    """User token balance for API usage tracking"""
    __tablename__ = "token_balances"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    # Token tracking
    tokens_remaining = Column(Integer, default=0, nullable=False)  # Current remaining tokens
    tokens_used_this_period = Column(Integer, default=0, nullable=False)  # Tokens used in current period
    monthly_tokens = Column(Integer, default=0, nullable=False)  # Starting balance for period (plan + granted tokens)
    
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

