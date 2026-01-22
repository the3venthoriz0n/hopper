"""Upload orchestration - background tasks, retries, batch operations"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.helpers import get_user_videos, get_user_settings, update_video
from app.db.session import SessionLocal
from app.models.video import Video
from app.services.token_service import check_tokens_available, get_token_balance, calculate_tokens_from_bytes
from app.services.video.helpers import (
    build_upload_context, check_upload_success, record_platform_error,
    set_platform_status, compute_global_status
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


async def _upload_single_video_to_destinations(
    video_id: int,
    user_id: int,
    enabled_destinations: list,
    upload_context: Dict[str, Any]
) -> Tuple[str, int]:  # Returns (result: "succeeded"|"failed"|"cancelled", video_id)
    """Upload a single video to all enabled destinations
    
    This function is called concurrently for multiple videos.
    Each call gets its own database session for thread-safety.
    
    Args:
        video_id: Video ID to upload
        user_id: User ID
        enabled_destinations: List of enabled destination names
        upload_context: Upload context dict (for settings, tokens, etc.)
    
    Returns:
        Tuple of (result, video_id) where result is "succeeded", "failed", or "cancelled"
    """
    # Create a new database session for this concurrent task
    db = SessionLocal()
    try:
        # Import DESTINATION_UPLOADERS
        from app.services.video import DESTINATION_UPLOADERS
        
        # Get video from database
        from app.models.video import Video as VideoModel
        video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
        
        if not video:
            upload_logger.error(f"Video {video_id} not found for user {user_id}")
            return ("failed", video_id)
        
        # Check token availability before uploading (only if tokens not already consumed)
        if video.tokens_consumed == 0:
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
                
                # Refresh video and build full response
                db.refresh(video)
                from app.services.event_service import publish_video_status_changed
                from app.services.video.helpers import build_video_response
                from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                all_settings = get_all_user_settings(user_id, db=db)
                all_tokens = get_all_oauth_tokens(user_id, db=db)
                video_dict = build_video_response(video, all_settings, all_tokens, user_id)
                
                # Publish status change event
                await publish_video_status_changed(user_id, video_id, old_status, "failed", video_dict=video_dict)
                
                return ("failed", video_id)
        
        # Check if upload was cancelled before starting
        if _cancellation_flags.get(video_id, False):
            upload_logger.info(f"Upload cancelled for video {video_id} before starting")
            _cancellation_flags.pop(video_id, None)
            old_status = video.status
            update_video(video_id, user_id, db=db, status="cancelled", error="Upload cancelled by user")
            
            # Refresh video and build full response
            db.refresh(video)
            from app.services.event_service import publish_video_status_changed
            from app.services.video.helpers import build_video_response
            from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
            all_settings = get_all_user_settings(user_id, db=db)
            all_tokens = get_all_oauth_tokens(user_id, db=db)
            video_dict = build_video_response(video, all_settings, all_tokens, user_id)
            
            await publish_video_status_changed(user_id, video_id, old_status, "cancelled", video_dict=video_dict)
            return ("cancelled", video_id)
        
        # Set status to uploading before starting
        old_status = video.status
        if old_status == "cancelled":
            update_video(video_id, user_id, db=db, status="uploading", error=None)
        else:
            update_video(video_id, user_id, db=db, status="uploading")
        
        # Clear any previous cancellation flag
        _cancellation_flags.pop(video_id, None)
        
        # Refresh video and build full response
        db.refresh(video)
        from app.services.event_service import publish_video_status_changed
        from app.services.video.helpers import build_video_response
        from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
        all_settings = get_all_user_settings(user_id, db=db)
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        video_dict = build_video_response(video, all_settings, all_tokens, user_id)
        
        # Publish status change event
        await publish_video_status_changed(user_id, video_id, old_status, "uploading", video_dict=video_dict)
        
        # Initialize platform_errors and platform_statuses in custom_settings
        if video.custom_settings is None:
            video.custom_settings = {}
        if "platform_errors" not in video.custom_settings:
            video.custom_settings["platform_errors"] = {}
        if "platform_statuses" not in video.custom_settings:
            video.custom_settings["platform_statuses"] = {}
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(video, "custom_settings")
        db.commit()
        
        # Track if upload was cancelled during processing
        upload_cancelled = False
        
        # Upload to all enabled destinations
        for dest_name in enabled_destinations:
            # Check for cancellation before each destination
            if _cancellation_flags.get(video_id, False):
                upload_logger.info(f"Upload cancelled for video {video_id} during {dest_name} upload")
                _cancellation_flags.pop(video_id, None)
                
                # Set all remaining platforms to cancelled
                for remaining_dest in enabled_destinations[enabled_destinations.index(dest_name):]:
                    await set_platform_status(video_id, user_id, remaining_dest, "cancelled", error="Upload cancelled by user", db=db)
                
                upload_cancelled = True
                break  # Exit destination loop
            
            uploader_func = DESTINATION_UPLOADERS.get(dest_name)
            if uploader_func:
                try:
                    # Set platform status to uploading before starting
                    await set_platform_status(video_id, user_id, dest_name, "uploading", error=None, db=db)
                    
                    await uploader_func(user_id, video_id, db=db)
                    
                    # Check if upload succeeded
                    updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
                    if updated_video and check_upload_success(updated_video, dest_name):
                        # Set platform status to success
                        await set_platform_status(video_id, user_id, dest_name, "success", error=None, db=db)
                    else:
                        # Upload didn't succeed - check if there's an error recorded
                        platform_errors = (updated_video.custom_settings or {}).get("platform_errors", {})
                        error_msg = platform_errors.get(dest_name, "Upload failed")
                        await set_platform_status(video_id, user_id, dest_name, "failed", error=error_msg, db=db)
                    
                    # Check for cancellation after each upload
                    if _cancellation_flags.get(video_id, False):
                        upload_logger.info(f"Upload cancelled for video {video_id} after {dest_name} upload")
                        _cancellation_flags.pop(video_id, None)
                        
                        # Set platform status to cancelled
                        await set_platform_status(video_id, user_id, dest_name, "cancelled", error="Upload cancelled by user", db=db)
                        
                        upload_cancelled = True
                        break  # Exit destination loop
                except Exception as upload_err:
                    # Check if error is due to cancellation
                    if "cancelled by user" in str(upload_err).lower():
                        upload_logger.info(f"Upload cancelled for {dest_name}: {upload_err}")
                        await set_platform_status(video_id, user_id, dest_name, "cancelled", error="Upload cancelled by user", db=db)
                        upload_cancelled = True
                        break
                    else:
                        upload_logger.error(f"Upload failed for {dest_name}: {upload_err}")
                        # Record platform-specific error and set status to failed
                        record_platform_error(video_id, user_id, dest_name, str(upload_err), db=db)
                        await set_platform_status(video_id, user_id, dest_name, "failed", error=str(upload_err), db=db)
        
        # Skip final status check if upload was cancelled
        if upload_cancelled:
            return ("cancelled", video_id)
        
        # Compute global status from platform statuses
        updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
        if updated_video:
            # Compute global status from platform statuses
            new_global_status = compute_global_status(updated_video, enabled_destinations)
            old_status = updated_video.status
            
            # Update global status if it changed
            if old_status != new_global_status:
                # Get actual error message from video if it exists
                actual_error = updated_video.error
                
                # Build error message based on platform statuses
                platform_statuses = (updated_video.custom_settings or {}).get("platform_statuses", {})
                succeeded = [d for d in enabled_destinations if platform_statuses.get(d, {}).get("status") == "success"]
                failed = [d for d in enabled_destinations if platform_statuses.get(d, {}).get("status") == "failed"]
                
                if new_global_status == "uploaded":
                    update_video(video_id, user_id, db=db, status="uploaded", error=None)
                elif new_global_status == "partial":
                    # Partial success - build error message
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="partial", error=actual_error)
                    else:
                        update_video(video_id, user_id, db=db, status="partial", 
                                   error=f"Partial upload: succeeded ({', '.join(succeeded)}), failed ({', '.join(failed)})")
                elif new_global_status == "failed":
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                    else:
                        update_video(video_id, user_id, db=db, status="failed", 
                                   error=f"Upload failed for all destinations: {', '.join(failed)}")
                else:
                    # For other statuses (uploading, pending, cancelled), just update status
                    update_video(video_id, user_id, db=db, status=new_global_status)
                
                # Refresh video to get updated status
                db.refresh(updated_video)
                
                # Build full video response
                all_settings = get_all_user_settings(user_id, db=db)
                all_tokens = get_all_oauth_tokens(user_id, db=db)
                video_dict = build_video_response(updated_video, all_settings, all_tokens, user_id)
                
                # Publish status change event
                await publish_video_status_changed(user_id, video_id, old_status, new_global_status, video_dict=video_dict)
            
            # Return result based on global status
            if new_global_status == "uploaded":
                return ("succeeded", video_id)
            elif new_global_status == "cancelled":
                return ("cancelled", video_id)
            else:
                return ("failed", video_id)
        
        return ("failed", video_id)
    except Exception as e:
        upload_logger.error(f"Error uploading video {video_id} for user {user_id}: {e}", exc_info=True)
        # Update video status to failed
        try:
            update_video(video_id, user_id, db=db, status="failed", error=f"Upload error: {str(e)}")
        except:
            pass
        return ("failed", video_id)
    finally:
        db.close()


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
        # Create concurrent tasks for all videos
        tasks = [
            _upload_single_video_to_destinations(
                video.id,
                user_id,
                enabled_destinations,
                upload_context
            )
            for video in pending_videos
        ]
        
        # Run all uploads concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        videos_succeeded = 0
        videos_failed = 0
        videos_cancelled = 0
        
        for result in results:
            if isinstance(result, Exception):
                upload_logger.error(f"Exception in concurrent upload: {result}", exc_info=True)
                videos_failed += 1
            else:
                result_type, video_id = result
                if result_type == "succeeded":
                    videos_succeeded += 1
                elif result_type == "failed":
                    videos_failed += 1
                elif result_type == "cancelled":
                    videos_cancelled += 1
        
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
    
    # Allow retry for failed or cancelled videos
    if video.status not in ["failed", "cancelled"]:
        raise ValueError(f"Cannot retry video with status '{video.status}'. Only failed or cancelled videos can be retried.")
    
    # Check if R2 object exists before retrying
    # If upload was cancelled before reaching R2, the object won't exist
    from app.services.storage.r2_service import get_r2_service
    r2_service = get_r2_service()
    
    if not video.path:
        raise ValueError(
            f"Cannot retry upload: Video file was never uploaded to storage. "
            f"The upload was cancelled before completion. Please remove this video and upload it again."
        )
    
    if not r2_service.object_exists(video.path):
        raise ValueError(
            f"Cannot retry upload: Video file not found in storage ({video.path}). "
            f"The upload was cancelled before completion. Please remove this video and upload it again."
        )
    
    # Clear all cancellation flags on retry
    _cancellation_flags.pop(video_id, None)
    from app.db.redis import clear_r2_upload_cancelled
    clear_r2_upload_cancelled(video_id)
    
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
    
    # Publish status change event with full video data and queue token count
    from app.services.token_service import get_queue_token_count
    queue_token_count = get_queue_token_count(user_id, db)
    await publish_video_status_changed(user_id, video_id, old_status, "pending", video_dict=video_dict, queue_token_count=queue_token_count)
    
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
    upload_cancelled = False
    
    # Publish status change to "uploading" when retry starts (so frontend shows cancel button)
    from app.models.video import Video as VideoModel
    retry_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
    if retry_video and retry_video.status == "pending":
        # Set status to uploading and publish event so frontend knows upload started
        update_video(video_id, user_id, db=db, status="uploading")
        db.refresh(retry_video)
        all_settings = get_all_user_settings(user_id, db=db)
        all_tokens = get_all_oauth_tokens(user_id, db=db)
        video_dict = build_video_response(retry_video, all_settings, all_tokens, user_id)
        await publish_video_status_changed(user_id, video_id, "pending", "uploading", video_dict=video_dict)
    
    for dest_name in enabled_destinations:
        # Check for cancellation before each destination
        if _cancellation_flags.get(video_id, False):
            upload_logger.info(f"Retry upload cancelled for video {video_id} during {dest_name} upload")
            _cancellation_flags.pop(video_id, None)
            
            # Set all remaining platforms to cancelled
            for remaining_dest in enabled_destinations[enabled_destinations.index(dest_name):]:
                await set_platform_status(video_id, user_id, remaining_dest, "cancelled", error="Upload cancelled by user", db=db)
            
            upload_cancelled = True
            break  # Exit destination loop
        
        uploader_func = DESTINATION_UPLOADERS.get(dest_name)
        if uploader_func:
            try:
                # Status is already set to uploading above, no need to set again
                # Upload
                if dest_name == "instagram":
                    await uploader_func(user_id, video_id, db=db)
                else:
                    uploader_func(user_id, video_id, db=db)
                
                # Set platform status to uploading before starting
                await set_platform_status(video_id, user_id, dest_name, "uploading", error=None, db=db)
                
                # Check for cancellation after each upload
                if _cancellation_flags.get(video_id, False):
                    upload_logger.info(f"Retry upload cancelled for video {video_id} after {dest_name} upload")
                    _cancellation_flags.pop(video_id, None)
                    
                    # Set platform status to cancelled
                    await set_platform_status(video_id, user_id, dest_name, "cancelled", error="Upload cancelled by user", db=db)
                    
                    upload_cancelled = True
                    break  # Exit destination loop
                
                # Check if upload succeeded
                from app.models.video import Video as VideoModel
                updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
                if updated_video and check_upload_success(updated_video, dest_name):
                    succeeded_destinations.append(dest_name)
                    # Set platform status to success
                    await set_platform_status(video_id, user_id, dest_name, "success", error=None, db=db)
                else:
                    # Upload didn't succeed - check if there's an error recorded
                    platform_errors = (updated_video.custom_settings or {}).get("platform_errors", {})
                    error_msg = platform_errors.get(dest_name, "Upload failed")
                    await set_platform_status(video_id, user_id, dest_name, "failed", error=error_msg, db=db)
            except Exception as upload_err:
                # Check if error is due to cancellation
                if "cancelled by user" in str(upload_err).lower():
                    upload_logger.info(f"Retry upload cancelled for {dest_name}: {upload_err}")
                    await set_platform_status(video_id, user_id, dest_name, "cancelled", error="Upload cancelled by user", db=db)
                    upload_cancelled = True
                    break
                else:
                    upload_logger.error(f"Retry upload failed for {dest_name}: {upload_err}")
                    # Record platform-specific error and set status to failed
                    record_platform_error(video_id, user_id, dest_name, str(upload_err), db=db)
                    await set_platform_status(video_id, user_id, dest_name, "failed", error=str(upload_err), db=db)
    
    # If upload was cancelled, return early
    if upload_cancelled:
        return {
            "ok": True,
            "succeeded": succeeded_destinations,
            "message": f"Retry cancelled. Partial success: {', '.join(succeeded_destinations) if succeeded_destinations else 'none'}"
        }
    
    # Compute global status from platform statuses
    from app.models.video import Video as VideoModel
    updated_video = db.query(VideoModel).filter(VideoModel.id == video_id).first()
    if updated_video:
        new_global_status = compute_global_status(updated_video, enabled_destinations)
        old_status = updated_video.status
        
        if old_status != new_global_status:
            actual_error = updated_video.error
            platform_statuses = (updated_video.custom_settings or {}).get("platform_statuses", {})
            succeeded = [d for d in enabled_destinations if platform_statuses.get(d, {}).get("status") == "success"]
            failed = [d for d in enabled_destinations if platform_statuses.get(d, {}).get("status") == "failed"]
            
            if new_global_status == "uploaded":
                update_video(video_id, user_id, db=db, status="uploaded", error=None)
            elif new_global_status == "partial":
                if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                    update_video(video_id, user_id, db=db, status="partial", error=actual_error)
                else:
                    update_video(video_id, user_id, db=db, status="partial", 
                               error=f"Partial upload: succeeded ({', '.join(succeeded)}), failed ({', '.join(failed)})")
            elif new_global_status == "failed":
                if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                    update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                else:
                    update_video(video_id, user_id, db=db, status="failed", 
                               error=f"Upload failed for all destinations: {', '.join(failed)}")
            else:
                update_video(video_id, user_id, db=db, status=new_global_status)
    
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

