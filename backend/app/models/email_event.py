"""EmailEvent model"""
from sqlalchemy import Column, Integer, String, Boolean, Text, JSON, DateTime
from datetime import datetime, timezone
from app.models.base import Base


class EmailEvent(Base):
    """Resend webhook event log for tracking email delivery"""
    __tablename__ = "email_events"
    
    id = Column(Integer, primary_key=True, index=True)
    resend_event_id = Column(String(255), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    email_id = Column(String(255), nullable=True, index=True)
    to_email = Column(String(255), nullable=True, index=True)
    processed = Column(Boolean, default=False, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

