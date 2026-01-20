"""File upload, streaming, and serving"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import UploadFile

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.helpers import (
    get_user_videos, get_user_settings, get_all_user_settings, get_all_oauth_tokens,
    add_user_video
)
from app.models.video import Video
from app.services.token_service import calculate_tokens_from_bytes, check_tokens_available, get_token_balance
from app.utils.templates import replace_template_placeholders
from app.utils.video_tokens import verify_video_access_token
from app.services.video.helpers import build_video_response
from app.services.storage.r2_service import get_r2_service

upload_logger = logging.getLogger("upload")
logger = logging.getLogger(__name__)


async def handle_file_upload(
    file: "UploadFile",
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Handle file upload with streaming, validation, and database creation
    
    Args:
        file: FastAPI UploadFile object
        user_id: User ID
        db: Database session
    
    Returns:
        Dict with video response (same format as GET /api/videos)
    
    Raises:
        ValueError: For validation errors (duplicate, file too large, etc.)
        Exception: For file I/O errors
    """
    
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
            raise ValueError(f"Duplicate video: {file.filename} is already in the queue")
    
    # Stream file to temporary file, then upload to R2
    # Use streaming to handle large files without loading entire file into memory
    temp_file = None
    file_size = 0
    start_time = asyncio.get_event_loop().time()
    last_log_time = start_time
    chunk_count = 0
    r2_object_key = None
    
    try:
        # Create temporary file for streaming upload
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}")
        temp_path = Path(temp_file.name)
        chunk_size = 1024 * 1024  # 1MB chunks
        
        with open(temp_path, "wb") as f:
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
                    size_mb = file_size / (1024 * 1024)
                    size_gb = file_size / (1024 * 1024 * 1024)
                    max_mb = settings.MAX_FILE_SIZE / (1024 * 1024)
                    max_gb = settings.MAX_FILE_SIZE / (1024 * 1024 * 1024)
                    raise ValueError(
                        f"File too large: {file.filename} is {size_mb:.2f} MB ({size_gb:.2f} GB). Maximum file size is {max_mb:.0f} MB ({max_gb:.0f} GB)."
                    )
                
                f.write(chunk)
        
        # Upload to R2
        upload_logger.info(f"Uploading {file.filename} to R2 for user {user_id}...")
        r2_service = get_r2_service()
        
        # Generate R2 object key: user_{user_id}/pending_{timestamp}_{filename}
        # Will be updated to user_{user_id}/video_{video_id}_{filename} after video creation
        timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
        r2_object_key = f"user_{user_id}/pending_{timestamp}_{file.filename}"
        
        if not r2_service.upload_file(temp_path, r2_object_key):
            raise Exception("Failed to upload file to R2 storage")
        
        elapsed_total = asyncio.get_event_loop().time() - start_time
        avg_speed = (file_size / (1024 * 1024)) / elapsed_total if elapsed_total > 0 else 0
        upload_logger.info(
            f"Video uploaded to R2 for user {user_id}: {file.filename} "
            f"({file_size / (1024*1024):.2f} MB, {chunk_count} chunks, "
            f"{avg_speed:.2f} MB/s, {elapsed_total:.1f}s total, R2 key: {r2_object_key})"
        )
    except ValueError:
        raise
    except asyncio.TimeoutError as e:
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        upload_logger.error(
            f"Upload timeout for user {user_id}: {file.filename} "
            f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks)",
            exc_info=True
        )
        raise Exception(
            f"Upload timeout: The file upload was interrupted after {elapsed:.0f} seconds. "
            f"Please try again or contact support if the issue persists."
        )
    except Exception as e:
        # Clean up temp file and R2 object on error
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass
        if r2_object_key:
            try:
                r2_service = get_r2_service()
                r2_service.delete_object(r2_object_key)
            except:
                pass
        
        error_type = type(e).__name__
        elapsed = asyncio.get_event_loop().time() - start_time if 'start_time' in locals() else 0
        
        # Check for connection-related errors
        error_str = str(e).lower()
        is_connection_error = any(keyword in error_str for keyword in [
            'connection', 'reset', 'closed', 'broken', 'timeout', 
            'gateway', 'proxy', 'cloudflare'
        ])
        
        if is_connection_error:
            upload_logger.error(
                f"Connection error during upload for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks) - "
                f"Error: {error_type}: {str(e)}",
                exc_info=True
            )
            raise Exception(
                f"Upload failed: Connection was interrupted after {elapsed:.0f} seconds. "
                f"Please try again."
            )
        else:
            upload_logger.error(
                f"Failed to upload video file for user {user_id}: {file.filename} "
                f"(received {file_size / (1024*1024):.2f} MB in {elapsed:.1f}s, {chunk_count} chunks, "
                f"error: {error_type}: {str(e)})",
                exc_info=True
            )
            raise Exception(f"Failed to upload video file: {str(e)}")
    finally:
        # Always clean up temp file
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except:
                pass
    
    # Calculate tokens required for this upload (1 token = 10MB)
    tokens_required = calculate_tokens_from_bytes(file_size)
    
    # Check token availability before adding to queue
    # For free plans, include queued videos to prevent queuing more than user can afford
    if not check_tokens_available(user_id, tokens_required, db, include_queued_videos=True):
        # Calculate total for accurate error message
        queued_videos = get_user_videos(user_id, db=db)
        total_tokens_required = tokens_required
        for video in queued_videos:
            if video.status in ('pending', 'scheduled') and video.tokens_consumed == 0:
                video_tokens = video.tokens_required if video.tokens_required is not None else (
                    calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0
                )
                total_tokens_required += video_tokens
        
        balance_info = get_token_balance(user_id, db)
        tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
        error_msg = f"Insufficient tokens: Need {total_tokens_required} tokens total (including {total_tokens_required - tokens_required} from queued videos) but only have {tokens_remaining} remaining"
        upload_logger.warning(
            f"Video upload blocked for user {user_id}: {file.filename} - {error_msg}"
        )
        raise ValueError(error_msg)
    
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
    
    # Verify R2 object exists
    r2_service = get_r2_service()
    if not r2_service.object_exists(r2_object_key):
        upload_logger.error(
            f"CRITICAL: File upload appeared to succeed for user {user_id}: {file.filename} "
            f"but R2 object does not exist at {r2_object_key}. File size reported: {file_size} bytes"
        )
        raise Exception(f"File upload failed: file was not saved to R2")
    
    # Verify R2 object size matches what we uploaded
    r2_object_size = r2_service.get_object_size(r2_object_key)
    if r2_object_size and r2_object_size != file_size:
        upload_logger.warning(
            f"File size mismatch for user {user_id}: {file.filename}. "
            f"Expected: {file_size} bytes, R2 object size: {r2_object_size} bytes"
        )
    
    # Add to database with file size and tokens
    # Store R2 object key in path field
    # 
    # TOKEN DEDUCTION STRATEGY:
    # Tokens are NOT deducted when adding to queue - only when successfully uploaded to platforms.
    # This allows users to queue videos, reorder, edit, and remove without losing tokens.
    # When a video is uploaded to multiple platforms (YouTube + TikTok + Instagram), tokens are
    # only charged ONCE (on first successful platform upload). The video.tokens_consumed field
    # tracks this to prevent double-charging across multiple platforms.
    # NOTE: Tokens are NOT deducted here - they're deducted when video is successfully uploaded to platforms
    # tokens_required is stored to avoid recalculation (DRY principle)
    video = add_user_video(
        user_id=user_id,
        filename=file.filename,
        path=r2_object_key,  # Store R2 object key
        generated_title=youtube_title,
        generated_description=youtube_description,
        file_size_bytes=file_size,
        tokens_required=tokens_required,  # Store calculated value to avoid recalculation
        tokens_consumed=0,  # Don't consume tokens yet - only on successful upload
        db=db
    )
    
    # Update R2 object key to final format: user_{user_id}/video_{video_id}_{filename}
    final_r2_key = f"user_{user_id}/video_{video.id}_{file.filename}"
    if r2_object_key != final_r2_key:
        # Copy object to new key (R2 doesn't support rename, so we copy and delete)
        try:
            if r2_service.copy_object(r2_object_key, final_r2_key):
                r2_service.delete_object(r2_object_key)
                # Update database with final key
                video.path = final_r2_key
                db.commit()
                upload_logger.info(f"Renamed R2 object from {r2_object_key} to {final_r2_key}")
            else:
                upload_logger.warning(f"Failed to copy R2 object from {r2_object_key} to {final_r2_key}. Using original key.")
        except Exception as e:
            upload_logger.warning(f"Failed to rename R2 object from {r2_object_key} to {final_r2_key}: {e}. Using original key.")
            # Continue with original key - not critical
    
    upload_logger.info(f"Video added to queue for user {user_id}: {file.filename} ({file_size / (1024*1024):.2f} MB, will cost {tokens_required} tokens on upload)")
    
    # Build video response using the same helper function as GET endpoint
    # Get settings and tokens to compute titles (batch load to prevent N+1)
    all_settings = get_all_user_settings(user_id, db=db)
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    video_dict = build_video_response(video, all_settings, all_tokens, user_id)
    
    # Publish event with full video data (prevents race condition with frontend)
    from app.services.event_service import publish_video_added
    await publish_video_added(user_id, video_dict)
    
    # Return the same format as GET /api/videos for consistency
    return video_dict


async def delete_video_files(
    user_id: int,
    video_id: Optional[int] = None,
    status_filter: Optional[List[str]] = None,
    exclude_status: Optional[List[str]] = None,
    db: Session = None
) -> Dict[str, Any]:
    """Delete video files and database records
    
    Args:
        user_id: User ID
        video_id: Optional specific video ID to delete
        status_filter: Optional list of statuses to include (e.g., ['uploaded', 'completed'])
        exclude_status: Optional list of statuses to exclude (e.g., ['uploading'])
        db: Database session
    
    Returns:
        Dict with 'ok' and 'deleted' count
    """
    if db is None:
        from app.db.session import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        videos = get_user_videos(user_id, db=db)
        deleted_count = 0
        
        for video in videos:
            # Filter by video_id if specified
            if video_id is not None and video.id != video_id:
                continue
            
            # Filter by status if specified
            if status_filter and video.status not in status_filter:
                continue
            
            # Exclude by status if specified
            if exclude_status and video.status in exclude_status:
                continue
            
            # Delete from R2 if it exists
            r2_service = get_r2_service()
            if video.path:
                if not r2_service.delete_object(video.path):
                    upload_logger.warning(f"Could not delete R2 object {video.path}")
            
            # Delete from database
            db.delete(video)
            deleted_count += 1
            
            # Publish video_deleted event for real-time UI updates
            from app.services.event_service import publish_video_deleted
            await publish_video_deleted(user_id, video.id)
        
        db.commit()
        upload_logger.info(f"Deleted {deleted_count} video(s) for user {user_id}")
        
        return {"ok": True, "deleted": deleted_count}
    finally:
        if should_close:
            db.close()


def serve_video_file(
    video_id: int,
    token: str,
    db: Session
) -> Dict[str, Any]:
    """Generate presigned download URL for video file from R2
    
    Args:
        video_id: Video ID
        token: Access token for video file (for verification)
        db: Database session
    
    Returns:
        Dict with 'url', 'filename', 'media_type', 'expires_in'
    
    Raises:
        ValueError: If video not found, token invalid, or R2 object doesn't exist
    """
    # Get video to verify it exists and get user_id
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        logger.warning(f"Video file request for non-existent video_id: {video_id}")
        raise ValueError("Video not found")
    
    # Verify token
    if not verify_video_access_token(token, video_id, video.user_id):
        logger.warning(f"Invalid or expired token for video_id: {video_id}, user_id: {video.user_id}")
        raise ValueError("Invalid or expired access token")
    
    # Verify R2 object exists
    if not video.path:
        logger.error(f"Video {video_id} has no R2 object key (path is empty)")
        raise ValueError("Video file not found in storage")
    
    r2_service = get_r2_service()
    if not r2_service.object_exists(video.path):
        logger.error(f"R2 object not found for video_id {video_id}: {video.path}")
        raise ValueError(f"Video file not found in storage: {video.path}")
    
    # Generate presigned download URL (valid for 1 hour)
    expires_in = 3600
    download_url = r2_service.generate_download_url(video.path, expires_in=expires_in)
    
    # Determine media type
    file_ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
    media_type = {
        'mp4': 'video/mp4',
        'mov': 'video/quicktime',
        'webm': 'video/webm'
    }.get(file_ext, 'video/mp4')
    
    return {
        "url": download_url,
        "filename": video.filename,
        "media_type": media_type,
        "expires_in": expires_in
    }

