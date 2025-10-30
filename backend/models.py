from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Destination(Base):
    __tablename__ = "destinations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    platform = Column(String)  # 'youtube', etc.
    enabled = Column(Boolean, default=True)
    credentials = Column(Text)  # Encrypted OAuth tokens
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Video(Base):
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    filename = Column(String)
    file_path = Column(String)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, scheduled, uploading, completed, failed
    scheduled_time = Column(DateTime(timezone=True), nullable=True)
    upload_destinations = Column(JSON)  # List of destination IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    uploaded_at = Column(DateTime(timezone=True), nullable=True)

