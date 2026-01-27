"""Pydantic schemas for admin operations"""
from pydantic import BaseModel
from typing import Optional


class BannerMessageUpdate(BaseModel):
    """Schema for updating banner message"""
    message: Optional[str] = None
    enabled: Optional[bool] = None
