"""Instagram-specific upload logic"""

import asyncio
import logging
from pathlib import Path
import httpx
from sqlalchemy.orm import Session

from app.core.config import INSTAGRAM_GRAPH_API_BASE
from app.db.helpers import get_user_videos, get_user_settings, get_oauth_token, update_video
from app.db.redis import set_upload_progress, delete_upload_progress
from app.services.token_service import check_tokens_available, get_token_balance, deduct_tokens, calculate_tokens_from_bytes
from app.utils.encryption import decrypt
from app.utils.templates import get_video_title
from app.services.video.helpers import record_platform_error

instagram_logger = logging.getLogger("instagram")


async def upload_video_to_instagram(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to Instagram - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        instagram_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.tokens_consumed == 0:
        # Use stored tokens_required with fallback for backward compatibility
        tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
        if tokens_required > 0 and not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            instagram_logger.error(
                f"❌ Instagram upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "instagram",
                    "error_type": "InsufficientTokens",
                }
            )
            
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            failed_uploads_gauge.inc()
            return
    
    # Get Instagram credentials from database
    instagram_token = get_oauth_token(user_id, "instagram", db=db)
    if not instagram_token:
            error_msg = "No credentials"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "error_type": "MissingCredentials",
                }
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            failed_uploads_gauge.inc()
            return
    
    # Decrypt access token
    access_token = decrypt(instagram_token.access_token)
    if not access_token:
        record_platform_error(video_id, user_id, "instagram", "Failed to decrypt token", db=db)
        instagram_logger.error("Failed to decrypt Instagram token")
        return
    
    # Get business account ID from extra_data
    extra_data = instagram_token.extra_data or {}
    business_account_id = extra_data.get("business_account_id")
    if not business_account_id:
        record_platform_error(video_id, user_id, "instagram", "No Business Account ID. Please reconnect your Instagram account.", db=db)
        instagram_logger.error("No Instagram Business Account ID")
        return
    
    # Get settings from database
    instagram_settings = get_user_settings(user_id, "instagram", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    instagram_logger.info(f"Starting upload for {video.filename}")
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        # Get video file
        video_path = Path(video.path).resolve()
        if not video_path.exists():
            error_msg = f"Video file not found: {video_path}"
            instagram_logger.error(
                f"❌ Instagram upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Path: {video_path}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "video_path": str(video_path),
                    "platform": "instagram",
                    "error_type": "FileNotFound",
                }
            )
            record_platform_error(video_id, user_id, "instagram", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        # Prepare caption
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get caption using consistent priority logic
        caption = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=instagram_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='caption_template'
        )
        
        caption = (caption or filename_no_ext)[:2200]
        
        # Get settings: per-video custom > destination settings
        location_id = custom_settings.get('location_id', instagram_settings.get('location_id', ''))
        
        instagram_logger.info(f"Uploading {video.filename} to Instagram")
        set_upload_progress(user_id, video_id, 10)
        
        # Read video file
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        video_size = len(video_data)
        set_upload_progress(user_id, video_id, 20)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Step 1: Create resumable upload container
            container_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{business_account_id}/media"
            container_params = {
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption
            }
            
            if location_id:
                container_params["location_id"] = location_id
            
            container_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Creating resumable upload container for {video.filename}")
            
            container_response = await client.post(
                container_url,
                json=container_params,
                headers=container_headers
            )
            
            if container_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": container_response.status_code,
                    "stage": "create_container",
                    "business_account_id": business_account_id,
                }
                
                error_data = container_response.json() if container_response.headers.get('content-type', '').startswith('application/json') else container_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(container_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                    
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
                raise Exception(f"Failed to create resumable upload container: {error_data}")
            
            container_result = container_response.json()
            container_id = container_result.get('id')
            
            if not container_id:
                raise Exception(f"No container ID in response: {container_result}")
            
            instagram_logger.info(f"Created container {container_id}")
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_container_id'] = container_id
            update_video(video_id, user_id, db=db, custom_settings=custom_settings)
            set_upload_progress(user_id, video_id, 40)
            
            # Step 2: Upload video to rupload.facebook.com
            upload_url = f"https://rupload.facebook.com/ig-api-upload/v21.0/{container_id}"
            upload_headers = {
                "Authorization": f"OAuth {access_token}",
                "offset": "0",
                "file_size": str(video_size)
            }
            
            instagram_logger.info(f"Uploading video data ({video_size} bytes) to rupload.facebook.com")
            
            upload_response = await client.post(
                upload_url,
                headers=upload_headers,
                content=video_data
            )
            
            if upload_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": upload_response.status_code,
                    "stage": "upload_video_data",
                    "container_id": container_id if 'container_id' in locals() else None,
                    "video_size": video_size if 'video_size' in locals() else None,
                }
                
                error_data = upload_response.json() if upload_response.headers.get('content-type', '').startswith('application/json') else upload_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(upload_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Video upload error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {upload_response.status_code}",
                    extra=error_context
                )
                instagram_logger.error(f"Failed to upload video: {error_data}")
                raise Exception(f"Failed to upload video data: {error_data}")
            
            upload_result = upload_response.json()
            if not upload_result.get('success'):
                raise Exception(f"Upload failed: {upload_result}")
            
            instagram_logger.info(f"Video uploaded successfully")
            set_upload_progress(user_id, video_id, 70)
            
            # Step 3: Wait for Instagram to process the video and check status
            instagram_logger.info(f"Waiting for Instagram to process video")
            await asyncio.sleep(5)
            
            # Check container status
            status_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{container_id}"
            status_params = {
                "fields": "status_code"
            }
            status_headers = {
                "Authorization": f"Bearer {access_token.strip()}"
            }
            
            for attempt in range(5):  # Check up to 5 times
                status_response = await client.get(status_url, params=status_params, headers=status_headers)
                if status_response.status_code == 200:
                    status_result = status_response.json()
                    status_code = status_result.get('status_code')
                    instagram_logger.info(f"Container status (attempt {attempt + 1}): {status_code}")
                    
                    if status_code == 'FINISHED':
                        break
                    elif status_code == 'ERROR':
                        raise Exception(f"Container processing failed")
                    elif status_code == 'EXPIRED':
                        raise Exception(f"Container expired")
                
                if attempt < 4:
                    await asyncio.sleep(60)  # Wait 60 seconds before checking again
            
            set_upload_progress(user_id, video_id, 85)
            
            # Step 4: Publish the container
            publish_url = f"{INSTAGRAM_GRAPH_API_BASE}/v21.0/{business_account_id}/media_publish"
            publish_params = {
                "creation_id": container_id
            }
            publish_headers = {
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json"
            }
            
            instagram_logger.info(f"Publishing container {container_id}")
            
            publish_response = await client.post(publish_url, json=publish_params, headers=publish_headers)
            
            if publish_response.status_code != 200:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "instagram",
                    "http_status": publish_response.status_code,
                    "stage": "publish_media",
                    "container_id": container_id if 'container_id' in locals() else None,
                }
                
                error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else publish_response.text
                if isinstance(error_data, (dict, list)):
                    error_context["response_data"] = json_module.dumps(error_data)
                else:
                    error_context["response_data"] = str(error_data)
                error_context["response_headers"] = json_module.dumps(dict(publish_response.headers))
                
                if isinstance(error_data, dict):
                    error_obj = error_data.get('error', {})
                    error_context["error_code"] = error_obj.get('code')
                    error_context["error_message"] = error_obj.get('message')
                    error_context["error_type"] = error_obj.get('type')
                
                instagram_logger.error(
                    f"❌ Instagram upload FAILED - Publish error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {publish_response.status_code}",
                    extra=error_context
                )
                instagram_logger.error(f"Failed to publish: {error_data}")
                raise Exception(f"Failed to publish media: {error_data}")
            
            publish_result = publish_response.json()
            media_id = publish_result.get('id')
            
            if not media_id:
                raise Exception(f"No media ID in publish response: {publish_result}")
            
            instagram_logger.info(f"Published to Instagram: {media_id}")
            
            # Update video in database with success
            custom_settings = custom_settings.copy() if custom_settings else {}
            custom_settings['instagram_id'] = media_id
            update_video(video_id, user_id, db=db, status="completed", custom_settings=custom_settings)
            set_upload_progress(user_id, video_id, 100)
            
            # Increment successful uploads counter
            successful_uploads_counter.inc()
            
            # Deduct tokens after successful upload (only if not already deducted)
            if video.tokens_consumed == 0:
                # Use stored tokens_required with fallback for backward compatibility
                tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
                if tokens_required > 0:
                    deduct_tokens(
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
                # Update tokens_consumed in video record to prevent double-charging
                update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
                instagram_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
            else:
                instagram_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
            
            # Clean up progress after a delay
            await asyncio.sleep(2)
            delete_upload_progress(user_id, video_id)
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        context = {
            "user_id": user_id,
            "video_id": video_id,
            "video_filename": video.filename,
            "file_size_bytes": video.file_size_bytes,
            "file_size_mb": round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            "tokens_consumed": video.tokens_consumed,
            "platform": "instagram",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
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
            if 'video_size' in locals():
                context["uploaded_video_size"] = video_size
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

