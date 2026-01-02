"""Setting model"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import Base


class Setting(Base):
    """User settings (global, youtube, tiktok, instagram)"""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), nullable=False)  # global, youtube, tiktok, instagram
    key = Column(String(100), nullable=False)
    value = Column(Text)  # Store as JSON string for complex values
    
    # Relationship
    user = relationship("User", back_populates="settings")
    
    # Composite index for common query pattern
    __table_args__ = (
        Index('ix_settings_user_category', 'user_id', 'category'),
    )

