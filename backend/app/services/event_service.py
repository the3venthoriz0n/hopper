"""Event publishing service for real-time updates via Redis pub/sub"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db.redis import async_redis_client

logger = logging.getLogger(__name__)


async def publish_event(
    user_id: int,
    event_type: str,
    data: Dict[str, Any],
    channel: Optional[str] = None
) -> None:
    """Publish an event to Redis pub/sub for real-time updates (async)
    
    Args:
        user_id: User ID to send event to
        event_type: Event type (e.g., 'video_added', 'video_status_changed')
        data: Event payload data
        channel: Optional channel override (defaults to channel based on event type)
    """
    try:
        # Determine channel if not provided
        if not channel:
            if event_type.startswith('video_'):
                channel = f"user:{user_id}:videos"
            elif event_type == 'destination_toggled':
                channel = f"user:{user_id}:destinations"
            elif event_type == 'upload_progress':
                channel = f"user:{user_id}:upload_progress"
            elif event_type == 'settings_changed':
                channel = f"user:{user_id}:settings"
            elif event_type == 'token_balance_changed':
                channel = f"user:{user_id}:tokens"
            else:
                # Default to videos channel
                channel = f"user:{user_id}:videos"
        
        # Build event message
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Serialize and check size
        event_json = json.dumps(event)
        event_size = len(event_json)
        logger.info(f"Publishing event {event_type} to {channel}, size: {event_size} bytes")
        
        if event_size > 1000000:  # 1MB warning
            logger.warning(f"Large event payload: {event_size} bytes for event {event_type}")
        
        # Publish to Redis using async client
        result = await async_redis_client.publish(channel, event_json)
        if result > 0:
            logger.info(f"✓ Event {event_type} published successfully to {channel}: {result} subscriber(s) received it")
        else:
            logger.warning(f"⚠ Event {event_type} published to {channel} but no subscribers received it (result={result})")
        
    except Exception as e:
        logger.error(f"Failed to publish event {event_type} for user {user_id}: {e}", exc_info=True)
        raise  # Re-raise to surface the error


# Convenience functions for specific event types

async def publish_video_added(user_id: int, video_dict: dict) -> None:
    """Publish video_added event with full video data
    
    Args:
        user_id: User ID
        video_dict: Full video response dict from build_video_response()
    """
    await publish_event(
        user_id,
        "video_added",
        {
            "video": video_dict
        }
    )


async def publish_video_status_changed(user_id: int, video_id: int, old_status: str, new_status: str) -> None:
    """Publish video_status_changed event"""
    await publish_event(
        user_id,
        "video_status_changed",
        {
            "video_id": video_id,
            "old_status": old_status,
            "new_status": new_status
        }
    )


async def publish_video_updated(user_id: int, video_id: int, changes: Dict[str, Any]) -> None:
    """Publish video_updated event"""
    await publish_event(
        user_id,
        "video_updated",
        {
            "video_id": video_id,
            "changes": changes
        }
    )


async def publish_video_deleted(user_id: int, video_id: int) -> None:
    """Publish video_deleted event"""
    await publish_event(
        user_id,
        "video_deleted",
        {
            "video_id": video_id
        }
    )


async def publish_video_title_recomputed(user_id: int, video_id: int, new_title: str) -> None:
    """Publish video_title_recomputed event"""
    await publish_event(
        user_id,
        "video_title_recomputed",
        {
            "video_id": video_id,
            "new_title": new_title
        }
    )


async def publish_videos_bulk_recomputed(user_id: int, platform: str, updated_count: int) -> None:
    """Publish videos_bulk_recomputed event"""
    await publish_event(
        user_id,
        "videos_bulk_recomputed",
        {
            "platform": platform,
            "updated_count": updated_count
        }
    )


async def publish_destination_toggled(user_id: int, platform: str, enabled: bool, connected: bool, videos: list = None) -> None:
    """Publish destination_toggled event with updated video data
    
    ROOT CAUSE FIX: Include updated videos in the event payload so frontend
    immediately receives correct upload_properties and platform_statuses.
    
    Args:
        user_id: User ID
        platform: Platform name (youtube, tiktok, instagram)
        enabled: Whether destination is enabled
        connected: Whether destination is connected
        videos: Optional list of updated video dicts with recomputed platform_statuses
    """
    videos_list = videos or []
    logger.info(f"Publishing destination_toggled: user={user_id}, platform={platform}, "
                f"enabled={enabled}, connected={connected}, video_count={len(videos_list)}")
    
    # Log payload size for debugging
    try:
        payload_json = json.dumps(videos_list)
        logger.info(f"Videos payload size: {len(payload_json)} bytes")
    except Exception as e:
        logger.error(f"Failed to serialize videos to JSON: {e}", exc_info=True)
    
    await publish_event(
        user_id,
        "destination_toggled",
        {
            "platform": platform,
            "enabled": enabled,
            "connected": connected,
            "videos": videos_list
        }
    )


async def publish_upload_progress(user_id: int, video_id: int, platform: str, progress_percent: int) -> None:
    """Publish upload_progress event"""
    await publish_event(
        user_id,
        "upload_progress",
        {
            "video_id": video_id,
            "platform": platform,
            "progress_percent": progress_percent
        },
        channel=f"user:{user_id}:upload_progress"
    )


async def publish_settings_changed(user_id: int, category: str) -> None:
    """Publish settings_changed event"""
    await publish_event(
        user_id,
        "settings_changed",
        {
            "category": category
        }
    )


async def publish_token_balance_changed(user_id: int, new_balance: int, change_amount: int, reason: Optional[str] = None) -> None:
    """Publish token_balance_changed event"""
    await publish_event(
        user_id,
        "token_balance_changed",
        {
            "new_balance": new_balance,
            "change_amount": change_amount,
            "reason": reason
        }
    )

