"""YouTube-specific upload logic"""

import logging
from pathlib import Path
from sqlalchemy.orm import Session

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.core.config import settings
from app.db.helpers import (
    get_user_videos, get_user_settings, get_oauth_token,
    oauth_token_to_credentials, credentials_to_oauth_token_data,
    save_oauth_token, update_video
)
from app.db.redis import set_upload_progress, delete_upload_progress
from app.services.event_service import publish_upload_progress
from app.services.token_service import check_tokens_available, get_token_balance, deduct_tokens, calculate_tokens_from_bytes
from app.utils.templates import get_video_title, get_video_description, replace_template_placeholders
from app.services.video.helpers import record_platform_error

youtube_logger = logging.getLogger("youtube")


async def upload_video_to_youtube(user_id: int, video_id: int, db: Session = None):
    """Upload a single video to YouTube - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    # Import cancellation flag to check for cancellation during upload
    from app.services.video.orchestrator import _cancellation_flags
    
    # Check for cancellation before starting
    if _cancellation_flags.get(video_id, False):
        youtube_logger.info(f"YouTube upload cancelled for video {video_id} before starting")
        raise Exception("Upload cancelled by user")
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        youtube_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.tokens_consumed == 0:
        # Use stored tokens_required with fallback for backward compatibility
        tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
        if tokens_required > 0 and not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            # Log with comprehensive context
            youtube_logger.error(
                f"❌ YouTube upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "youtube",
                    "error_type": "InsufficientTokens",
                }
            )
            
            record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
            failed_uploads_gauge.inc()
            return
    
    # Get YouTube credentials from database
    youtube_token = get_oauth_token(user_id, "youtube", db=db)
    if not youtube_token:
            error_msg = "No credentials"
            youtube_logger.error(
                f"❌ YouTube upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "youtube",
                    "error_type": "MissingCredentials",
                }
            )
            record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
            failed_uploads_gauge.inc()
            return
    
    # Convert OAuth token to Google Credentials
    youtube_creds = oauth_token_to_credentials(youtube_token, db=db)
    if not youtube_creds:
        record_platform_error(video_id, user_id, "youtube", "Failed to convert token to credentials", db=db)
        youtube_logger.error("Failed to convert YouTube token to credentials")
        return
    
    # Check if refresh_token is present (required for token refresh)
    if not youtube_creds.refresh_token:
        error_msg = "Refresh token is missing. Please disconnect and reconnect YouTube."
        record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
        youtube_logger.error(error_msg)
        return
    
    # Refresh token if expired (must be done before building YouTube client)
    if youtube_creds.expired:
        try:
            youtube_logger.debug("Refreshing expired YouTube token...")
            youtube_creds.refresh(GoogleRequest())
            
            # ROOT CAUSE FIX: Validate credentials after refresh
            if not youtube_creds.token:
                error_msg = "Failed to refresh token: No access token returned after refresh. Please disconnect and reconnect YouTube."
                record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
                youtube_logger.error(error_msg)
                return
            
            # Save refreshed token back to database
            token_data = credentials_to_oauth_token_data(
                youtube_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
            )
            
            # ROOT CAUSE FIX: Additional validation (credentials_to_oauth_token_data now raises on None, but double-check)
            if not token_data.get("access_token"):
                error_msg = "Failed to refresh token: No access token in token data. Please disconnect and reconnect YouTube."
                record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
                youtube_logger.error(error_msg)
                return
            
            save_oauth_token(
                user_id=user_id,
                platform="youtube",
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=token_data["expires_at"],
                extra_data=token_data["extra_data"],
                db=db
            )
            youtube_logger.debug("YouTube token refreshed successfully")
        except ValueError as ve:
            # ROOT CAUSE FIX: Handle validation errors from credentials_to_oauth_token_data
            error_msg = f"Failed to refresh token: {str(ve)}. Please disconnect and reconnect YouTube."
            record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
            youtube_logger.error(error_msg, exc_info=True)
            return
        except Exception as refresh_error:
            error_msg = f"Failed to refresh token: {str(refresh_error)}. Please disconnect and reconnect YouTube."
            record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
            youtube_logger.error(error_msg, exc_info=True)
            return
    
    # Get settings from database
    youtube_settings = get_user_settings(user_id, "youtube", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    youtube_logger.info(f"Starting upload for {video.filename}")
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
        youtube_logger.debug("Building YouTube API client...")
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Get video metadata
        # ROOT CAUSE FIX: Refresh video from database to ensure we have latest custom_settings
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get title using consistent priority logic (DRY - shared helper function)
        title = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=youtube_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='title_template'
        )
        
        # Enforce YouTube's 100 character limit for titles
        if len(title) > 100:
            title = title[:100]
        
        # Get description using consistent priority logic (DRY - shared helper function)
        description = get_video_description(
            video=video,
            custom_settings=custom_settings,
            destination_settings=youtube_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='description_template',
            default='Uploaded via hopper'
        )
        
        # Get visibility and made_for_kids: per-video custom > destination settings
        visibility = custom_settings.get('visibility', youtube_settings.get('visibility', 'private'))
        made_for_kids = custom_settings.get('made_for_kids', youtube_settings.get('made_for_kids', False))
        
        # Get tags: per-video custom > template
        if 'tags' in custom_settings:
            tags_str = custom_settings['tags']
        else:
            tags_str = replace_template_placeholders(
                youtube_settings.get('tags_template', ''),
                filename_no_ext,
                global_settings.get('wordbank', [])
            )
        
        # Parse tags (comma-separated, strip whitespace, filter empty)
        tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()] if tags_str else []
        
        snippet_body = {
            'title': title,
            'description': description,
            'categoryId': '22'
        }
        
        # Only add tags if there are any
        if tags:
            snippet_body['tags'] = tags
        
        youtube_logger.info(f"Preparing upload request - Title: {title[:50]}..., Visibility: {visibility}")
        # ROOT CAUSE FIX: Resolve path to absolute to ensure file is found
        video_path = Path(video.path).resolve()
        youtube_logger.debug(f"Video path: {video_path}")
        
        # Verify file exists before attempting upload
        if not video_path.exists():
            error_msg = f"Video file not found: {video_path}"
            youtube_logger.error(
                f"❌ YouTube upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Path: {video_path}",
                extra={
                    "context": {
                        "user_id": user_id,
                        "video_id": video_id,
                        "video_filename": video.filename,
                        "video_path": str(video_path),
                        "platform": "youtube",
                        "error_type": "FileNotFound",
                    }
                }
            )
            record_platform_error(video_id, user_id, "youtube", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        request = youtube.videos().insert(
            part='snippet,status',
            body={
                'snippet': snippet_body,
                'status': {
                    'privacyStatus': visibility,
                    'selfDeclaredMadeForKids': made_for_kids
                }
            },
            media_body=MediaFileUpload(str(video_path), resumable=True)
        )
        
        youtube_logger.info("Starting resumable upload...")
        response = None
        chunk_count = 0
        last_published_progress = -1
        while response is None:
            # Check for cancellation during upload
            if _cancellation_flags.get(video_id, False):
                youtube_logger.info(f"YouTube upload cancelled for video {video_id} during upload")
                raise Exception("Upload cancelled by user")
            
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                set_upload_progress(user_id, video_id, progress)
                # Publish websocket event for real-time progress updates (1% increments or at completion)
                from app.services.video.helpers import should_publish_progress
                if should_publish_progress(progress, last_published_progress):
                    await publish_upload_progress(user_id, video_id, "youtube", progress)
                    last_published_progress = progress
                chunk_count += 1
                if chunk_count % 10 == 0 or progress == 100:  # Log every 10 chunks or at completion
                    youtube_logger.info(f"Upload progress: {progress}%")
        
        # Update video in database with success
        custom_settings = custom_settings.copy() if custom_settings else {}
        custom_settings['youtube_id'] = response['id']
        update_video(video_id, user_id, db=db, status="uploaded", custom_settings=custom_settings)
        set_upload_progress(user_id, video_id, 100)
        # Publish final progress update
        await publish_upload_progress(user_id, video_id, "youtube", 100)
        youtube_logger.info(f"Successfully uploaded {video.filename}, YouTube ID: {response['id']}")
        
        # Increment successful uploads counter
        successful_uploads_counter.inc()
        
        # Deduct tokens after successful upload (only if not already deducted)
        if video.tokens_consumed == 0:
            # Use stored tokens_required with fallback for backward compatibility
            tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
            if tokens_required > 0:
                await deduct_tokens(
                    user_id=user_id,
                    tokens=tokens_required,
                    transaction_type='upload',
                    video_id=video.id,
                    metadata={
                        'filename': video.filename,
                        'platform': 'youtube',
                        'youtube_id': response['id'],
                        'file_size_bytes': video.file_size_bytes,
                        'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                    },
                    db=db
                )
            # Update tokens_consumed in video record to prevent double-charging
            update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            youtube_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            youtube_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
    
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Gather comprehensive context for troubleshooting
        context = {
            "user_id": user_id,
            "video_id": video_id,
            "video_filename": video.filename,
            "file_size_bytes": video.file_size_bytes,
            "file_size_mb": round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else None,
            "tokens_consumed": video.tokens_consumed,
            "platform": "youtube",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
        # Add video path if available
        try:
            video_path = Path(video.path).resolve() if video.path else None
            if video_path:
                context["video_path"] = str(video_path)
                context["file_exists"] = video_path.exists()
                if video_path.exists():
                    context["actual_file_size_bytes"] = video_path.stat().st_size
        except Exception:
            pass
        
        # Log comprehensive error details
        youtube_logger.error(
            f"❌ YouTube upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        # Update video status with detailed error
        error_message = f"Upload failed: {error_type}: {error_msg}"
        record_platform_error(video_id, user_id, "youtube", error_message, db=db)
        delete_upload_progress(user_id, video_id)
        
        # Increment failed uploads metric
        failed_uploads_gauge.inc()

