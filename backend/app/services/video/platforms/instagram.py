"""Instagram-specific upload logic"""

import asyncio
import logging
from pathlib import Path
import httpx
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from app.core.config import INSTAGRAM_GRAPH_API_BASE, settings
from app.db.helpers import get_user_videos, get_user_settings, get_oauth_token, update_video
from app.db.redis import set_upload_progress, delete_upload_progress, get_upload_progress, set_platform_upload_progress, get_platform_upload_progress
from app.services.token_service import check_tokens_available, get_token_balance, deduct_tokens, calculate_tokens_from_bytes
from app.utils.encryption import decrypt
from app.utils.templates import get_video_title
from app.utils.video_tokens import generate_video_access_token
from app.services.video.helpers import record_platform_error

instagram_logger = logging.getLogger("instagram")


# ============================================================================
# DRY HELPER FUNCTIONS
# ============================================================================

def _get_instagram_setting(custom_settings: Dict, instagram_settings: Dict, key: str, default: Any = None) -> Any:
    """DRY: Get setting with custom override fallback"""
    return custom_settings.get(key, instagram_settings.get(key, default))


def _build_container_params(
    media_type: str,
    file_url: str,
    caption: str,
    custom_settings: Dict,
    instagram_settings: Dict
) -> Dict[str, Any]:
    """DRY: Build container params based on media type - extensible for new types"""
    params = {
        "media_type": media_type,
        "video_url": file_url,
        "caption": caption
    }
    
    # Reels-specific parameters
    if media_type == "REELS":
        share_to_feed = _get_instagram_setting(custom_settings, instagram_settings, 'share_to_feed', True)
        params["share_to_feed"] = share_to_feed
        
        # Commented out - removed Audio Name feature
        # Optional: audio name for Reels
        # audio_name = _get_instagram_setting(custom_settings, instagram_settings, 'audio_name')
        # if audio_name:
        #     params["audio_name"] = audio_name
    
    # Optional: custom thumbnail (works for both REELS and VIDEO)
    cover_url = _get_instagram_setting(custom_settings, instagram_settings, 'cover_url')
    if cover_url:
        params["cover_url"] = cover_url
    
    return params


async def _poll_container_status(
    client: httpx.AsyncClient,
    container_id: str,
    access_token: str,
    user_id: int,
    video_id: int,
    max_retries: int = 60,
    retry_delay: int = 60
) -> str:
    """DRY: Reusable status polling logic for any media type
    
    Returns:
        status_code when FINISHED
    
    Raises:
        Exception if ERROR, EXPIRED, timeout, or cancelled
    """
    # Import cancellation flag to check for cancellation during polling
    from app.services.video.orchestrator import _cancellation_flags
    from app.db.redis import set_active_upload_session, clear_active_upload_session
    
    instagram_logger.info(f"Polling container status for {container_id} (max {max_retries} attempts)")
    
    # Mark upload as active
    set_active_upload_session(video_id, "instagram")
    
    try:
        for attempt in range(max_retries):
            # Check for cancellation during polling
            if _cancellation_flags.get(video_id, False):
                instagram_logger.info(f"Instagram upload cancelled for video {video_id} during polling")
                raise Exception("Upload cancelled by user")
            
            status_url = f"{INSTAGRAM_GRAPH_API_BASE}/{container_id}"
            status_params = {
                "fields": "status_code",
                "access_token": access_token.strip()
            }
            
            status_response = await client.get(status_url, params=status_params)
            
            status_code = None
            if status_response.status_code == 200:
                status_data = status_response.json()
                status_code = status_data.get('status_code')
                
                instagram_logger.info(f"Container status: {status_code} (attempt {attempt + 1}/{max_retries})")
                
                if status_code == "FINISHED":
                    instagram_logger.info(f"Video processed successfully, ready to publish")
                    # FINISHED status = 90% (ready to publish)
                    progress = 90
                    set_upload_progress(user_id, video_id, progress)
                    set_platform_upload_progress(user_id, video_id, "instagram", progress)
                    # Publish final progress update
                    from app.services.event_service import publish_upload_progress
                    await publish_upload_progress(user_id, video_id, "instagram", progress)
                    return status_code
                elif status_code == "ERROR":
                    # ERROR can be transient - continue polling unless we've exhausted retries
                    if attempt == max_retries - 1:
                        raise Exception(f"Instagram video processing failed with ERROR status after {max_retries} attempts")
                    # Otherwise, continue polling (will retry on next iteration)
                    instagram_logger.debug(f"Container returned ERROR status (attempt {attempt + 1}/{max_retries}), continuing to poll...")
                elif status_code == "EXPIRED":
                    raise Exception(f"Container expired (not published within 24 hours)")
                # IN_PROGRESS - continue polling and update progress
            else:
                instagram_logger.warning(f"Status check failed with HTTP {status_response.status_code}, retrying...")
                # If status check failed, assume IN_PROGRESS for progress calculation
                status_code = "IN_PROGRESS"
            
            # Update progress during polling (for IN_PROGRESS status or when status unknown)
            if status_code == "IN_PROGRESS" or status_code is None:
                # Use time-based progress estimation for more realistic progress
                # Instagram typically processes videos in 2-5 minutes, but can take up to 10 minutes
                # Estimate: 20% at start, 90% at ~8 minutes (480 seconds)
                import time
                if not hasattr(_poll_container_status, '_start_times'):
                    _poll_container_status._start_times = {}
                
                if video_id not in _poll_container_status._start_times:
                    _poll_container_status._start_times[video_id] = time.time()
                
                elapsed_time = time.time() - _poll_container_status._start_times[video_id]
                # Estimate 8 minutes (480 seconds) for typical processing
                estimated_total_time = 480
                
                # Time-based progress (more realistic)
                time_progress = 20 + int((elapsed_time / estimated_total_time) * 70)
                time_progress = min(89, max(20, time_progress))
                
                # Attempt-based progress (fallback)
                current_attempt = attempt + 1
                attempt_progress = 20 + int((current_attempt / max_retries) * 70)
                attempt_progress = min(89, max(20, attempt_progress))
                
                # Use the higher of the two for more optimistic progress
                progress = max(time_progress, attempt_progress)
                
                # Get previous progress to check if we should publish
                from app.db.redis import get_platform_upload_progress, get_upload_progress
                previous_progress = get_platform_upload_progress(user_id, video_id, "instagram") or get_upload_progress(user_id, video_id) or 20
                
                # Always update progress
                set_upload_progress(user_id, video_id, progress)
                set_platform_upload_progress(user_id, video_id, "instagram", progress)
                
                # Publish WebSocket progress event (always publish if progress increased)
                from app.services.event_service import publish_upload_progress
                # Publish if it's the first attempt, or if progress increased by at least 1%
                if attempt == 0 or progress > previous_progress:
                    await publish_upload_progress(user_id, video_id, "instagram", progress)
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
    finally:
        # Always clear the active session flag when done (success or failure)
        clear_active_upload_session(video_id, "instagram")
        # Clean up start time tracking
        if hasattr(_poll_container_status, '_start_times') and video_id in _poll_container_status._start_times:
            del _poll_container_status._start_times[video_id]
    
    raise Exception(f"Video processing timeout after {max_retries * retry_delay} seconds")


def _build_error_context(
    user_id: int,
    video_id: int,
    video_filename: str,
    stage: str,
    http_status: Optional[int] = None,
    **extra_fields
) -> Dict[str, Any]:
    """DRY: Build structured error context for logging"""
    context = {
        "user_id": user_id,
        "video_id": video_id,
        "video_filename": video_filename,
        "platform": "instagram",
        "stage": stage,
    }
    
    if http_status:
        context["http_status"] = http_status
    
    context.update(extra_fields)
    return context


# ============================================================================
# MAIN UPLOAD FUNCTION
# ============================================================================

async def upload_video_to_instagram(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to Instagram using file_url method (like TikTok)"""
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    # Import cancellation flag to check for cancellation during upload
    from app.services.video.orchestrator import _cancellation_flags
    
    # Check for cancellation before starting
    if _cancellation_flags.get(video_id, False):
        instagram_logger.info(f"Instagram upload cancelled for video {video_id} before starting")
        raise Exception("Upload cancelled by user")
    
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        instagram_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    if video.tokens_consumed == 0:
        tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
        if tokens_required > 0 and not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            instagram_logger.error(
                f"❌ Instagram upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra=_build_error_context(
                    user_id, video_id, video.filename, "token_check",
                    file_size_bytes=video.file_size_bytes,
                    tokens_required=tokens_required,
                    tokens_remaining=tokens_remaining,
                    error_type="InsufficientTokens"
                )
            )
            
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            return
    
    instagram_token = get_oauth_token(user_id, "instagram", db=db)
    if not instagram_token:
        error_msg = "No credentials"
        instagram_logger.error(
            f"❌ Instagram upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
            extra=_build_error_context(user_id, video_id, video.filename, "credentials", error_type="MissingCredentials")
        )
        record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
        failed_uploads_gauge.inc()
        return
    
    access_token = decrypt(instagram_token.access_token)
    if not access_token:
        record_platform_error(video_id, user_id, "instagram", "Failed to decrypt token", db=db)
        instagram_logger.error("Failed to decrypt Instagram token")
        return
    
    extra_data = instagram_token.extra_data or {}
    business_account_id = extra_data.get("business_account_id")
    if not business_account_id:
        record_platform_error(video_id, user_id, "instagram", "No Business Account ID. Please reconnect your Instagram account.", db=db)
        instagram_logger.error("No Instagram Business Account ID")
        return
    
    instagram_settings = get_user_settings(user_id, "instagram", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    instagram_logger.info(f"Starting upload for {video.filename}")
    
    # Mark upload as active at the start
    from app.db.redis import set_active_upload_session, clear_active_upload_session
    set_active_upload_session(video_id, "instagram")
    
    # Note: Status is already set to "uploading" by orchestrator and event is published
    # No need to set it again here - orchestrator handles status change events
    
    try:
        # Set initial progress and publish immediately so frontend sees it
        set_upload_progress(user_id, video_id, 0)
        set_platform_upload_progress(user_id, video_id, "instagram", 0)
        from app.services.event_service import publish_upload_progress
        await publish_upload_progress(user_id, video_id, "instagram", 0)
        
        # Verify R2 object exists
        if not video.path:
            error_msg = f"Video has no R2 object key"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - No R2 object key - User {user_id}, Video {video_id} ({video.filename})",
                extra=_build_error_context(
                    user_id, video_id, video.filename, "file_check",
                    error_type="FileNotFound"
                )
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        # After file validation, update progress
        set_upload_progress(user_id, video_id, 5)
        set_platform_upload_progress(user_id, video_id, "instagram", 5)
        await publish_upload_progress(user_id, video_id, "instagram", 5)
        
        from app.services.storage.r2_service import get_r2_service
        r2_service = get_r2_service()
        
        if not r2_service.object_exists(video.path):
            # Check if this is an old local path
            from app.services.storage.r2_service import _is_old_local_path
            if _is_old_local_path(video.path):
                error_msg = f"Video has old local file path (pre-R2 migration): {video.path}. Please re-upload the video."
            else:
                error_msg = f"R2 object not found: {video.path}"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - R2 object not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"R2 object key: {video.path}",
                extra=_build_error_context(
                    user_id, video_id, video.filename, "file_check",
                    r2_object_key=video.path,
                    error_type="FileNotFound"
                )
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        # After R2 check passes, update progress
        set_upload_progress(user_id, video_id, 7)
        set_platform_upload_progress(user_id, video_id, "instagram", 7)
        await publish_upload_progress(user_id, video_id, "instagram", 7)
        
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        caption = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=instagram_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='caption_template'
        )
        
        caption = (caption or filename_no_ext)[:2200]
        
        media_type = _get_instagram_setting(custom_settings, instagram_settings, 'media_type', 'REELS')
        
        instagram_logger.info(f"Uploading {video.filename} to Instagram as {media_type} using file_url method")
        
        # After getting settings, update progress
        set_upload_progress(user_id, video_id, 10)
        set_platform_upload_progress(user_id, video_id, "instagram", 10)
        await publish_upload_progress(user_id, video_id, "instagram", 10)
        
        # Get video URL using DRY helper (validates custom domain URLs)
        from app.services.storage.r2_service import get_video_download_url
        try:
            file_url = get_video_download_url(video.path, r2_service)
            instagram_logger.info(
                f"Using custom domain URL for Instagram download: {file_url}, R2 path: {video.path}"
            )
        except ValueError as url_error:
            error_msg = f"Failed to generate video URL: {str(url_error)}"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - URL generation error - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                extra=_build_error_context(
                    user_id, video_id, video.filename, "url_generation",
                    r2_object_key=video.path,
                    error_type="URLGenerationFailed"
                )
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            raise ValueError(error_msg)
        
        # After URL generation, update progress
        set_upload_progress(user_id, video_id, 15)
        set_platform_upload_progress(user_id, video_id, "instagram", 15)
        await publish_upload_progress(user_id, video_id, "instagram", 15)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            container_url = f"{INSTAGRAM_GRAPH_API_BASE}/{business_account_id}/media"
            container_params = _build_container_params(
                media_type, file_url, caption, custom_settings, instagram_settings
            )
            
            container_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Creating media container with file_url for {video.filename}")
            
            container_response = await client.post(
                container_url,
                json=container_params,
                headers=container_headers
            )
            
            if container_response.status_code != 200:
                import json as json_module
                error_data = container_response.json() if container_response.headers.get('content-type', '').startswith('application/json') else container_response.text
                
                error_context = _build_error_context(
                    user_id, video_id, video.filename, "create_container",
                    http_status=container_response.status_code,
                    business_account_id=business_account_id,
                    response_data=json_module.dumps(error_data) if isinstance(error_data, (dict, list)) else str(error_data),
                    response_headers=json_module.dumps(dict(container_response.headers))
                )
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context.update({
                        "error_code": error_obj.get('code'),
                        "error_message": error_obj.get('message'),
                        "error_type": error_obj.get('type')
                    })
                    
                    if error_obj.get('code') == 190:
                        error_msg = "Instagram access token is invalid or expired. Please reconnect your Instagram account."
                        instagram_logger.error(
                            f"❌ Instagram upload FAILED - Token expired - User {user_id}, Video {video_id} ({video.filename}): "
                            f"HTTP {container_response.status_code} - {error_msg}",
                            extra=error_context
                        )
                        raise Exception(error_msg)
                    
                    # Include file URL in error context for debugging (especially for custom domain issues)
                    error_context["file_url"] = file_url if 'file_url' in locals() else "unknown"
                    error_context["r2_public_domain"] = settings.R2_PUBLIC_DOMAIN
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Container creation error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {container_response.status_code}",
                    extra=error_context
                )
                raise Exception(f"Failed to create media container: {error_data}")
            
            container_result = container_response.json()
            container_id = container_result.get('id')
            
            if not container_id:
                raise Exception(f"No container ID in response: {container_result}")
            
            instagram_logger.info(f"Created container {container_id}, Instagram will now download video from file_url")
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_container_id'] = container_id
            update_video(video_id, user_id, db=db, custom_settings=custom_settings)
            
            # Container created, start polling at 20% - publish immediately
            set_upload_progress(user_id, video_id, 20)
            set_platform_upload_progress(user_id, video_id, "instagram", 20)
            await publish_upload_progress(user_id, video_id, "instagram", 20)
            
            instagram_logger.info(f"Waiting for Instagram to process video from URL...")
            
            await _poll_container_status(
                client, container_id, access_token, user_id, video_id,
                max_retries=120, retry_delay=10  # Poll every 10 seconds for more frequent updates
            )
            
            # Check for cancellation after polling completes
            if _cancellation_flags.get(video_id, False):
                instagram_logger.info(f"Instagram upload cancelled for video {video_id} after polling")
                raise Exception("Upload cancelled by user")
            
            # After FINISHED, publish step = 100%
            progress = 100
            set_upload_progress(user_id, video_id, progress)
            set_platform_upload_progress(user_id, video_id, "instagram", progress)
            from app.services.event_service import publish_upload_progress
            await publish_upload_progress(user_id, video_id, "instagram", progress)
            
            # Check for cancellation before publishing
            if _cancellation_flags.get(video_id, False):
                instagram_logger.info(f"Instagram upload cancelled for video {video_id} before publishing")
                raise Exception("Upload cancelled by user")
            
            publish_url = f"{INSTAGRAM_GRAPH_API_BASE}/{business_account_id}/media_publish"
            publish_data = {
                "creation_id": container_id
            }
            publish_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Publishing container {container_id}")
            
            publish_response = await client.post(
                publish_url,
                json=publish_data,
                headers=publish_headers
            )
            
            if publish_response.status_code != 200:
                import json as json_module
                error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else publish_response.text
                
                error_context = _build_error_context(
                    user_id, video_id, video.filename, "publish_media",
                    http_status=publish_response.status_code,
                    container_id=container_id,
                    response_data=json_module.dumps(error_data) if isinstance(error_data, (dict, list)) else str(error_data),
                    response_headers=json_module.dumps(dict(publish_response.headers))
                )
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context.update({
                        "error_code": error_obj.get('code'),
                        "error_message": error_obj.get('message'),
                        "error_type": error_obj.get('type')
                    })
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Publish error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {publish_response.status_code}",
                    extra=error_context
                )
                raise Exception(f"Failed to publish media: {error_data}")
            
            publish_result = publish_response.json()
            media_id = publish_result.get('id')
            
            if not media_id:
                raise Exception(f"No media ID in publish response: {publish_result}")
            
            instagram_logger.info(f"Successfully published to Instagram: {media_id}")
            
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_id'] = media_id
            update_video(video_id, user_id, db=db, status="completed", custom_settings=custom_settings)
            set_upload_progress(user_id, video_id, 100)
            
            successful_uploads_counter.inc()
            
            if video.tokens_consumed == 0:
                tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
                if tokens_required > 0:
                    await deduct_tokens(
                        user_id=user_id,
                        tokens=tokens_required,
                        transaction_type='upload',
                        video_id=video.id,
                        metadata={
                            'filename': video.filename,
                            'platform': 'instagram',
                            'instagram_id': media_id,
                            'file_size_bytes': video.file_size_bytes,
                            'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                        },
                        db=db
                    )
                    update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
                    instagram_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
            else:
                instagram_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
            
            await asyncio.sleep(2)
            delete_upload_progress(user_id, video_id)
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        context = _build_error_context(
            user_id, video_id, video.filename, "exception",
            file_size_bytes=video.file_size_bytes,
            file_size_mb=round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            tokens_consumed=video.tokens_consumed,
            error_type=error_type,
            error_message=error_msg
        )
        
        try:
            from app.services.storage.r2_service import get_r2_service
            r2_service = get_r2_service()
            if video.path:
                context["r2_object_key"] = video.path
                context["r2_object_exists"] = r2_service.object_exists(video.path)
                r2_size = r2_service.get_object_size(video.path)
                if r2_size:
                    context["actual_file_size_bytes"] = r2_size
        except Exception:
            pass
        
        try:
            balance_info = get_token_balance(user_id, db)
            if balance_info:
                context["tokens_remaining"] = balance_info.get('tokens_remaining', 0)
                context["tokens_used_this_period"] = balance_info.get('tokens_used_this_period', 0)
        except Exception:
            pass
        
        try:
            if 'container_id' in locals():
                context["instagram_container_id"] = container_id
            if 'business_account_id' in locals():
                context["instagram_business_account_id"] = business_account_id
        except Exception:
            pass
        
        instagram_logger.error(
            f"❌ Instagram upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        error_message = f"Upload failed: {error_type}: {error_msg}"
        record_platform_error(video_id, user_id, "instagram", error_message, db=db)
        delete_upload_progress(user_id, video_id)
        
        update_video(video_id, user_id, db=db, status="failed", error=error_message)
        failed_uploads_gauge.inc()
    finally:
        # Always clear the active session flag when upload completes (success or failure)
        clear_active_upload_session(video_id, "instagram")