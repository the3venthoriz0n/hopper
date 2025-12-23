"""StripeEvent model"""
from sqlalchemy import Column, Integer, String, Boolean, Text, JSON, DateTime
from datetime import datetime, timezone
from app.models.base import Base


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

