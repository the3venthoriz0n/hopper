"""Subscription model"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base


class Subscription(Base):
    """Stripe subscription information"""
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    stripe_subscription_id = Column(String(255), unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String(255), nullable=False, index=True)
    plan_type = Column(String(50), nullable=False)  # 'free', 'starter', 'creator', 'unlimited'
    status = Column(String(50), nullable=False)  # 'active', 'canceled', 'past_due', 'unpaid', 'trialing'
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    preserved_tokens_balance = Column(Integer, nullable=True)  # Token balance preserved when enrolling in unlimited plan
    stripe_metered_item_id = Column(String(255), nullable=True)  # Stripe subscription item ID for metered usage (overage tokens)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="subscription")

