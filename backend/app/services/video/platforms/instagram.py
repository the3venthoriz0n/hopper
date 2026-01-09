"""Instagram-specific upload logic"""

import asyncio
import logging
from pathlib import Path
import httpx
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from app.core.config import INSTAGRAM_GRAPH_API_BASE, settings
from app.db.helpers import get_user_videos, get_user_settings, get_oauth_token, update_video
from app.db.redis import set_upload_progress, delete_upload_progress, get_upload_progress
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
    
    instagram_logger.info(f"Polling container status for {container_id} (max {max_retries} attempts)")
    
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
        
        if status_response.status_code == 200:
            status_data = status_response.json()
            status_code = status_data.get('status_code')
            
            instagram_logger.info(f"Container status: {status_code} (attempt {attempt + 1}/{max_retries})")
            
            if status_code == "FINISHED":
                instagram_logger.info(f"Video processed successfully, ready to publish")
                # FINISHED status = 90% (ready to publish)
                progress = 90
                set_upload_progress(user_id, video_id, progress)
                # Publish final progress update
                from app.services.event_service import publish_upload_progress
                await publish_upload_progress(user_id, video_id, "instagram", progress)
                return status_code
            elif status_code == "ERROR":
                raise Exception(f"Instagram video processing failed with ERROR status")
            elif status_code == "EXPIRED":
                raise Exception(f"Container expired (not published within 24 hours)")
            # IN_PROGRESS - continue polling
        else:
            instagram_logger.warning(f"Status check failed with HTTP {status_response.status_code}, retrying...")
        
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            
            # Map status_code to progress percentages
            # IN_PROGRESS: 20-90% (Instagram downloading/processing from our server)
            # FINISHED: 90% (ready to publish)
            if status_code == "IN_PROGRESS":
                # Distribute progress 20-90% based on attempts
                progress = 20 + int((attempt / max_retries) * 70)
            else:
                # For other statuses, use previous progress or default
                progress = get_upload_progress(user_id, video_id) or 20
            
            set_upload_progress(user_id, video_id, progress)
            
            # Publish WebSocket progress event (1% increments or at first attempt)
            previous_progress = get_upload_progress(user_id, video_id) or 0
            from app.services.video.helpers import should_publish_progress
            from app.services.event_service import publish_upload_progress
            if should_publish_progress(progress, previous_progress) or attempt == 0:
                await publish_upload_progress(user_id, video_id, "instagram", progress)
    
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
            failed_uploads_gauge.inc()
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
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        video_path = Path(video.path).resolve()
        if not video_path.exists():
            error_msg = f"Video file not found: {video_path}"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Path: {video_path}",
                extra=_build_error_context(
                    user_id, video_id, video.filename, "file_check",
                    video_path=str(video_path),
                    error_type="FileNotFound"
                )
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
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
        set_upload_progress(user_id, video_id, 10)
        
        video_access_token = generate_video_access_token(video_id, user_id, expires_in_hours=1)
        file_url = f"{settings.BACKEND_URL.rstrip('/')}/api/videos/{video_id}/file?token={video_access_token}"
        
        instagram_logger.info(f"Generated secure file_url for Instagram to download")
        set_upload_progress(user_id, video_id, 20)
        
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
            # Container created, start polling at 20% (IN_PROGRESS range starts)
            set_upload_progress(user_id, video_id, 20)
            
            instagram_logger.info(f"Waiting for Instagram to process video from URL...")
            
            await _poll_container_status(
                client, container_id, access_token, user_id, video_id,
                max_retries=60, retry_delay=60
            )
            
            # Check for cancellation after polling completes
            if _cancellation_flags.get(video_id, False):
                instagram_logger.info(f"Instagram upload cancelled for video {video_id} after polling")
                raise Exception("Upload cancelled by user")
            
            # After FINISHED, publish step = 100%
            progress = 100
            set_upload_progress(user_id, video_id, progress)
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
            video_path = Path(video.path).resolve() if video.path else None
            if video_path:
                context["video_path"] = str(video_path)
                context["file_exists"] = video_path.exists()
                if video_path.exists():
                    context["actual_file_size_bytes"] = video_path.stat().st_size
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
        
        failed_uploads_gauge.inc()
