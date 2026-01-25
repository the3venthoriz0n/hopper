"""Videos API routes"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_auth, require_csrf_new
from app.services.storage.r2_service import get_r2_service
from app.db.helpers import (
    add_user_video, delete_video, get_all_user_settings, get_user_settings,
    get_user_videos, update_video
)
from app.db.redis import set_upload_progress
from app.db.session import get_db
from app.db.task_queue import enqueue_task
from app.models.video import Video
from app.services.token_service import calculate_tokens_from_bytes
from app.services.video import (
    DESTINATION_UPLOADERS,
    build_upload_context, build_video_response, check_upload_success,
    cleanup_video_file, record_platform_error,
    delete_video_files, serve_video_file,
    upload_all_pending_videos, retry_failed_upload, cancel_scheduled_videos,
    recompute_video_title, update_video_settings,
    recompute_all_videos_for_platform
)
from app.services.video.orchestrator import cancel_upload
from app.utils.templates import replace_template_placeholders
from app.utils.video_tokens import verify_video_access_token
from app.schemas.video import VideoUpdateRequest, VideoReorderRequest
from app.services.event_service import (
    publish_video_added, publish_video_deleted, publish_video_updated,
    publish_video_title_recomputed, publish_videos_bulk_recomputed,
    publish_upload_progress
)

# Loggers
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Separate router for upload endpoints
upload_router = APIRouter(prefix="/api/upload", tags=["upload"])


# Pydantic models for upload requests
class PresignedUploadRequest(BaseModel):
    filename: str
    file_size: int
    content_type: Optional[str] = None
    video_id: Optional[int] = None  # Optional video ID for storing upload info


class MultipartInitiateRequest(BaseModel):
    filename: str
    file_size: int
    content_type: Optional[str] = None
    video_id: Optional[int] = None  # Optional video ID for storing upload info


class MultipartPartUrlRequest(BaseModel):
    object_key: str
    upload_id: str
    part_number: int


class MultipartPart(BaseModel):
    part_number: int
    etag: str


class MultipartCompleteRequest(BaseModel):
    object_key: str
    upload_id: str
    parts: list[MultipartPart]


class InitiateUploadRequest(BaseModel):
    filename: str
    file_size: int


class ConfirmUploadRequest(BaseModel):
    video_id: int
    object_key: str
    filename: str
    file_size: int


class FailUploadRequest(BaseModel):
    video_id: int


class AbortUploadRequest(BaseModel):
    video_id: int


class UpdateUploadProgressRequest(BaseModel):
    video_id: int
    progress_percent: int


@router.get("")
def get_videos(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get video queue with progress and computed titles for user"""
    # Get user's videos and settings - batch load to prevent N+1 queries
    videos = get_user_videos(user_id, db=db)
    all_settings = get_all_user_settings(user_id, db=db)
    from app.db.helpers import get_all_oauth_tokens
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    
    videos_with_info = []
    for video in videos:
        # Use the shared helper function to build video response
        video_dict = build_video_response(video, all_settings, all_tokens, user_id)
        videos_with_info.append(video_dict)
    
    return videos_with_info


@router.get("/queue-token-count")
def get_queue_token_count(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get total token count for queued videos (backend is source of truth)"""
    from app.services.token_service import get_queue_token_count
    
    count = get_queue_token_count(user_id, db)
    return {"queue_token_count": count}


@router.delete("/uploaded")
async def delete_uploaded_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete only uploaded/completed videos from user's queue"""
    return await delete_video_files(user_id, status_filter=['uploaded', 'completed'], db=db)


@router.delete("")
async def delete_all_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete all videos from user's queue"""
    return await delete_video_files(user_id, exclude_status=['uploading'], db=db)


@router.delete("/{video_id}")
async def delete_video_by_id(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove video from user's queue"""
    try:
        result = await delete_video_files(user_id, video_id=video_id, db=db)
        if result["deleted"] == 0:
            raise HTTPException(404, "Video not found")
        
        return {"ok": True}
    except ValueError as e:
        # Handle validation errors (e.g., trying to delete uploading video or video with active platform uploads)
        raise HTTPException(400, str(e))


@router.post("/{video_id}/cancel")
async def cancel_video_upload(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel an in-progress upload for a video"""
    result = await cancel_upload(video_id, user_id, db)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "Failed to cancel upload"))
    return result


@router.post("/{video_id}/cancel-r2")
async def cancel_r2_upload(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel R2 upload for a video (client-side upload)
    
    Note: This endpoint is kept for backward compatibility.
    The /cancel endpoint now handles both R2 and destination uploads.
    This endpoint simply calls the unified cancel_upload service.
    """
    from app.services.video.orchestrator import cancel_upload
    result = await cancel_upload(video_id, user_id, db)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "Failed to cancel upload"))
    return result


@router.get("/{video_id}/r2-cancelled")
async def check_r2_cancelled(video_id: int, user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Check if R2 upload is cancelled"""
    from app.db.redis import is_r2_upload_cancelled
    
    # Verify video belongs to user
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    return {"cancelled": is_r2_upload_cancelled(video_id)}


@router.post("/{video_id}/progress")
async def update_upload_progress(
    video_id: int,
    request: UpdateUploadProgressRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update R2 upload progress and publish via WebSocket
    
    Called by frontend during R2 uploads to report progress.
    Stores progress in Redis and publishes WebSocket event for real-time updates.
    """
    from app.services.video.helpers import should_publish_progress
    
    # Verify video belongs to user
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Validate progress range
    progress = max(0, min(100, request.progress_percent))
    
    # Get last published progress from Redis to throttle updates
    from app.db.redis import get_upload_progress
    last_published_progress = get_upload_progress(user_id, video_id) or -1
    
    # Store progress in Redis
    set_upload_progress(user_id, video_id, progress)
    
    # Publish WebSocket event (throttled to 1% increments or at completion)
    if should_publish_progress(progress, last_published_progress):
        # Use "r2" as platform identifier for R2 uploads
        await publish_upload_progress(user_id, video_id, "r2", progress)
    
    return {"ok": True, "progress": progress}


@router.get("/{video_id}/file")
def get_video_file(
    video_id: int,
    token: str = Query(..., description="Access token for video file"),
    db: Session = Depends(get_db)
):
    """Get presigned R2 download URL for video file
    
    This endpoint requires a signed token to prevent unauthorized access.
    The token is time-limited (1 hour) and includes video_id + user_id verification.
    
    Security features:
    - HMAC-signed token prevents tampering
    - Time-limited (expires after 1 hour)
    - Video ID and user ID verification
    - Constant-time comparison prevents timing attacks
    
    Args:
        video_id: Video ID
        token: Signed access token (generated during upload)
        db: Database session
    
    Returns:
        JSON response with presigned R2 download URL (redirects to R2)
    
    Raises:
        HTTPException 404: Video not found
        HTTPException 403: Invalid or expired token
    """
    from fastapi.responses import RedirectResponse
    
    try:
        file_info = serve_video_file(video_id, token, db)
        # Redirect to presigned R2 URL
        return RedirectResponse(url=file_info["url"], status_code=302)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(403, error_msg)


@router.post("/{video_id}/recompute-title")
async def recompute_video_title_route(
    video_id: int,
    platform: str = 'youtube',
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Recompute video title for specified platform"""
    try:
        result = recompute_video_title(video_id, user_id, db, platform)
        
        # Publish event
        await publish_video_title_recomputed(user_id, video_id, result.get("title", ""))
        
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/recompute-all/{platform}")
async def recompute_all_videos(
    platform: str,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Recompute all videos for a platform using current templates
    
    Platform can be: youtube, tiktok, instagram
    """
    
    try:
        updated_count = recompute_all_videos_for_platform(user_id, platform, db)
        
        # Publish event
        await publish_videos_bulk_recomputed(user_id, platform, updated_count)
        
        return {"ok": True, "updated_count": updated_count}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/{video_id}")
async def update_video_settings_route(
    video_id: int,
    request: VideoUpdateRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Update video settings"""
    try:
        # Convert Pydantic model to dict, excluding unset fields
        update_data = request.model_dump(exclude_unset=True)
        result = update_video_settings(
            video_id, user_id, db,
            **update_data
        )
        
        # Publish event with changes
        await publish_video_updated(user_id, video_id, update_data)
        
        return result
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(400, error_msg)


@router.post("/reorder")
async def reorder_videos(
    request_data: VideoReorderRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Reorder videos in the user's queue"""
    try:
        video_ids = request_data.video_ids
        
        if not video_ids:
            raise HTTPException(400, "video_ids required")
        
        # Get user's videos
        videos = get_user_videos(user_id, db=db)
        video_map = {v.id: v for v in videos}
        
        # Note: Currently we don't have an order field in the Video model
        # This would require adding an 'order' or 'position' column
        # For now, we'll just acknowledge the reorder (frontend handles display order)
        # TODO: Add 'order' field to Video model for persistent ordering
        
        return {"ok": True, "count": len(video_ids)}
    except Exception as e:
        raise HTTPException(400, f"Invalid request: {str(e)}")


@router.post("/cancel-scheduled")
async def cancel_scheduled_videos_route(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel all scheduled videos for user"""
    return cancel_scheduled_videos(user_id, db)


@router.post("/{video_id}/retry")
async def retry_failed_upload_route(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Retry a failed upload"""
    try:
        return await retry_failed_upload(video_id, user_id, db)
    except ValueError as e:
        error_msg = str(e)
        # Log user-blocking errors as errors, not warnings
        logger.error(
            f"Retry upload failed: user_id={user_id}, video_id={video_id}, error={error_msg}"
        )
        if "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(400, error_msg)


# ============================================================================
# UPLOAD ROUTES
# ============================================================================

@upload_router.get("/limits")
async def get_upload_limits():
    """Get upload size limits"""
    from app.core.config import settings
    MAX_UPLOAD_SIZE = settings.MAX_FILE_SIZE  # 10GB in bytes
    max_gb = MAX_UPLOAD_SIZE / (1024 * 1024 * 1024)
    max_mb = MAX_UPLOAD_SIZE / (1024 * 1024)
    return {
        "max_file_size_bytes": MAX_UPLOAD_SIZE,
        "max_file_size_mb": int(max_mb),
        "max_file_size_gb": max_gb,
        "max_file_size_display": f"{int(max_gb)} GB"
    }


@upload_router.post("/initiate")
async def initiate_upload(
    request: InitiateUploadRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Create video record immediately with 'uploading' status
    
    This is called before R2 upload starts so the video appears in queue
    with progress tracking.
    """
    from app.services.video.file_handler import initiate_upload_service
    
    try:
        return await initiate_upload_service(
            filename=request.filename,
            file_size=request.file_size,
            user_id=user_id,
            db=db
        )
    except ValueError as e:
        error_msg = str(e)
        if "too large" in error_msg.lower():
            raise HTTPException(413, error_msg)
        elif "duplicate" in error_msg.lower():
            raise HTTPException(400, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Failed to initiate upload for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to initiate upload: {str(e)}")


@upload_router.post("/presigned")
async def get_presigned_upload_url(
    request_data: PresignedUploadRequest,
    http_request: Request,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Generate presigned URL for single file upload to R2
    
    Validates file size and generates R2 object key, returns presigned URL
    for direct client-to-R2 upload (bypasses backend and Cloudflare limits).
    """
    from app.services.video.file_handler import get_presigned_upload_url_service
    from app.core.security import get_client_ip
    
    # Log detailed request information for debugging
    client_ip = get_client_ip(http_request)
    content_type = http_request.headers.get("Content-Type", "unknown")
    origin = http_request.headers.get("Origin", "none")
    referer = http_request.headers.get("Referer", "none")
    
    logger.info(
        f"Presigned upload request: user_id={user_id}, filename={request_data.filename}, "
        f"file_size={request_data.file_size}, content_type={request_data.content_type}, "
        f"client_ip={client_ip}, origin={origin}, referer={referer}"
    )
    
    try:
        result = get_presigned_upload_url_service(
            filename=request_data.filename,
            file_size=request_data.file_size,
            content_type=request_data.content_type,
            user_id=user_id,
            db=db,
            video_id=request_data.video_id
        )
        logger.info(f"Successfully generated presigned URL for user {user_id}, filename={request_data.filename}")
        return result
    except ValueError as e:
        error_msg = str(e)
        logger.error(
            f"Validation error for presigned upload: user_id={user_id}, "
            f"filename={request_data.filename}, file_size={request_data.file_size}, "
            f"client_ip={client_ip}, error={error_msg}"
        )
        if "too large" in error_msg.lower():
            raise HTTPException(413, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(
            f"Failed to generate presigned URL for user {user_id}, filename={request_data.filename}, "
            f"client_ip={client_ip}: {e}", exc_info=True
        )
        raise HTTPException(500, f"Failed to generate upload URL: {str(e)}")


@upload_router.post("/multipart/initiate")
async def initiate_multipart_upload(
    request: MultipartInitiateRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Initiate multipart upload for large files
    
    Validates file size and creates multipart upload in R2, returns upload_id.
    """
    from app.services.video.file_handler import initiate_multipart_upload_service
    
    try:
        return initiate_multipart_upload_service(
            filename=request.filename,
            file_size=request.file_size,
            content_type=request.content_type,
            user_id=user_id,
            db=db,
            video_id=request.video_id
        )
    except ValueError as e:
        error_msg = str(e)
        if "too large" in error_msg.lower():
            raise HTTPException(413, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Failed to initiate multipart upload for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to initiate multipart upload: {str(e)}")


@upload_router.post("/multipart/part-url")
async def get_multipart_part_url(
    request: MultipartPartUrlRequest,
    user_id: int = Depends(require_csrf_new)
):
    """Get presigned URL for uploading a specific part in multipart upload"""
    from app.services.video.file_handler import get_multipart_part_url_service
    
    try:
        return get_multipart_part_url_service(
            object_key=request.object_key,
            upload_id=request.upload_id,
            part_number=request.part_number,
            user_id=user_id
        )
    except ValueError as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "ownership" in error_msg.lower():
            raise HTTPException(403, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Failed to generate part URL for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to generate part URL: {str(e)}")


@upload_router.post("/multipart/complete")
async def complete_multipart_upload(
    request: MultipartCompleteRequest,
    user_id: int = Depends(require_csrf_new)
):
    """Complete multipart upload in R2
    
    Combines all uploaded parts into final object.
    """
    from app.services.video.file_handler import complete_multipart_upload_service
    from app.services.storage.r2_service import get_r2_service
    
    try:
        parts = [{"PartNumber": p.part_number, "ETag": p.etag} for p in request.parts]
        return complete_multipart_upload_service(
            object_key=request.object_key,
            upload_id=request.upload_id,
            parts=parts,
            user_id=user_id
        )
    except ValueError as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "ownership" in error_msg.lower():
            raise HTTPException(403, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Failed to complete multipart upload for user {user_id}: {e}", exc_info=True)
        # Try to abort on failure
        try:
            r2_service = get_r2_service()
            r2_service.abort_multipart_upload(request.object_key, request.upload_id)
        except:
            pass
        raise HTTPException(500, f"Failed to complete multipart upload: {str(e)}")


@upload_router.post("/confirm")
async def confirm_upload(
    request: ConfirmUploadRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Confirm upload and update video record
    
    Called after file is successfully uploaded to R2. Validates R2 object exists,
    updates existing video record (created by initiate_upload) with final R2 key,
    and returns video data.
    """
    from app.services.video.file_handler import confirm_upload as confirm_upload_handler
    
    try:
        return await confirm_upload_handler(
            video_id=request.video_id,
            object_key=request.object_key,
            filename=request.filename,
            file_size=request.file_size,
            user_id=user_id,
            db=db
        )
    except ValueError as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "ownership" in error_msg.lower():
            raise HTTPException(403, error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(400, error_msg)
    except Exception as e:
        logger.error(f"Failed to confirm upload for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to confirm upload: {str(e)}")


@upload_router.post("/abort")
async def abort_upload(
    request: AbortUploadRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Abort R2 upload (works for both single and multipart uploads)
    
    Cleans up multipart uploads in R2 if applicable, and clears upload info from Redis.
    """
    from app.db.redis import get_r2_upload_info, clear_r2_upload_info
    from app.services.storage.r2_service import get_r2_service
    from app.db.helpers import get_user_videos
    
    # Verify video belongs to user
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == request.video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Get upload info from Redis
    upload_info = get_r2_upload_info(request.video_id)
    
    if upload_info:
        # Validate object_key ownership for extra security
        object_key = upload_info.get("object_key")
        if object_key:
            from app.services.video.file_handler import _validate_object_key_ownership
            try:
                _validate_object_key_ownership(object_key, user_id)
            except ValueError:
                raise HTTPException(403, "Invalid object key for user")
        
        # If multipart, abort the multipart upload in R2
        if upload_info.get("upload_type") == "multipart":
            r2_service = get_r2_service()
            try:
                r2_service.abort_multipart_upload(
                    upload_info["object_key"],
                    upload_info["upload_id"]
                )
                logger.info(
                    f"Aborted multipart upload for video {request.video_id}: "
                    f"object_key={upload_info['object_key']}, upload_id={upload_info['upload_id']}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to abort multipart upload for video {request.video_id}: {e}",
                    exc_info=True
                )
                # Continue anyway - clear Redis entry
        
        # Clear upload info from Redis
        clear_r2_upload_info(request.video_id)
    
    return {"ok": True, "message": "Upload aborted"}


@upload_router.post("/fail")
async def fail_upload(
    request: FailUploadRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Mark upload as failed or delete video record on upload failure"""
    from app.db.helpers import delete_video
    
    # Verify video belongs to user and is in uploading status
    video = db.query(Video).filter(
        Video.id == request.video_id,
        Video.user_id == user_id,
        Video.status == "uploading"  # Only allow failing videos that are uploading
    ).first()
    
    if not video:
        raise HTTPException(404, "Video not found or cannot be failed")
    
    # Delete the video record (cleanup)
    delete_video(request.video_id, user_id, db=db)
    
    # Publish deletion event
    from app.services.event_service import publish_video_deleted
    await publish_video_deleted(user_id, request.video_id)
    
    return {"ok": True, "message": "Upload failed and video removed"}


@upload_router.get("")
async def get_upload_error():
    """Handle GET requests to /api/upload - this endpoint only accepts POST"""
    raise HTTPException(
        status_code=405,
        detail="Method not allowed. Use POST /api/upload to upload videos."
    )


@upload_router.post("")
async def upload_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Upload all pending videos to all enabled destinations (immediate or scheduled)
    
    Enqueues task and returns immediately (202 Accepted) to avoid Cloudflare 524 timeout.
    Task is processed asynchronously by background worker with unlimited concurrency.
    """
    # Quick validation before enqueueing
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    
    if not enabled_destinations:
        raise HTTPException(
            status_code=400,
            detail="No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        )
    
    # Validate TikTok privacy level if TikTok is enabled
    if "tiktok" in enabled_destinations:
        tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
        privacy_level = tiktok_settings.get("privacy_level")
        if not privacy_level or str(privacy_level).strip() == '':
            raise HTTPException(
                status_code=400,
                detail="TikTok privacy level is required. Please select a privacy level in TikTok destination settings before uploading."
            )
    
    user_videos = get_user_videos(user_id, db=db)
    pending_videos = [v for v in user_videos if v.status in ['pending', 'failed', 'uploading', 'cancelled']]
    
    if not pending_videos:
        statuses = {}
        for v in user_videos:
            status = v.status or 'unknown'
            statuses[status] = statuses.get(status, 0) + 1
        raise HTTPException(
            status_code=400,
            detail=f"No videos ready to upload. Add videos first. Current video statuses: {statuses}"
        )
    
    # Enqueue task
    task_id = enqueue_task(
        task_type="upload_videos",
        payload={"user_id": user_id},
        retry_count=0,
        max_retries=3
    )
    
    # Return 202 Accepted immediately
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "message": f"Upload started for {len(pending_videos)} video(s). Progress will be updated via WebSocket events.",
            "task_id": task_id,
            "videos_queued": len(pending_videos),
            "status": "processing"
        }
    )
