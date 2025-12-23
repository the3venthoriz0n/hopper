"""Pydantic schemas for video operations"""
from pydantic import BaseModel
from typing import Optional, Dict, Any


# Video operations mostly use the Video model directly or return dictionaries
# These schemas are for any explicit request/response models if needed

class VideoResponse(BaseModel):
    """Video response schema"""
    id: int
    filename: str
    status: str
    # Additional fields can be added as needed

