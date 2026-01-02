"""Pydantic schemas for settings API"""
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class TikTokPrivacyLevel(str, Enum):
    """TikTok privacy level enum - accepts both old and new formats"""
    # Old format (for backward compatibility)
    PUBLIC = "public"
    PRIVATE = "private"
    FRIENDS = "friends"
    
    # New API format
    PUBLIC_TO_EVERYONE = "PUBLIC_TO_EVERYONE"
    MUTUAL_FOLLOW_FRIENDS = "MUTUAL_FOLLOW_FRIENDS"
    SELF_ONLY = "SELF_ONLY"
    FOLLOWER_OF_CREATOR = "FOLLOWER_OF_CREATOR"
    
    @classmethod
    def from_string(cls, value: str) -> Optional['TikTokPrivacyLevel']:
        """Convert string to enum, handling empty/null strings"""
        if not value or value.lower() == "null":
            return None
        try:
            return cls(value)
        except ValueError:
            return None


class GlobalSettingsUpdate(BaseModel):
    """Schema for updating global settings"""
    title_template: Optional[str] = Field(None, max_length=100)
    description_template: Optional[str] = None
    upload_immediately: Optional[bool] = None
    schedule_mode: Optional[Literal["spaced", "specific_time"]] = None
    schedule_interval_value: Optional[int] = Field(None, ge=1)
    schedule_interval_unit: Optional[Literal["minutes", "hours", "days"]] = None
    schedule_start_time: Optional[str] = None
    allow_duplicates: Optional[bool] = None
    upload_first_immediately: Optional[bool] = None


class YouTubeSettingsUpdate(BaseModel):
    """Schema for updating YouTube settings"""
    visibility: Optional[Literal["public", "private", "unlisted"]] = None
    made_for_kids: Optional[bool] = None
    title_template: Optional[str] = Field(None, max_length=100)
    description_template: Optional[str] = None
    tags_template: Optional[str] = None


class TikTokSettingsUpdate(BaseModel):
    """Schema for updating TikTok settings"""
    privacy_level: Optional[TikTokPrivacyLevel] = None
    allow_comments: Optional[bool] = None
    allow_duet: Optional[bool] = None
    allow_stitch: Optional[bool] = None
    title_template: Optional[str] = Field(None, max_length=100)
    description_template: Optional[str] = None
    commercial_content_disclosure: Optional[bool] = None
    commercial_content_your_brand: Optional[bool] = None
    commercial_content_branded: Optional[bool] = None


class InstagramSettingsUpdate(BaseModel):
    """Schema for updating Instagram settings"""
    caption_template: Optional[str] = Field(None, max_length=2200)
    disable_comments: Optional[bool] = None
    disable_likes: Optional[bool] = None
    media_type: Optional[Literal["REELS", "VIDEO"]] = None
    share_to_feed: Optional[bool] = None
    cover_url: Optional[str] = None
    audio_name: Optional[str] = None


class AddWordbankWordRequest(BaseModel):
    """Schema for adding a word to the wordbank"""
    word: str = Field(..., min_length=1)


class ToggleDestinationRequest(BaseModel):
    """Schema for toggling a destination on/off - extensible for future fields"""
    enabled: bool = Field(..., description="Whether to enable or disable the destination")
