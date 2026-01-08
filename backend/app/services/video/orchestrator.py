"""Upload orchestration - background tasks, retries, batch operations"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.helpers import get_user_videos, get_user_settings, update_video
from app.models.video import Video
from app.services.token_service import check_tokens_available, get_token_balance, calculate_tokens_from_bytes
from app.services.video.helpers import (
    build_upload_context, check_upload_success, record_platform_error
)

upload_logger = logging.getLogger("upload")

# Track cancellation requests by video_id (thread-safe for async operations)
_cancellation_flags: Dict[int, bool] = {}


def calculate_scheduled_time(
    video: Video,
    video_index: int,
    global_settings: Dict[str, Any],
    db: Session
) -> Optional[datetime]:
    """Calculate scheduled_time for a video based on schedule settings"""
    
    if video.scheduled_time:
        return video.scheduled_time
    
    schedule_mode = global_settings.get("schedule_mode", "spaced")
    schedule_interval_value = global_settings.get("schedule_interval_value", 1)
    schedule_interval_unit = global_settings.get("schedule_interval_unit", "hours")
    schedule_start_time = global_settings.get("schedule_start_time", "")
    upload_first_immediately = global_settings.get("upload_first_immediately", True)
    
    current_time = datetime.now(timezone.utc)
    
    # CASE 1: Immediate first upload handling
    if upload_first_immediately and video_index == 0:
        return current_time

    # Determine Base Time
    if schedule_start_time:
        try:
            base_time = datetime.fromisoformat(schedule_start_time.replace('Z', '+00:00'))
            if base_time.tzinfo is None:
                base_time = base_time.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            base_time = current_time
    else:
        base_time = current_time

    # Calculate interval in seconds
    units = {"minutes": 60, "hours": 3600, "days": 86400}
    interval_seconds = schedule_interval_value * units.get(schedule_interval_unit, 3600)

    # --- THE LOGIC FIX ---
    # If immediate is TRUE:  Index 0=Now, Index 1=Base+1Interval, Index 2=Base+2Interval
    # If immediate is FALSE: Index 0=Base+1Interval, Index 1=Base+2Interval, Index 2=Base+3Interval
    if upload_first_immediately:
        offset_multiplier = video_index  # 0, 1, 2...
    else:
        offset_multiplier = video_index + 1  # 1, 2, 3...
    
    scheduled_time = base_time + timedelta(seconds=interval_seconds * offset_multiplier)

    # Final check: If scheduled for the past (due to old base_time), 
    # shift everything relative to current_time
    if scheduled_time < current_time:
        scheduled_time = current_time + timedelta(seconds=interval_seconds * offset_multiplier)
    
    return scheduled_time


async def upload_all_pending_videos(
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Upload all pending videos to all enabled destinations (immediate or scheduled)
    
    Background task entry point - handles batch upload orchestration.
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with 'ok', 'message', and upload statistics
    """
    # Build upload context (enabled destinations, settings, tokens)
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    
    upload_logger.debug(f"Checking destinations for user {user_id}...")
    upload_logger.info(f"Enabled destinations for user {user_id}: {enabled_destinations}")
    
    if not enabled_destinations:
        error_msg = "No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        upload_logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Get videos that can be uploaded: pending, failed (retry), uploading (retry if stuck), or cancelled (retry)
    user_videos = get_user_videos(user_id, db=db)
    pending_videos = [v for v in user_videos if v.status in ['pending', 'failed', 'uploading', 'cancelled']]
    
    upload_logger.info(f"Videos ready to upload for user {user_id}: {len(pending_videos)}")
    
    # Get global settings for upload behavior
    global_settings = get_user_settings(user_id, "global", db=db)
    upload_immediately = global_settings.get("upload_immediately", True)
    
    if not pending_videos:
        # Check what statuses videos actually have
        statuses = {}
        for v in user_videos:
            status = v.status or 'unknown'
            statuses[status] = statuses.get(status, 0) + 1
        error_msg = f"No videos ready to upload. Add videos first. Current video statuses: {statuses}"
        upload_logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Import DESTINATION_UPLOADERS from video module
    from app.services.video import DESTINATION_UPLOADERS
    
    # If upload immediately is enabled, upload all at once to all enabled destinations
    if upload_immediately:
        videos_succeeded = 0
        videos_failed = 0
        videos_cancelled = 0
        
        for video in pending_videos:
            video_id = video.id
            
            # Check token availability before uploading (only if tokens not already consumed)
            if video.tokens_consumed == 0:
                # Use stored tokens_required with fallback for backward compatibility
                tokens_required = video.tokens_required if video.tokens_required is not None else calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0
                
                if tokens_required > 0 and not check_tokens_available(user_id, tokens_required, db):
                    balance_info = get_token_balance(user_id, db)
                    tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
                    error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
                    upload_logger.error(
                        f"Upload blocked for user {user_id}, video {video_id} ({video.filename}): {error_msg}"
                    )
                    old_status = video.status
                    update_video(video_id, user_id, db=db, status="failed", error=error_msg)
                    
                    # Refresh video and build full response (backend is source of truth)
                    db.refresh(video)
                    from app.services.event_service import publish_video_status_changed
                    from app.services.video.helpers import build_video_response
                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                    all_settings = get_all_user_settings(user_id, db=db)
                    all_tokens = get_all_oauth_tokens(user_id, db=db)
                    video_dict = build_video_response(video, all_settings, all_tokens, user_id)
                    
                    # Publish status change event with full video data
                    await publish_video_status_changed(user_id, video_id, old_status, "failed", video_dict=video_dict)
                    
                    videos_failed += 1
                    continue
            
            # Check if upload was cancelled before starting
            if _cancellation_flags.get(video_id, False):
                upload_logger.info(f"Upload cancelled for video {video_id} before starting")
                _cancellation_flags.pop(video_id, None)
                old_status = video.status
                update_video(video_id, user_id, db=db, status="cancelled", error="Upload cancelled by user")
                
                # Refresh video and build full response (backend is source of truth)
                db.refresh(video)
                from app.services.event_service import publish_video_status_changed
                from app.services.video.helpers import build_video_response
                from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                all_settings = get_all_user_settings(user_id, db=db)
                all_tokens = get_all_oauth_tokens(user_id, db=db)
                video_dict = build_video_response(video, all_settings, all_tokens, user_id)
                
                await publish_video_status_changed(user_id, video_id, old_status, "cancelled", video_dict=video_dict)
                videos_cancelled += 1
                continue
            
            # Set status to uploading before starting
            # If video was cancelled, reset error and clear cancellation flag
            old_status = video.status
            if old_status == "cancelled":
                update_video(video_id, user_id, db=db, status="uploading", error=None)
            else:
                update_video(video_id, user_id, db=db, status="uploading")
            
            # Clear any previous cancellation flag
            _cancellation_flags.pop(video_id, None)
            
            # Get video object from database for building response
            from app.models.video import Video as VideoModel
            video_obj = db.query(VideoModel).filter(VideoModel.id == video_id).first()
            
            if video_obj:
                # Refresh video and build full response (backend is source of truth)
                db.refresh(video_obj)
                from app.services.event_service import publish_video_status_changed
                from app.services.video.helpers import build_video_response
                from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                all_settings = get_all_user_settings(user_id, db=db)
                all_tokens = get_all_oauth_tokens(user_id, db=db)
                video_dict = build_video_response(video_obj, all_settings, all_tokens, user_id)
                
                # Publish status change event with full video data
                await publish_video_status_changed(user_id, video_id, old_status, "uploading", video_dict=video_dict)
                
                # Initialize platform_errors in custom_settings
                if video_obj.custom_settings is None:
                    video_obj.custom_settings = {}
                if "platform_errors" not in video_obj.custom_settings:
                    video_obj.custom_settings["platform_errors"] = {}
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(video_obj, "custom_settings")
                db.commit()
            
            # Track if upload was cancelled during processing
            upload_cancelled = False
            
            # Upload to all enabled destinations
            for dest_name in enabled_destinations:
                # Check for cancellation before each destination
                if _cancellation_flags.get(video_id, False):
                    upload_logger.info(f"Upload cancelled for video {video_id} during {dest_name} upload")
                    _cancellation_flags.pop(video_id, None)
                    
                    # Get current video status
                    from app.models.video import Video as VideoModel
                    current_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
                    old_status = current_video.status if current_video else "uploading"
                    
                    update_video(video_id, user_id, db=db, status="cancelled", error="Upload cancelled by user")
                    
                    # Refresh video and build full response (backend is source of truth)
                    db.refresh(current_video)
                    from app.services.event_service import publish_video_status_changed
                    from app.services.video.helpers import build_video_response
                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                    all_settings = get_all_user_settings(user_id, db=db)
                    all_tokens = get_all_oauth_tokens(user_id, db=db)
                    video_dict = build_video_response(current_video, all_settings, all_tokens, user_id)
                    
                    await publish_video_status_changed(user_id, video_id, old_status, "cancelled", video_dict=video_dict)
                    videos_cancelled += 1
                    upload_cancelled = True
                    break  # Exit destination loop
                
                uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                if uploader_func:
                    try:
                        await uploader_func(user_id, video_id, db=db)
                        
                        # Check for cancellation after each upload
                        if _cancellation_flags.get(video_id, False):
                            upload_logger.info(f"Upload cancelled for video {video_id} after {dest_name} upload")
                            _cancellation_flags.pop(video_id, None)
                            
                            # Get current video status
                            from app.models.video import Video as VideoModel
                            current_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
                            old_status = current_video.status if current_video else "uploading"
                            
                            update_video(video_id, user_id, db=db, status="cancelled", error="Upload cancelled by user")
                            
                            # Refresh video and build full response (backend is source of truth)
                            db.refresh(current_video)
                            from app.services.event_service import publish_video_status_changed
                            from app.services.video.helpers import build_video_response
                            from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                            all_settings = get_all_user_settings(user_id, db=db)
                            all_tokens = get_all_oauth_tokens(user_id, db=db)
                            video_dict = build_video_response(current_video, all_settings, all_tokens, user_id)
                            
                            await publish_video_status_changed(user_id, video_id, old_status, "cancelled", video_dict=video_dict)
                            videos_cancelled += 1
                            upload_cancelled = True
                            break  # Exit destination loop
                    except Exception as upload_err:
                        # Check if error is due to cancellation
                        if "cancelled by user" in str(upload_err).lower():
                            upload_logger.info(f"Upload cancelled for {dest_name}: {upload_err}")
                            # Don't record as platform error - cancellation is intentional
                            # The cancellation flag and status update are already handled
                        else:
                            upload_logger.error(f"Upload failed for {dest_name}: {upload_err}")
                            # Record platform-specific error
                            record_platform_error(video_id, user_id, dest_name, str(upload_err), db=db)
                        # Continue to next destination (or break if cancelled)
                        if "cancelled by user" in str(upload_err).lower():
                            upload_cancelled = True
                            break
            
            # Skip final status check if upload was cancelled
            if upload_cancelled:
                continue
            
            # Check final status and collect actual error messages
            updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
            if updated_video:
                succeeded = []
                failed = []
                
                for dest_name in enabled_destinations:
                    if check_upload_success(updated_video, dest_name):
                        succeeded.append(dest_name)
                    else:
                        failed.append(dest_name)
                
                # Get actual error message from video if it exists
                actual_error = updated_video.error
                
                if len(succeeded) == len(enabled_destinations):
                    old_status = updated_video.status
                    update_video(video_id, user_id, db=db, status="uploaded")
                    
                    # Refresh video to get updated status
                    db.refresh(updated_video)
                    
                    # Build full video response (backend is source of truth)
                    from app.services.video.helpers import build_video_response
                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                    all_settings = get_all_user_settings(user_id, db=db)
                    all_tokens = get_all_oauth_tokens(user_id, db=db)
                    video_dict = build_video_response(updated_video, all_settings, all_tokens, user_id)
                    
                    # Publish status change event with full video data
                    from app.services.event_service import publish_video_status_changed
                    await publish_video_status_changed(user_id, video_id, old_status, "uploaded", video_dict=video_dict)
                    
                    videos_succeeded += 1
                elif len(succeeded) > 0:
                    # Partial success - preserve actual error if it's platform-specific, otherwise list failed destinations
                    old_status = updated_video.status
                    from app.services.event_service import publish_video_status_changed
                    from app.services.video.helpers import build_video_response
                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                    
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                    else:
                        # List which destinations succeeded and failed (like old implementation)
                        update_video(video_id, user_id, db=db, status="failed", 
                                   error=f"Partial upload: succeeded ({', '.join(succeeded)}), failed ({', '.join(failed)})")
                    
                    # Refresh video and build full response
                    db.refresh(updated_video)
                    all_settings = get_all_user_settings(user_id, db=db)
                    all_tokens = get_all_oauth_tokens(user_id, db=db)
                    video_dict = build_video_response(updated_video, all_settings, all_tokens, user_id)
                    
                    await publish_video_status_changed(user_id, video_id, old_status, "failed", video_dict=video_dict)
                    videos_failed += 1
                else:
                    # All failed - preserve actual error if it's platform-specific, otherwise list failed destinations
                    old_status = updated_video.status
                    from app.services.event_service import publish_video_status_changed
                    from app.services.video.helpers import build_video_response
                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                    
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                    else:
                        update_video(video_id, user_id, db=db, status="failed", 
                                   error=f"Upload failed for all destinations: {', '.join(failed)}")
                    
                    # Refresh video and build full response
                    db.refresh(updated_video)
                    all_settings = get_all_user_settings(user_id, db=db)
                    all_tokens = get_all_oauth_tokens(user_id, db=db)
                    video_dict = build_video_response(updated_video, all_settings, all_tokens, user_id)
                    
                    await publish_video_status_changed(user_id, video_id, old_status, "failed", video_dict=video_dict)
                    videos_failed += 1
        
        # Build appropriate message based on results
        if videos_succeeded > 0 and videos_failed == 0 and videos_cancelled == 0:
            message = f"Successfully uploaded {videos_succeeded} video(s) to all enabled destinations"
        elif videos_succeeded > 0 and (videos_failed > 0 or videos_cancelled > 0):
            message = f"Uploaded {videos_succeeded} video(s) successfully, {videos_failed} failed, {videos_cancelled} cancelled"
        elif videos_cancelled > 0:
            message = f"{videos_cancelled} video(s) cancelled"
        else:
            message = f"Upload failed for {videos_failed} video(s)"
        
        return {
            "ok": True,
            "message": message,
            "videos_uploaded": videos_succeeded,
            "videos_failed": videos_failed,
            "videos_cancelled": videos_cancelled
        }
    else:
        # Schedule uploads (scheduler will handle them)
        scheduled_count = 0
        for index, video in enumerate(pending_videos):
            # Calculate scheduled_time based on schedule settings
            scheduled_time = calculate_scheduled_time(video, index, global_settings, db)
            update_video(video.id, user_id, db=db, status="scheduled", scheduled_time=scheduled_time)
            scheduled_count += 1
        
        return {
            "ok": True,
            "message": f"Scheduled {scheduled_count} video(s) for upload",
            "videos_scheduled": scheduled_count
        }


async def retry_failed_upload(
    video_id: int,
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Retry a failed upload
    
    Args:
        video_id: Video ID to retry
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with 'ok', 'succeeded' destinations, and 'message'
    """
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise ValueError("Video not found")
    
    # Only allow retry for failed videos
    if video.status != "failed":
        raise ValueError(f"Cannot retry video with status '{video.status}'. Only failed videos can be retried.")
    
    # Store old status for websocket event
    old_status = video.status
    
    # Reset status to pending, clear error, and reset tokens_consumed
    update_video(video_id, user_id, db=db, status="pending", error=None, tokens_consumed=0)
    
    # Publish websocket event so frontend updates immediately
    from app.services.event_service import publish_video_status_changed
    from app.services.video.helpers import build_video_response
    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
    
    # Refresh video and build full response (backend is source of truth)
    db.refresh(video)
    all_settings = get_all_user_settings(user_id, db=db)
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    video_dict = build_video_response(video, all_settings, all_tokens, user_id)
    
    # Publish status change event with full video data
    await publish_video_status_changed(user_id, video_id, old_status, "pending", video_dict=video_dict)
    
    # Trigger upload immediately
    # Get enabled destinations
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    
    if not enabled_destinations:
        raise ValueError("No enabled destinations. Enable at least one destination first.")
    
    # Import DESTINATION_UPLOADERS from video module
    from app.services.video import DESTINATION_UPLOADERS
    
    # Upload to all enabled destinations
    succeeded_destinations = []
    for dest_name in enabled_destinations:
        uploader_func = DESTINATION_UPLOADERS.get(dest_name)
        if uploader_func:
            try:
                # Set status to uploading
                update_video(video_id, user_id, db=db, status="uploading")
                
                # Upload
                if dest_name == "instagram":
                    await uploader_func(user_id, video_id, db=db)
                else:
                    uploader_func(user_id, video_id, db=db)
                
                # Check if upload succeeded
                from app.models.video import Video as VideoModel
                updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
                if updated_video and check_upload_success(updated_video, dest_name):
                    succeeded_destinations.append(dest_name)
            except Exception as upload_err:
                upload_logger.error(f"Retry upload failed for {dest_name}: {upload_err}")
                # Continue to next destination
    
    # Update final status - preserve actual error messages
    from app.models.video import Video as VideoModel
    updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
    actual_error = updated_video.error if updated_video else None
    
    if len(succeeded_destinations) == len(enabled_destinations):
        update_video(video_id, user_id, db=db, status="uploaded")
    elif len(succeeded_destinations) > 0:
        # Partial success - preserve actual error if it's platform-specific, otherwise list failed destinations
        failed_destinations = [d for d in enabled_destinations if d not in succeeded_destinations]
        if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
            update_video(video_id, user_id, db=db, status="failed", error=actual_error)
        else:
            # List which destinations succeeded and failed (like old implementation)
            update_video(video_id, user_id, db=db, status="failed", 
                       error=f"Partial upload: succeeded ({', '.join(succeeded_destinations)}), failed ({', '.join(failed_destinations)})")
    else:
        # All failed - preserve actual error if it's platform-specific, otherwise list failed destinations
        failed_destinations = [d for d in enabled_destinations if d not in succeeded_destinations]
        if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
            update_video(video_id, user_id, db=db, status="failed", error=actual_error)
        else:
            update_video(video_id, user_id, db=db, status="failed", 
                       error=f"Upload failed for all destinations: {', '.join(failed_destinations)}")
    
    return {
        "ok": True,
        "succeeded": succeeded_destinations,
        "message": f"Retry completed. Succeeded: {', '.join(succeeded_destinations) if succeeded_destinations else 'none'}"
    }


def cancel_scheduled_videos(
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Cancel all scheduled videos for user
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with 'ok' and 'cancelled' count
    """
    videos = get_user_videos(user_id, db=db)
    cancelled_count = 0
    
    for video in videos:
        if video.status == "scheduled":
            video_id = video.id
            update_video(video_id, user_id, db=db, status="pending", scheduled_time=None)
            cancelled_count += 1
    
    return {"ok": True, "cancelled": cancelled_count}


async def cancel_upload(video_id: int, user_id: int, db: Session) -> Dict[str, Any]:
    """Cancel an in-progress upload for a specific video
    
    Immediately updates status to cancelled and stops any in-progress upload operations.
    
    Args:
        video_id: Video ID to cancel
        user_id: User ID (for verification)
        db: Database session
        
    Returns:
        Dict with 'ok' and 'message' keys
    """
    # Verify video belongs to user
    video = db.query(Video).filter(
        Video.id == video_id,
        Video.user_id == user_id
    ).first()
    
    if not video:
        return {"ok": False, "message": "Video not found"}
    
    # Only allow cancellation if video is pending or uploading
    if video.status not in ["pending", "uploading"]:
        return {"ok": False, "message": f"Cannot cancel video with status: {video.status}"}
    
    # Immediately update status to cancelled and set cancellation flag
    old_status = video.status
    update_video(video_id, user_id, db=db, status="cancelled", error="Upload cancelled by user")
    
    # Set cancellation flag to stop any in-progress upload operations
    _cancellation_flags[video_id] = True
    
    # Publish status change event for immediate UI update
    # Refresh video and build full response (backend is source of truth)
    db.refresh(video)
    from app.services.event_service import publish_video_status_changed
    from app.services.video.helpers import build_video_response
    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
    all_settings = get_all_user_settings(user_id, db=db)
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    video_dict = build_video_response(video, all_settings, all_tokens, user_id)
    
    await publish_video_status_changed(user_id, video_id, old_status, "cancelled", video_dict=video_dict)
    
    upload_logger.info(f"Upload cancelled immediately for video {video_id} by user {user_id}")
    
    return {"ok": True, "message": "Upload cancelled"}

