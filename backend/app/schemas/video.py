"""Pydantic schemas for video operations"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List


# Video operations mostly use the Video model directly or return dictionaries
# These schemas are for any explicit request/response models if needed

class VideoResponse(BaseModel):
    """Video response schema"""
    id: int
    filename: str
    status: str
    # Additional fields can be added as needed


class VideoUpdateRequest(BaseModel):
    """Schema for updating video settings"""
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    visibility: Optional[str] = None
    made_for_kids: Optional[bool] = None
    scheduled_time: Optional[str] = None
    privacy_level: Optional[str] = None
    allow_comments: Optional[bool] = None
    allow_duet: Optional[bool] = None
    allow_stitch: Optional[bool] = None
    caption: Optional[str] = None


class VideoReorderRequest(BaseModel):
    """Schema for reordering videos"""
    video_ids: List[int]

