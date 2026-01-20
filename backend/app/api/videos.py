"""Videos API routes"""
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_auth, require_csrf_new
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
    handle_file_upload, delete_video_files, serve_video_file,
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
    publish_video_title_recomputed, publish_videos_bulk_recomputed
)

# Loggers
upload_logger = logging.getLogger("upload")
cleanup_logger = logging.getLogger("cleanup")
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Separate router for upload endpoints
upload_router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("")
async def add_video(
    file: UploadFile = File(...),
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Add video to user's queue"""
    try:
        return await handle_file_upload(file, user_id, db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        error_str = str(e).lower()
        if "timeout" in error_str or "proxy" in error_str:
            raise HTTPException(504, str(e))
        elif "too large" in error_str:
            raise HTTPException(413, str(e))
        else:
            raise HTTPException(500, str(e))


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
    result = await delete_video_files(user_id, video_id=video_id, db=db)
    if result["deleted"] == 0:
        raise HTTPException(404, "Video not found")
    
    return {"ok": True}


@router.post("/{video_id}/cancel")
async def cancel_video_upload(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel an in-progress upload for a video"""
    result = await cancel_upload(video_id, user_id, db)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "Failed to cancel upload"))
    return result


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
