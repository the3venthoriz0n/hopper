"""System setting model"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from datetime import datetime, timezone
from app.models.base import Base


class SystemSetting(Base):
    """System-wide settings (not user-specific)"""
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    __table_args__ = (
        Index('ix_system_settings_key', 'key'),
    )
