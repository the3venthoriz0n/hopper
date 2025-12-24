"""Videos API routes"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_auth, require_csrf_new
from app.db.helpers import (
    add_user_video, delete_video, get_all_user_settings, get_user_settings,
    get_user_videos, update_video
)
from app.db.redis import set_upload_progress
from app.db.session import get_db
from app.models.video import Video
from app.services.stripe_service import calculate_tokens_from_bytes
from app.services.video_service import (
    DESTINATION_UPLOADERS, build_upload_context, build_video_response,
    check_upload_success, cleanup_video_file
)
from app.utils.templates import replace_template_placeholders
from app.utils.video_tokens import verify_video_access_token

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
    # ROOT CAUSE FIX: Validate file size during streaming
    # Note: For multipart/form-data uploads, we cannot reliably get file size before reading
    # because Content-Length includes the entire request (boundaries, field names, etc.), not just the file.
    # FastAPI's UploadFile.size may also not be set. We validate during streaming instead.
    
    upload_logger.info(
        f"Video upload method: FILE_UPLOAD (file) - Starting upload for user {user_id}: "
        f"{file.filename} (Content-Type: {file.content_type})"
    )
    
    # Get user settings
    global_settings = get_user_settings(user_id, "global", db=db)
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    
    # Check for duplicates if not allowed
    if not global_settings.get("allow_duplicates", False):
        existing_videos = get_user_videos(user_id, db=db)
        if any(v.filename == file.filename for v in existing_videos):
            raise HTTPException(400, f"Duplicate video: {file.filename} is already in the queue")
    
    # Save file to disk with streaming and size validation
    # ROOT CAUSE FIX: Use streaming to handle large files without loading entire file into memory
    path = settings.UPLOAD_DIR / file.filename
    file_size = 0
    start_time = asyncio.get_event_loop().time()
    last_log_time = start_time
    chunk_count = 0
    
    try:
        chunk_size = 1024 * 1024  # 1MB chunks
        
        with open(path, "wb") as f:
            while True:
                # Read chunk with explicit timeout to detect connection issues
                try:
                    chunk = await asyncio.wait_for(file.read(chunk_size), timeout=300.0)  # 5 minute timeout per chunk
                except asyncio.TimeoutError:
                    upload_logger.error(f"Chunk read timeout for user {user_id}: {file.filename} (received {file_size / (1024*1024):.2f} MB)")
                    raise
                
                if not chunk:
                    break
                
                file_size += len(chunk)
                chunk_count += 1
                current_time = asyncio.get_event_loop().time()
                
                # Log progress every 10MB or every 30 seconds
                if file_size % (10 * 1024 * 1024) < chunk_size or (current_time - last_log_time) >= 30:
                    elapsed = current_time - start_time
                    speed_mbps = (file_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    upload_logger.info(
                        f"Upload progress for user {user_id}: {file.filename} - "
                        f"{file_size / (1024*1024):.2f} MB received ({chunk_count} chunks, "
                        f"{speed_mbps:.2f} MB/s, {elapsed:.1f}s elapsed)"
                    )
                    last_log_time = current_time
                
                # Validate file size during streaming (before writing entire file)
                if file_size > settings.MAX_FILE_SIZE:
                    # Clean up partial file
                    try:
                        path.unlink()
                    except:
                        pass
                    size_mb = file_size / (1024 * 1024)
                    size_gb = file_size / (1024 * 1024 * 1024)
                    max_mb = settings.MAX_FILE_SIZE / (1024 * 1024)
                    max_gb = settings.MAX_FILE_SIZE / (1024 * 1024 * 1024)
                    raise HTTPException(
                        413,
                        f"File too large: {file.filename} is {size_mb:.2f} MB ({size_gb:.2f} GB). Maximum file size is {max_mb:.0f} MB ({max_gb:.0f} GB)."
                    )
                
                f.write(chunk)
        
        elapsed_total = asyncio.get_event_loop().time() - start_time
        avg_speed = (file_size / (1024 * 1024)) / elapsed_total if elapsed_total > 0 else 0
        upload_logger.info(
            f"Video added for user {user_id}: {file.filename} "
            f"({file_size / (1024*1024):.2f} MB, {chunk_count} chunks, "
            f"{avg_speed:.2f} MB/s, {elapsed_total:.1f}s total)"
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError as e:
        # Clean up partial file on timeout
        try:
            if path.exists():
                path.unlink()
        except:
            pass
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        upload_logger.error(
            f"Upload timeout for user {user_id}: {file.filename} "
            f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks) - "
            f"Likely caused by proxy/reverse proxy timeout (Cloudflare default: 100s free, 600s paid)",
            exc_info=True
        )
        raise HTTPException(
            504, 
            f"Upload timeout: The file upload was interrupted after {elapsed:.0f} seconds. "
            f"This is likely due to a proxy timeout (e.g., Cloudflare). "
            f"Please try again or contact support if the issue persists."
        )
    except HTTPException:
        raise
    except Exception as e:
        # Clean up partial file on error
        try:
            if path.exists():
                path.unlink()
        except:
            pass
        error_type = type(e).__name__
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        
        # Check for connection-related errors that might indicate proxy timeout
        error_str = str(e).lower()
        is_connection_error = any(keyword in error_str for keyword in [
            'connection', 'reset', 'closed', 'broken', 'timeout', 
            'gateway', 'proxy', 'cloudflare'
        ])
        
        if is_connection_error:
            upload_logger.error(
                f"Connection error during upload for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks) - "
                f"Error: {error_type}: {str(e)} - Likely proxy/reverse proxy timeout",
                exc_info=True
            )
            raise HTTPException(
                504,
                f"Upload failed: Connection was interrupted after {elapsed:.0f} seconds. "
                f"This may be due to a proxy timeout. Please try again."
            )
        else:
            upload_logger.error(
                f"Failed to save video file for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks, "
                f"error: {error_type}: {str(e)})",
                exc_info=True
            )
            raise HTTPException(500, f"Failed to save video file: {str(e)}")
    
    # Calculate tokens required for this upload (1 token = 10MB)
    tokens_required = calculate_tokens_from_bytes(file_size)
    
    # NOTE: We don't check tokens here - tokens are deducted when video is successfully uploaded to platforms
    # This allows users to queue videos and manage their uploads without immediately consuming tokens
    
    # Generate YouTube title and description (to prevent re-randomization)
    filename_no_ext = file.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    youtube_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Generate description once to prevent re-randomization when templates use {random}
    desc_template = youtube_settings.get('description_template', '') or global_settings.get('description_template', '')
    youtube_description = replace_template_placeholders(
        desc_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    ) if desc_template else ''
    
    # Verify file was actually written to disk
    resolved_path = path.resolve()
    if not resolved_path.exists():
        upload_logger.error(
            f"CRITICAL: File upload appeared to succeed for user {user_id}: {file.filename} "
            f"but file does not exist at {resolved_path}. File size reported: {file_size} bytes"
        )
        raise HTTPException(500, f"File upload failed: file was not saved to disk")
    
    # Verify file size matches what we wrote
    actual_file_size = resolved_path.stat().st_size
    if actual_file_size != file_size:
        upload_logger.warning(
            f"File size mismatch for user {user_id}: {file.filename}. "
            f"Expected: {file_size} bytes, Actual: {actual_file_size} bytes"
        )
    
    # Add to database with file size and tokens
    # ROOT CAUSE FIX: Store absolute path to prevent path resolution issues
    # 
    # TOKEN DEDUCTION STRATEGY:
    # Tokens are NOT deducted when adding to queue - only when successfully uploaded to platforms.
    # This allows users to queue videos, reorder, edit, and remove without losing tokens.
    # When a video is uploaded to multiple platforms (YouTube + TikTok + Instagram), tokens are
    # only charged ONCE (on first successful platform upload). The video.tokens_consumed field
    # tracks this to prevent double-charging across multiple platforms.
    # NOTE: Tokens are NOT deducted here - they're deducted when video is successfully uploaded to platforms
    video = add_user_video(
        user_id=user_id,
        filename=file.filename,
        path=str(resolved_path),  # Ensure absolute path
        generated_title=youtube_title,
        generated_description=youtube_description,
        file_size_bytes=file_size,
        tokens_consumed=0,  # Don't consume tokens yet - only on successful upload
        db=db
    )
    
    upload_logger.info(f"Video added to queue for user {user_id}: {file.filename} ({file_size / (1024*1024):.2f} MB, will cost {tokens_required} tokens on upload)")
    
    # Return the same format as GET /api/videos for consistency
    # Get settings and tokens to compute titles (batch load to prevent N+1)
    all_settings = get_all_user_settings(user_id, db=db)
    from app.db.helpers import get_all_oauth_tokens
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    
    # Build video response using the same helper function as GET endpoint
    return build_video_response(video, all_settings, all_tokens, user_id)


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


@router.delete("/uploaded")
def delete_uploaded_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete only uploaded/completed videos from user's queue"""
    videos = get_user_videos(user_id, db=db)
    deleted_count = 0
    
    # Delete only videos that are uploaded or completed
    for video in videos:
        if video.status not in ('uploaded', 'completed'):
            continue
            
        # Clean up file if it exists
        video_path = Path(video.path).resolve()
        if video_path.exists():
            try:
                video_path.unlink()
            except Exception as e:
                upload_logger.warning(f"Could not delete file {video_path}: {e}")
        
        # Delete from database
        db.delete(video)
        deleted_count += 1
    
    db.commit()
    upload_logger.info(f"Deleted {deleted_count} uploaded videos for user {user_id}")
    
    return {"ok": True, "deleted": deleted_count}


@router.delete("")
def delete_all_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Delete all videos from user's queue"""
    videos = get_user_videos(user_id, db=db)
    deleted_count = 0
    
    # Delete all video files and database records
    for video in videos:
        # Skip videos that are currently uploading
        if video.status == 'uploading':
            continue
            
        # Clean up file if it exists
        video_path = Path(video.path).resolve()
        if video_path.exists():
            try:
                video_path.unlink()
            except Exception as e:
                upload_logger.warning(f"Could not delete file {video_path}: {e}")
        
        # Delete from database
        db.delete(video)
        deleted_count += 1
    
    db.commit()
    upload_logger.info(f"Deleted {deleted_count} videos for user {user_id}")
    
    return {"ok": True, "deleted": deleted_count}


@router.delete("/{video_id}")
def delete_video_by_id(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Remove video from user's queue"""
    success = delete_video(video_id, user_id, db=db)
    if not success:
        raise HTTPException(404, "Video not found")
    
    # Clean up file if it exists
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
    if video:
        video_path = Path(video.path).resolve()
        if video_path.exists():
            try:
                video_path.unlink()
            except Exception as e:
                upload_logger.warning(f"Could not delete file {video_path}: {e}")
    
    return {"ok": True}


@router.get("/{video_id}/file")
def get_video_file(
    video_id: int,
    token: str = Query(..., description="Access token for video file"),
    db: Session = Depends(get_db)
):
    """Serve video file for TikTok PULL_FROM_URL
    
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
        Video file with proper headers for TikTok
    
    Raises:
        HTTPException 404: Video not found
        HTTPException 403: Invalid or expired token
    """
    # Get video to verify it exists and get user_id
    # Query all videos to find this one (we need user_id for token verification)
    all_videos = db.query(Video).filter(Video.id == video_id).all()
    if not all_videos:
        logger.warning(f"Video file request for non-existent video_id: {video_id}")
        raise HTTPException(404, "Video not found")
    
    video = all_videos[0]
    
    # Verify token
    if not verify_video_access_token(token, video_id, video.user_id):
        logger.warning(f"Invalid or expired token for video_id: {video_id}, user_id: {video.user_id}")
        raise HTTPException(403, "Invalid or expired access token")
    
    # Try the stored path first
    video_path = Path(video.path).resolve()
    
    # If stored path doesn't exist, try fallback: UPLOAD_DIR / filename
    if not video_path.exists():
        fallback_path = (settings.UPLOAD_DIR / video.filename).resolve()
        
        # Only log once per video_id to reduce log spam
        # Use module-level cache to track logged video_ids
        if not hasattr(get_video_file, '_logged_404_videos'):
            get_video_file._logged_404_videos = set()
        
        if fallback_path.exists():
            if video_id not in get_video_file._logged_404_videos:
                logger.info(f"Using fallback path for video_id {video_id}: {fallback_path} (stored path not found: {video_path})")
                get_video_file._logged_404_videos.add(video_id)
            video_path = fallback_path
        else:
            # Only log error once per video_id
            if video_id not in get_video_file._logged_404_videos:
                logger.error(
                    f"Video file not found for video_id {video_id}: "
                    f"Stored path: {video_path} (exists: False), "
                    f"Fallback path: {fallback_path} (exists: False), "
                    f"UPLOAD_DIR: {settings.UPLOAD_DIR}, Filename: {video.filename}"
                )
                get_video_file._logged_404_videos.add(video_id)
                # Clear cache periodically (every 1000 entries) to prevent memory growth
                if len(get_video_file._logged_404_videos) > 1000:
                    get_video_file._logged_404_videos.clear()
            raise HTTPException(404, f"Video file not found at {video_path} or {fallback_path}")
    
    # Return file with proper headers for TikTok
    file_ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
    media_type = {
        'mp4': 'video/mp4',
        'mov': 'video/quicktime',
        'webm': 'video/webm'
    }.get(file_ext, 'video/mp4')
    
    return FileResponse(
        path=str(video_path),
        media_type=media_type,
        filename=video.filename,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600"  # Cache for 1 hour
        }
    )


@router.post("/{video_id}/recompute-title")
def recompute_video_title(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Recompute video title from current template"""
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Get settings
    global_settings = get_user_settings(user_id, "global", db=db)
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    
    # Remove custom title if exists in custom_settings
    custom_settings = video.custom_settings or {}
    if "title" in custom_settings:
        del custom_settings["title"]
        update_video(video_id, user_id, db=db, custom_settings=custom_settings)
    
    # Regenerate title
    filename_no_ext = video.filename.rsplit('.', 1)[0]
    title_template = youtube_settings.get('title_template', '') or global_settings.get('title_template', '{filename}')
    
    new_title = replace_template_placeholders(
        title_template,
        filename_no_ext,
        global_settings.get('wordbank', [])
    )
    
    # Update generated_title in database
    update_video(video_id, user_id, db=db, generated_title=new_title)
    
    return {"ok": True, "title": new_title[:100]}


@router.patch("/{video_id}")
def update_video_settings(
    video_id: int,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db),
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[str] = None,
    visibility: Optional[str] = None,
    made_for_kids: Optional[bool] = None,
    scheduled_time: Optional[str] = None,
    privacy_level: Optional[str] = None,
    allow_comments: Optional[bool] = None,
    allow_duet: Optional[bool] = None,
    allow_stitch: Optional[bool] = None,
    caption: Optional[str] = None
):
    """Update video settings"""
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Update custom settings
    custom_settings = video.custom_settings or {}
    
    if title is not None:
        if len(title) > 100:
            raise HTTPException(400, "Title must be 100 characters or less")
        custom_settings["title"] = title
    
    if description is not None:
        custom_settings["description"] = description
    
    if tags is not None:
        custom_settings["tags"] = tags
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        custom_settings["visibility"] = visibility
    
    if made_for_kids is not None:
        custom_settings["made_for_kids"] = made_for_kids
    
    # TikTok-specific settings
    if privacy_level is not None:
        # Accept both old format (public/private/friends) and new API format (PUBLIC_TO_EVERYONE/SELF_ONLY/etc)
        valid_levels = ["public", "private", "friends", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY", "FOLLOWER_OF_CREATOR"]
        if privacy_level not in valid_levels:
            raise HTTPException(400, f"Invalid privacy level: {privacy_level}. Must be one of {valid_levels}")
        custom_settings["privacy_level"] = privacy_level
    
    if allow_comments is not None:
        custom_settings["allow_comments"] = allow_comments
    
    if allow_duet is not None:
        custom_settings["allow_duet"] = allow_duet
    
    if allow_stitch is not None:
        custom_settings["allow_stitch"] = allow_stitch
    
    # Instagram-specific settings
    if caption is not None:
        if len(caption) > 2200:
            raise HTTPException(400, "Caption must be 2200 characters or less")
        custom_settings["caption"] = caption
    
    # Build update dict
    update_data = {"custom_settings": custom_settings}
    
    # Handle scheduled_time
    if scheduled_time is not None:
        if scheduled_time:  # Set schedule
            try:
                parsed_time = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                update_data["scheduled_time"] = parsed_time
                if video.status == "pending":
                    update_data["status"] = "scheduled"
            except ValueError:
                raise HTTPException(400, "Invalid datetime format")
        else:  # Clear schedule
            update_data["scheduled_time"] = None
            if video.status == "scheduled":
                update_data["status"] = "pending"
    
    # Update in database
    update_video(video_id, user_id, db=db, **update_data)
    
    # Return updated video
    updated_videos = get_user_videos(user_id, db=db)
    updated_video = next((v for v in updated_videos if v.id == video_id), None)
    
    return {
        "id": updated_video.id,
        "filename": updated_video.filename,
        "status": updated_video.status,
        "custom_settings": updated_video.custom_settings,
        "scheduled_time": updated_video.scheduled_time.isoformat() if hasattr(updated_video, 'scheduled_time') and updated_video.scheduled_time else None
    }


@router.post("/reorder")
async def reorder_videos(request: Request, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Reorder videos in the user's queue"""
    try:
        # Parse JSON body
        body = await request.json()
        video_ids = body.get("video_ids", [])
        
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
async def cancel_scheduled_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Cancel all scheduled videos for user"""
    videos = get_user_videos(user_id, db=db)
    cancelled_count = 0
    
    for video in videos:
        if video.status == "scheduled":
            video_id = video.id
            update_video(video_id, user_id, db=db, status="pending", scheduled_time=None)
            cancelled_count += 1
    
    return {"ok": True, "cancelled": cancelled_count}


@router.post("/{video_id}/retry")
async def retry_failed_upload(video_id: int, user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Retry a failed upload"""
    # Get video
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    
    if not video:
        raise HTTPException(404, "Video not found")
    
    # Only allow retry for failed videos
    if video.status != "failed":
        raise HTTPException(400, f"Cannot retry video with status '{video.status}'. Only failed videos can be retried.")
    
    # Reset status to pending and clear error
    update_video(video_id, user_id, db=db, status="pending", error=None)
    
    # Trigger upload immediately
    # Get enabled destinations
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    
    if not enabled_destinations:
        raise HTTPException(400, "No enabled destinations. Enable at least one destination first.")
    
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
                updated_video = db.query(Video).filter(Video.id == video_id).first()
                if updated_video and check_upload_success(updated_video, dest_name):
                    succeeded_destinations.append(dest_name)
            except Exception as upload_err:
                upload_logger.error(f"Retry upload failed for {dest_name}: {upload_err}")
                # Continue to next destination
    
    # Update final status - preserve actual error messages
    updated_video = db.query(Video).filter(Video.id == video_id).first()
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


# ============================================================================
# UPLOAD ROUTES
# ============================================================================

@upload_router.get("/limits")
async def get_upload_limits():
    """Get upload size limits"""
    max_mb = settings.MAX_FILE_SIZE / (1024 * 1024)
    max_gb = settings.MAX_FILE_SIZE / (1024 * 1024 * 1024)
    return {
        "max_file_size_bytes": settings.MAX_FILE_SIZE,
        "max_file_size_mb": int(max_mb),
        "max_file_size_gb": max_gb,
        "max_file_size_display": f"{int(max_mb)} MB ({max_gb:.0f} GB)"
    }


@upload_router.post("")
async def upload_videos(user_id: int = Depends(require_csrf_new), db: Session = Depends(get_db)):
    """Upload all pending videos to all enabled destinations (immediate or scheduled)"""
    
    # Check if at least one destination is enabled and connected
    enabled_destinations = []
    
    upload_logger.debug(f"Checking destinations for user {user_id}...")
    
    # Build upload context (enabled destinations, settings, tokens)
    upload_context = build_upload_context(user_id, db)
    enabled_destinations = upload_context["enabled_destinations"]
    destination_settings = upload_context["dest_settings"]
    all_tokens = upload_context["all_tokens"]
    
    upload_logger.info(f"Enabled destinations for user {user_id}: {enabled_destinations}")
    
    if not enabled_destinations:
        error_msg = "No enabled and connected destinations. Enable at least one destination and ensure it's connected."
        upload_logger.error(error_msg)
        raise HTTPException(400, error_msg)
    
    # Get videos that can be uploaded: pending, failed (retry), or uploading (retry if stuck)
    user_videos = get_user_videos(user_id, db=db)
    pending_videos = [v for v in user_videos if v.status in ['pending', 'failed', 'uploading']]
    
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
        raise HTTPException(400, error_msg)
    
    # If upload immediately is enabled, upload all at once to all enabled destinations
    if upload_immediately:
        for video in pending_videos:
            video_id = video.id
            
            # Set status to uploading before starting
            update_video(video_id, user_id, db=db, status="uploading")
            
            # Upload to all enabled destinations
            failed_destinations = []
            for dest_name in enabled_destinations:
                uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                if uploader_func:
                    try:
                        if dest_name == "instagram":
                            await uploader_func(user_id, video_id, db=db)
                        else:
                            uploader_func(user_id, video_id, db=db)
                    except Exception as upload_err:
                        upload_logger.error(f"Upload failed for {dest_name}: {upload_err}")
                        # Continue to next destination
            
            # Check final status and collect actual error messages
            updated_video = db.query(Video).filter(Video.id == video_id).first()
            if updated_video:
                succeeded = []
                failed = []
                error_messages = []
                
                for dest_name in enabled_destinations:
                    if check_upload_success(updated_video, dest_name):
                        succeeded.append(dest_name)
                    else:
                        failed.append(dest_name)
                
                # Get actual error message from video if it exists
                actual_error = updated_video.error
                
                if len(succeeded) == len(enabled_destinations):
                    update_video(video_id, user_id, db=db, status="uploaded")
                elif len(succeeded) > 0:
                    # Partial success - preserve actual error if it's platform-specific, otherwise list failed destinations
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                    else:
                        # List which destinations succeeded and failed (like old implementation)
                        update_video(video_id, user_id, db=db, status="failed", 
                                   error=f"Partial upload: succeeded ({', '.join(succeeded)}), failed ({', '.join(failed)})")
                else:
                    # All failed - preserve actual error if it's platform-specific, otherwise list failed destinations
                    if actual_error and not any(pattern in actual_error.lower() for pattern in ["upload failed for all destinations", "upload succeeded for", "but failed for others", "partial upload:"]):
                        update_video(video_id, user_id, db=db, status="failed", error=actual_error)
                    else:
                        update_video(video_id, user_id, db=db, status="failed", 
                                   error=f"Upload failed for all destinations: {', '.join(failed)}")
        
        return {
            "ok": True,
            "message": f"Uploaded {len(pending_videos)} video(s) to all enabled destinations",
            "videos_uploaded": len(pending_videos)
        }
    else:
        # Schedule uploads (scheduler will handle them)
        scheduled_count = 0
        for video in pending_videos:
            update_video(video.id, user_id, db=db, status="scheduled")
            scheduled_count += 1
        
        return {
            "ok": True,
            "message": f"Scheduled {scheduled_count} video(s) for upload",
            "videos_scheduled": scheduled_count
        }
