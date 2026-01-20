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


# Helper functions for validation and R2 operations
def _validate_file_size(file_size: int, filename: str) -> None:
    """Validate file size against MAX_FILE_SIZE
    
    Args:
        file_size: File size in bytes
        filename: File name for error message
        
    Raises:
        ValueError: If file size exceeds MAX_FILE_SIZE
    """
    if file_size > settings.MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        size_gb = file_size / (1024 * 1024 * 1024)
        max_gb = settings.MAX_FILE_SIZE / (1024 * 1024 * 1024)
        raise ValueError(
            f"File too large: {filename} is {size_mb:.2f} MB ({size_gb:.2f} GB). Maximum file size is {max_gb:.0f} GB."
        )


def _check_duplicate_filename(filename: str, user_id: int, db: Session) -> None:
    """Check for duplicate filename if duplicates are not allowed
    
    Args:
        filename: File name to check
        user_id: User ID
        db: Database session
        
    Raises:
        ValueError: If duplicate found and duplicates not allowed
    """
    global_settings = get_user_settings(user_id, "global", db=db)
    if not global_settings.get("allow_duplicates", False):
        existing_videos = get_user_videos(user_id, db=db)
        if any(v.filename == filename for v in existing_videos):
            raise ValueError(f"Duplicate video: {filename} is already in the queue")


def _generate_r2_object_key(filename: str, user_id: int) -> str:
    """Generate unique R2 object key
    
    Args:
        filename: File name
        user_id: User ID
        
    Returns:
        R2 object key: user_{user_id}/pending_{timestamp}_{filename}
    """
    timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
    return f"user_{user_id}/pending_{timestamp}_{filename}"


def _validate_object_key_ownership(object_key: str, user_id: int) -> None:
    """Validate that object_key belongs to user
    
    Args:
        object_key: R2 object key to validate
        user_id: User ID
        
    Raises:
        ValueError: If object_key does not belong to user
    """
    if not object_key.startswith(f"user_{user_id}/"):
        raise ValueError("Invalid object key for user")


async def confirm_upload(
    object_key: str,
    filename: str,
    file_size: int,
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Confirm upload and create video record after R2 upload completes
    
    This function is called after a file has been successfully uploaded to R2
    using presigned URLs. It validates the R2 object, creates the video record,
    and returns the video data.
    
    Args:
        object_key: R2 object key where file was uploaded
        filename: Original filename
        file_size: File size in bytes
        user_id: User ID
        db: Database session
        
    Returns:
        Dict with video response (same format as GET /api/videos)
        
    Raises:
        ValueError: For validation errors (duplicate, R2 object not found, etc.)
        Exception: For database or R2 errors
    """
    upload_logger.info(
        f"Confirming upload for user {user_id}: {filename} "
        f"({file_size / (1024*1024):.2f} MB, R2 key: {object_key})"
    )
    
    # Validate object_key belongs to user
    _validate_object_key_ownership(object_key, user_id)
    
    # Get user settings
    global_settings = get_user_settings(user_id, "global", db=db)
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    
    # Check for duplicates if not allowed
    _check_duplicate_filename(filename, user_id, db)
    
    # Verify R2 object exists
    r2_service = get_r2_service()
    if not r2_service.object_exists(object_key):
        upload_logger.error(
            f"R2 object not found for user {user_id}: {filename} at {object_key}"
        )
        raise ValueError(f"Upload failed: file was not saved to R2")
    
    # Verify R2 object size matches expected size
    r2_object_size = r2_service.get_object_size(object_key)
    if r2_object_size and r2_object_size != file_size:
        upload_logger.warning(
            f"File size mismatch for user {user_id}: {filename}. "
            f"Expected: {file_size} bytes, R2 object size: {r2_object_size} bytes"
        )
        # Use actual R2 size if available
        if r2_object_size:
            file_size = r2_object_size
    
    # Calculate tokens required for this upload (1 token = 10MB)
    tokens_required = calculate_tokens_from_bytes(file_size)
    
    # Check token availability before adding to queue
    if not check_tokens_available(user_id, tokens_required, db, include_queued_videos=True):
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
            f"Video upload blocked for user {user_id}: {filename} - {error_msg}"
        )
        raise ValueError(error_msg)
    
    # Generate YouTube title and description (to prevent re-randomization)
    filename_no_ext = filename.rsplit('.', 1)[0]
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
    
    # Add to database with file size and tokens
    # Store R2 object key in path field
    video = add_user_video(
        user_id=user_id,
        filename=filename,
        path=object_key,  # Store R2 object key
        generated_title=youtube_title,
        generated_description=youtube_description,
        file_size_bytes=file_size,
        tokens_required=tokens_required,
        tokens_consumed=0,  # Don't consume tokens yet - only on successful upload
        db=db
    )
    
    # Update R2 object key to final format: user_{user_id}/video_{video_id}_{filename}
    final_r2_key = f"user_{user_id}/video_{video.id}_{filename}"
    if object_key != final_r2_key:
        # Copy object to new key (R2 doesn't support rename, so we copy and delete)
        try:
            if r2_service.copy_object(object_key, final_r2_key):
                r2_service.delete_object(object_key)
                # Update database with final key
                video.path = final_r2_key
                db.commit()
                upload_logger.info(f"Renamed R2 object from {object_key} to {final_r2_key}")
            else:
                upload_logger.warning(f"Failed to copy R2 object from {object_key} to {final_r2_key}. Using original key.")
        except Exception as e:
            upload_logger.warning(f"Failed to rename R2 object from {object_key} to {final_r2_key}: {e}. Using original key.")
            # Continue with original key - not critical
    
    upload_logger.info(f"Video added to queue for user {user_id}: {filename} ({file_size / (1024*1024):.2f} MB, will cost {tokens_required} tokens on upload)")
    
    # Build video response using the same helper function as GET endpoint
    all_settings = get_all_user_settings(user_id, db=db)
    all_tokens = get_all_oauth_tokens(user_id, db=db)
    video_dict = build_video_response(video, all_settings, all_tokens, user_id)
    
    # Publish event with full video data
    from app.services.event_service import publish_video_added
    await publish_video_added(user_id, video_dict)
    
    # Return the same format as GET /api/videos for consistency
    return video_dict


# Service functions for presigned upload operations
def get_presigned_upload_url_service(
    filename: str,
    file_size: int,
    content_type: Optional[str],
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Get presigned URL for single file upload to R2
    
    Args:
        filename: File name
        file_size: File size in bytes
        content_type: Optional content type (MIME type)
        user_id: User ID
        db: Database session
        
    Returns:
        Dict with upload_url, object_key, expires_in
        
    Raises:
        ValueError: For validation errors (file too large, duplicate)
        Exception: For R2 errors
    """
    _validate_file_size(file_size, filename)
    _check_duplicate_filename(filename, user_id, db)
    
    object_key = _generate_r2_object_key(filename, user_id)
    
    r2_service = get_r2_service()
    upload_url = r2_service.generate_upload_url(
        object_key,
        content_type=content_type,
        expires_in=settings.R2_PRESIGNED_URL_EXPIRY
    )
    
    return {
        "upload_url": upload_url,
        "object_key": object_key,
        "expires_in": settings.R2_PRESIGNED_URL_EXPIRY
    }


def initiate_multipart_upload_service(
    filename: str,
    file_size: int,
    content_type: Optional[str],
    user_id: int,
    db: Session
) -> Dict[str, Any]:
    """Initiate multipart upload for large files
    
    Args:
        filename: File name
        file_size: File size in bytes
        content_type: Optional content type (MIME type)
        user_id: User ID
        db: Database session
        
    Returns:
        Dict with upload_id, object_key, expires_in
        
    Raises:
        ValueError: For validation errors (file too large, duplicate)
        Exception: For R2 errors
    """
    _validate_file_size(file_size, filename)
    _check_duplicate_filename(filename, user_id, db)
    
    object_key = _generate_r2_object_key(filename, user_id)
    
    r2_service = get_r2_service()
    upload_id = r2_service.create_multipart_upload(
        object_key,
        content_type=content_type
    )
    
    return {
        "upload_id": upload_id,
        "object_key": object_key,
        "expires_in": settings.R2_PRESIGNED_URL_EXPIRY
    }


def get_multipart_part_url_service(
    object_key: str,
    upload_id: str,
    part_number: int,
    user_id: int
) -> Dict[str, Any]:
    """Get presigned URL for uploading a part in multipart upload
    
    Args:
        object_key: R2 object key
        upload_id: Multipart upload ID
        part_number: Part number (1-indexed)
        user_id: User ID
        
    Returns:
        Dict with upload_url, expires_in
        
    Raises:
        ValueError: For validation errors (invalid object key)
        Exception: For R2 errors
    """
    _validate_object_key_ownership(object_key, user_id)
    
    r2_service = get_r2_service()
    upload_url = r2_service.generate_presigned_url_for_part(
        object_key,
        upload_id,
        part_number,
        expires_in=settings.R2_PRESIGNED_URL_EXPIRY
    )
    
    return {
        "upload_url": upload_url,
        "expires_in": settings.R2_PRESIGNED_URL_EXPIRY
    }


def complete_multipart_upload_service(
    object_key: str,
    upload_id: str,
    parts: List[Dict[str, any]],
    user_id: int
) -> Dict[str, Any]:
    """Complete multipart upload in R2
    
    Args:
        object_key: R2 object key
        upload_id: Multipart upload ID
        parts: List of dicts with 'PartNumber' and 'ETag' keys
        user_id: User ID
        
    Returns:
        Dict with object_key, size
        
    Raises:
        ValueError: For validation errors (invalid object key)
        Exception: For R2 errors
    """
    _validate_object_key_ownership(object_key, user_id)
    
    r2_service = get_r2_service()
    
    # Format parts for boto3
    formatted_parts = [
        {"PartNumber": p["PartNumber"], "ETag": p["ETag"]}
        for p in parts
    ]
    
    success = r2_service.complete_multipart_upload(
        object_key,
        upload_id,
        formatted_parts
    )
    
    if not success:
        raise Exception("Failed to complete multipart upload")
    
    # Get object size
    object_size = r2_service.get_object_size(object_key)
    
    return {
        "object_key": object_key,
        "size": object_size or 0
    }


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

