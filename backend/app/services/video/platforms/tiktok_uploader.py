"""TikTok upload service logic"""

import asyncio
import logging
from pathlib import Path
from typing import Optional
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings, TIKTOK_INIT_UPLOAD_URL
from app.db.helpers import (
    get_user_videos, get_user_settings, get_oauth_token,
    check_token_expiration, update_video
)
from app.db.redis import set_upload_progress, delete_upload_progress, set_platform_upload_progress
from app.services.event_service import publish_upload_progress
from app.services.token_service import check_tokens_available, get_token_balance, deduct_tokens, calculate_tokens_from_bytes
from app.utils.encryption import decrypt
from app.utils.templates import get_video_title
from app.utils.video_tokens import generate_video_access_token

from app.services.video.platforms.tiktok_api import (
    check_tiktok_rate_limit,
    refresh_tiktok_token,
    get_tiktok_creator_info,
    map_privacy_level_to_tiktok
)

# Import helpers from video/helpers module
from app.services.video.helpers import (
    record_platform_error
)

tiktok_logger = logging.getLogger("tiktok")


async def upload_video_to_tiktok(user_id: int, video_id: int, db: Session = None, session_id: str = None):
    """Upload a single video to TikTok - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    # Import cancellation flag to check for cancellation during upload
    from app.services.video.orchestrator import _cancellation_flags
    
    # Check for cancellation before starting
    if _cancellation_flags.get(video_id, False):
        tiktok_logger.info(f"TikTok upload cancelled for video {video_id} before starting")
        raise Exception("Upload cancelled by user")
    
    # Get video from database
    videos = get_user_videos(user_id, db=db)
    video = next((v for v in videos if v.id == video_id), None)
    if not video:
        tiktok_logger.error(f"Video {video_id} not found for user {user_id}")
        return
    
    # Check token balance before uploading (only if tokens not already consumed)
    if video.tokens_consumed == 0:
        # Use stored tokens_required with fallback for backward compatibility
        tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
        if tokens_required > 0 and not check_tokens_available(user_id, tokens_required, db):
            balance_info = get_token_balance(user_id, db)
            tokens_remaining = balance_info.get('tokens_remaining', 0) if balance_info else 0
            error_msg = f"Insufficient tokens: Need {tokens_required} tokens but only have {tokens_remaining} remaining"
            
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Insufficient tokens - User {user_id}, Video {video_id} ({video.filename}): "
                f"Required {tokens_required} tokens, but only {tokens_remaining} remaining. "
                f"File size: {video.file_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "file_size_bytes": video.file_size_bytes,
                    "tokens_required": tokens_required,
                    "tokens_remaining": tokens_remaining,
                    "platform": "tiktok",
                    "error_type": "InsufficientTokens",
                }
            )
            
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            return
    
    # Get TikTok credentials from database
    tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
    if not tiktok_token:
            error_msg = "No credentials"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - No credentials - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "MissingCredentials",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            return
    
    # Decrypt access token
    access_token = decrypt(tiktok_token.access_token)
    if not access_token or not access_token.strip():
        error_msg = "Access token is missing or invalid. Please reconnect your TikTok account."
        tiktok_logger.error(
            f"❌ TikTok token is empty or invalid - User {user_id}, Video {video_id} ({video.filename})",
            extra={
                "user_id": user_id,
                "video_id": video_id,
                "video_filename": video.filename,
                "platform": "tiktok",
                "error_type": "EmptyToken",
            }
        )
        record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
        failed_uploads_gauge.inc()
        return
    
    # Check if token is expired and refresh if needed
    token_expiry = check_token_expiration(tiktok_token)
    if token_expiry.get("expired", False) or token_expiry.get("expires_soon", False):
        refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
        if refresh_token_decrypted:
            try:
                tiktok_logger.info(f"TikTok token expired/expiring for user {user_id}, refreshing...")
                access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                if not tiktok_token:
                    raise Exception("Failed to retrieve token after refresh")
                tiktok_logger.info(f"Successfully refreshed TikTok token for user {user_id}")
            except Exception as refresh_error:
                error_msg = f"Failed to refresh access token. Please reconnect your TikTok account. Error: {str(refresh_error)}"
                tiktok_logger.error(
                    f"❌ TikTok token refresh FAILED - User {user_id}, Video {video_id} ({video.filename}): {refresh_error}",
                    extra={
                        "user_id": user_id,
                        "video_id": video_id,
                        "video_filename": video.filename,
                        "platform": "tiktok",
                        "error_type": "TokenRefreshFailed",
                    },
                    exc_info=True
                )
                record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                return
        else:
            error_msg = "Access token expired and no refresh token available. Please reconnect your TikTok account."
            tiktok_logger.error(
                f"❌ TikTok token expired with no refresh token - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "TokenExpiredNoRefresh",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            return
    
    # Get settings from database
    tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        last_published_progress = -1
        from app.services.video.helpers import should_publish_progress
        
        # Log upload initiation with source type
        tiktok_logger.info(
            f"Starting TikTok upload - User {user_id}, Video {video_id} ({video.filename}), "
            f"Source: PULL_FROM_URL, File size: {video.file_size_bytes / (1024*1024):.2f} MB"
        )
        
        set_upload_progress(user_id, video_id, 0)
        set_platform_upload_progress(user_id, video_id, "tiktok", 0)
        await publish_upload_progress(user_id, video_id, "tiktok", 0)
        last_published_progress = 0
        
        # Check rate limit (use user_id if session_id not provided)
        check_tiktok_rate_limit(session_id=session_id, user_id=user_id)
        
        # Get creator info (with automatic retry on token error)
        try:
            creator_info = get_tiktok_creator_info(access_token)
        except Exception as creator_info_error:
            error_msg = str(creator_info_error)
            # If token is invalid, try refreshing once more
            if "access_token_invalid" in error_msg.lower() or "invalid" in error_msg.lower():
                tiktok_logger.warning(f"Creator info query failed with token error, attempting refresh: {error_msg}")
                tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                if not tiktok_token:
                    error_msg = f"TikTok: No token found in database. Please reconnect your TikTok account."
                    tiktok_logger.error(
                        f"❌ TikTok token not found - User {user_id}, Video {video_id} ({video.filename})",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "platform": "tiktok",
                            "error_type": "TokenNotFound",
                        }
                    )
                    record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                    return
                refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                if refresh_token_decrypted:
                    try:
                        access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                        tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                        if not tiktok_token:
                            raise Exception("Failed to retrieve token after refresh")
                        creator_info = get_tiktok_creator_info(access_token)
                        tiktok_logger.info(f"Successfully refreshed token and retried creator info query for user {user_id}")
                    except Exception as retry_error:
                        error_msg = f"TikTok: Failed to refresh access token after invalid token error. Please reconnect your TikTok account. Error: {str(retry_error)}"
                        tiktok_logger.error(
                            f"❌ TikTok token refresh FAILED after invalid token - User {user_id}, Video {video_id} ({video.filename}): {retry_error}",
                            extra={
                                "user_id": user_id,
                                "video_id": video_id,
                                "video_filename": video.filename,
                                "platform": "tiktok",
                                "error_type": "TokenRefreshFailedAfterInvalid",
                            },
                            exc_info=True
                        )
                        record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                        return
                else:
                    error_msg = f"Access token is invalid and no refresh token available. Please reconnect your TikTok account. Error: {error_msg}"
                    tiktok_logger.error(
                        f"❌ TikTok invalid token with no refresh token - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "platform": "tiktok",
                            "error_type": "InvalidTokenNoRefresh",
                        }
                    )
                    record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                    return
            else:
                # Other error - re-raise
                raise
        
        # Check if creator can make more posts (TikTok UX requirement 1b)
        can_not_make_more_posts = creator_info.get("can_not_make_more_posts", False)
        if can_not_make_more_posts:
            error_msg = "You cannot make more posts at this moment. Please try again later."
            tiktok_logger.warning(
                f"❌ TikTok upload BLOCKED - Creator cannot make more posts - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PostingLimitReached",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            raise Exception(error_msg)
        
        
        # Prepare metadata
        db.refresh(video)
        filename_no_ext = video.filename.rsplit('.', 1)[0] if '.' in video.filename else video.filename
        custom_settings = video.custom_settings or {}
        
        # Get title using consistent priority logic
        title = get_video_title(
            video=video,
            custom_settings=custom_settings,
            destination_settings=tiktok_settings,
            global_settings=global_settings,
            filename_no_ext=filename_no_ext,
            template_key='title_template'
        )
        
        title = (title or filename_no_ext)[:2200]  # TikTok limit
        
        # Get settings: per-video custom > destination settings
        privacy_level = custom_settings.get('privacy_level') or tiktok_settings.get('privacy_level')
        if not privacy_level:
            error_msg = "Privacy level is required. Please set a privacy level in the video settings or TikTok destination settings."
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Privacy level not set - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PrivacyLevelRequired",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            return
        
        try:
            tiktok_privacy = map_privacy_level_to_tiktok(privacy_level, creator_info)
            tiktok_logger.debug(f"Using privacy_level: {tiktok_privacy} (from input: {privacy_level})")
        except Exception as privacy_error:
            error_msg = f"Privacy level error: {str(privacy_error)}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Privacy level error - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "PrivacyLevelError",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            return
        
        # Check creator_info for disabled interactions
        allow_comments_setting = custom_settings.get('allow_comments', tiktok_settings.get('allow_comments', False))
        allow_duet_setting = custom_settings.get('allow_duet', tiktok_settings.get('allow_duet', False))
        allow_stitch_setting = custom_settings.get('allow_stitch', tiktok_settings.get('allow_stitch', False))
        
        comment_disabled = creator_info.get("disable_comment", False) or creator_info.get("comment_disabled", False)
        duet_disabled = creator_info.get("disable_duet", False) or creator_info.get("duet_disabled", False)
        stitch_disabled = creator_info.get("disable_stitch", False) or creator_info.get("stitch_disabled", False)
        
        allow_comments = allow_comments_setting and not comment_disabled
        allow_duet = allow_duet_setting and not duet_disabled
        allow_stitch = allow_stitch_setting and not stitch_disabled
        
        # Get commercial content disclosure settings
        commercial_content_disclosure = custom_settings.get('commercial_content_disclosure', tiktok_settings.get('commercial_content_disclosure', False))
        commercial_content_your_brand = custom_settings.get('commercial_content_your_brand', tiktok_settings.get('commercial_content_your_brand', False))
        commercial_content_branded = custom_settings.get('commercial_content_branded', tiktok_settings.get('commercial_content_branded', False))
        
        brand_organic_toggle = commercial_content_disclosure and commercial_content_your_brand
        brand_content_toggle = commercial_content_disclosure and commercial_content_branded
        
        video_size_mb = video.file_size_bytes / (1024*1024) if video.file_size_bytes else 0
        tiktok_logger.info(f"Uploading {video.filename} ({video_size_mb:.2f} MB)")
        progress = 5
        set_upload_progress(user_id, video_id, progress)
        set_platform_upload_progress(user_id, video_id, "tiktok", progress)
        if should_publish_progress(progress, last_published_progress):
            await publish_upload_progress(user_id, video_id, "tiktok", progress)
            last_published_progress = progress
        
        # Use PULL_FROM_URL method only (R2 presigned URLs)
        # Check if R2 object exists
        from app.services.storage.r2_service import get_r2_service, _is_old_local_path
        r2_service = get_r2_service()
        
        if not video.path:
            error_msg = "Video has no R2 object key"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - No R2 object key - User {user_id}, Video {video_id} ({video.filename})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "error_type": "FileNotFound",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        if not r2_service.object_exists(video.path):
            # Check if this is an old local path
            if _is_old_local_path(video.path):
                error_msg = f"Video has old local file path (pre-R2 migration): {video.path}. Please re-upload the video."
            else:
                error_msg = f"R2 object not found: {video.path}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - R2 object not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"R2 object key: {video.path}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "r2_object_key": video.path,
                    "platform": "tiktok",
                    "error_type": "FileNotFound",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            raise FileNotFoundError(error_msg)
        
        # Get video URL using DRY helper (validates custom domain URLs)
        from app.services.storage.r2_service import get_video_download_url
        try:
            video_url = get_video_download_url(video.path, r2_service)
            tiktok_logger.info(
                f"TikTok upload method: PULL_FROM_URL - User {user_id}, Video {video_id} ({video.filename}), "
                f"URL: {video_url}, R2 path: {video.path}"
            )
        except ValueError as url_error:
            error_msg = f"Failed to generate video URL: {str(url_error)}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - URL generation error - User {user_id}, Video {video_id} ({video.filename}): {error_msg}",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "r2_object_key": video.path,
                    "platform": "tiktok",
                    "error_type": "URLGenerationFailed",
                }
            )
            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
            raise ValueError(error_msg)
        
        # Step 1: Initialize upload with PULL_FROM_URL
        source_info = {
            "source": "PULL_FROM_URL",
            "video_url": video_url
        }
        
        init_response = httpx.post(
            TIKTOK_INIT_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json; charset=UTF-8"
            },
            json={
                "post_info": {
                    "title": title,
                    "privacy_level": tiktok_privacy,
                    "disable_duet": not allow_duet,
                    "disable_comment": not allow_comments,
                    "disable_stitch": not allow_stitch,
                    "brand_organic_toggle": brand_organic_toggle,
                    "brand_content_toggle": brand_content_toggle
                },
                "source_info": source_info
            },
            timeout=30.0
        )
        
        # Check if token error and retry with refresh
        if init_response.status_code != 200:
            try:
                response_data = init_response.json()
                error = response_data.get("error", {})
                error_code = error.get('code', '')
                error_message = error.get('message', '')
                
                # If token is invalid, try refreshing once more
                if "access_token_invalid" in error_code.lower() or "access_token_invalid" in error_message.lower() or "invalid" in error_message.lower():
                    tiktok_logger.warning(f"Init upload failed with token error, attempting refresh: {error_code} - {error_message}")
                    tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                    if not tiktok_token:
                        error_msg = f"TikTok: No token found in database. Please reconnect your TikTok account."
                        tiktok_logger.error(
                            f"❌ TikTok token not found - User {user_id}, Video {video_id} ({video.filename})",
                            extra={
                                "user_id": user_id,
                                "video_id": video_id,
                                "video_filename": video.filename,
                                "platform": "tiktok",
                                "error_type": "TokenNotFound",
                            }
                        )
                        record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                        return
                    refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                    if refresh_token_decrypted:
                        try:
                            access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                            tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                            if not tiktok_token:
                                raise Exception("Failed to retrieve token after refresh")
                            # Retry init upload with new token
                            retry_source_info = {
                                "source": "PULL_FROM_URL",
                                "video_url": video_url
                            }
                            
                            init_response = httpx.post(
                                TIKTOK_INIT_UPLOAD_URL,
                                headers={
                                    "Authorization": f"Bearer {access_token.strip()}",
                                    "Content-Type": "application/json; charset=UTF-8"
                                },
                                json={
                                    "post_info": {
                                        "title": title,
                                        "privacy_level": tiktok_privacy,
                                        "disable_duet": not allow_duet,
                                        "disable_comment": not allow_comments,
                                        "disable_stitch": not allow_stitch,
                                        "brand_organic_toggle": brand_organic_toggle,
                                        "brand_content_toggle": brand_content_toggle
                                    },
                                    "source_info": retry_source_info
                                },
                                timeout=30.0
                            )
                            tiktok_logger.info(f"Successfully refreshed token and retried init upload for user {user_id}")
                        except Exception as retry_error:
                            error_msg = f"Failed to refresh access token during upload. Please reconnect your TikTok account. Error: {str(retry_error)}"
                            tiktok_logger.error(
                                f"❌ TikTok token refresh FAILED during upload - User {user_id}, Video {video_id} ({video.filename}): {retry_error}",
                                extra={
                                    "user_id": user_id,
                                    "video_id": video_id,
                                    "video_filename": video.filename,
                                    "platform": "tiktok",
                                    "error_type": "TokenRefreshFailedDuringUpload",
                                },
                                exc_info=True
                            )
                            record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                            return
            except:
                pass
        
        if init_response.status_code != 200:
            import json as json_module
            error_context = {
                "user_id": user_id,
                "video_id": video_id,
                "video_filename": video.filename,
                "platform": "tiktok",
                "http_status": init_response.status_code,
                "stage": "init_upload",
                "source": "PULL_FROM_URL",
            }
            
            # Include video URL in error context for debugging (especially for custom domain issues)
            if 'video_url' in locals():
                error_context["video_url"] = video_url
                error_context["r2_public_domain"] = settings.R2_PUBLIC_DOMAIN
            
            try:
                response_data = init_response.json()
                error_context["response_data"] = json_module.dumps(response_data)
                error = response_data.get("error", {})
                error_code = error.get('code', '')
                error_message = error.get('message', 'Unknown error')
                log_id = error.get('log_id', '')
                error_context["tiktok_error_code"] = error_code
                error_context["tiktok_error_message"] = error_message
                error_context["tiktok_log_id"] = log_id
                
                # Map TikTok API error codes to user-friendly messages per API docs
                if error_code == "unaudited_client_can_only_post_to_private_accounts":
                    user_friendly_error = (
                        "TikTok app is not audited. Unaudited apps can only post to private accounts. "
                        "Please set your TikTok privacy level to 'private' in settings, or wait for app audit completion."
                    )
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Unaudited client limitation - User {user_id}, Video {video_id} ({video.filename}): "
                        f"TikTok error_code: {error_code}, message: {error_message}, log_id: {log_id}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                elif error_code == "url_ownership_unverified":
                    user_friendly_error = (
                        "URL ownership not verified. The video URL domain must be verified in TikTok Developer Portal. "
                        "Please verify your custom domain or URL prefix in TikTok Developer Portal."
                    )
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - URL ownership unverified - User {user_id}, Video {video_id} ({video.filename}): "
                        f"TikTok error_code: {error_code}, message: {error_message}, log_id: {log_id}, video_url: {video_url}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                elif error_code == "spam_risk_too_many_posts":
                    user_friendly_error = "Daily post limit reached. Please try again tomorrow."
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Rate limit - User {user_id}, Video {video_id} ({video.filename}): "
                        f"TikTok error_code: {error_code}, message: {error_message}, log_id: {log_id}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                elif error_code == "privacy_level_option_mismatch":
                    user_friendly_error = (
                        "Privacy level mismatch. The selected privacy level is not available for this account. "
                        "Please check your TikTok account settings."
                    )
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Privacy level error - User {user_id}, Video {video_id} ({video.filename}): "
                        f"TikTok error_code: {error_code}, message: {error_message}, log_id: {log_id}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                else:
                    # Generic error handling with TikTok error codes
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Init error - User {user_id}, Video {video_id} ({video.filename}): "
                        f"HTTP {init_response.status_code}, TikTok error_code: {error_code}, message: {error_message}, log_id: {log_id}",
                        extra=error_context
                    )
                    raise Exception(f"TikTok API error ({error_code}): {error_message}")
            except Exception as parse_error:
                # If we can't parse the response, log the raw response
                error_context["raw_response"] = init_response.text
                error_context["parse_error"] = str(parse_error)
                tiktok_logger.error(
                    f"❌ TikTok upload FAILED - Init error (parse failed) - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {init_response.status_code}, Could not parse response: {str(parse_error)}",
                    extra=error_context
                )
                tiktok_logger.error(f"Raw response text: {init_response.text}")
                raise Exception(f"Init failed: {init_response.status_code} - {init_response.text}")
        
        init_data = init_response.json()
        publish_id = init_data["data"]["publish_id"]
        
        # Log publish_id immediately after receiving it from TikTok API
        tiktok_logger.info(
            f"TikTok upload initialized - User {user_id}, Video {video_id} ({video.filename}), "
            f"publish_id: {publish_id}, Source: PULL_FROM_URL"
        )
        
        # ROOT CAUSE FIX: Save publish_id to database immediately so status_checker can track it
        # even if this upload task times out. This ensures long-running uploads aren't lost.
        custom_settings = video.custom_settings or {}
        custom_settings = custom_settings.copy()
        custom_settings['tiktok_publish_id'] = publish_id
        update_video(video_id, user_id, db=db, custom_settings=custom_settings, status="uploading")
        
        progress = 10
        set_upload_progress(user_id, video_id, progress)
        set_platform_upload_progress(user_id, video_id, "tiktok", progress)
        if should_publish_progress(progress, last_published_progress):
            await publish_upload_progress(user_id, video_id, "tiktok", progress)
            last_published_progress = progress
        
        # PULL_FROM_URL method: TikTok will download the file automatically
        # Check for cancellation before marking as success
        if _cancellation_flags.get(video_id, False):
            tiktok_logger.info(f"TikTok upload cancelled for video {video_id} before PULL_FROM_URL completion")
            raise Exception("Upload cancelled by user")
        
        tiktok_logger.info(
            f"TikTok using PULL_FROM_URL (URL) method - TikTok will download the file automatically - "
            f"User {user_id}, Video {video_id} ({video.filename})"
        )
        
        # Start polling TikTok status for PULL_FROM_URL progress tracking
        # Initial status will be PROCESSING_DOWNLOAD (10-50% range)
        from app.services.video.platforms.tiktok_api import fetch_tiktok_publish_status
        poll_count = 0
        max_polls = 120  # Poll for up to 10 minutes (5 second intervals)
        estimated_download_polls = 60  # Estimate download takes ~5 minutes
        estimated_upload_polls = 60  # Estimate processing takes ~5 minutes
        last_logged_status = None  # Track last logged status for transition logging
        
        while poll_count < max_polls:
            # Check for cancellation
            if _cancellation_flags.get(video_id, False):
                tiktok_logger.info(f"TikTok upload cancelled for video {video_id} during PULL_FROM_URL polling")
                raise Exception("Upload cancelled by user")
            
            # Check if video still exists in database (user may have deleted it)
            from app.models.video import Video
            video_exists = db.query(Video).filter(Video.id == video_id).first()
            if not video_exists:
                tiktok_logger.info(f"Video {video_id} was deleted during TikTok upload polling, stopping poll")
                raise Exception("Video was deleted during upload")
            
            await asyncio.sleep(5)  # Poll every 5 seconds
            poll_count += 1
            
            status_data = fetch_tiktok_publish_status(user_id, publish_id, db=db)
            if not status_data:
                # Status not available yet, continue polling
                continue
            
            status = status_data.get("status")
            
            # Log status transitions for better observability
            if status != last_logged_status:
                tiktok_logger.info(
                    f"TikTok upload status transition - User {user_id}, Video {video_id} ({video.filename}), "
                    f"publish_id: {publish_id}, Status: {status} (was: {last_logged_status}), Poll: {poll_count}/{max_polls}"
                )
                last_logged_status = status
            
            # Map status to progress percentages
            if status == "PROCESSING_DOWNLOAD":
                # TikTok is downloading from our server: 10-50% range
                progress = 10 + int(min(poll_count / estimated_download_polls, 1.0) * 40)
                set_upload_progress(user_id, video_id, progress)
                set_platform_upload_progress(user_id, video_id, "tiktok", progress)
                if should_publish_progress(progress, last_published_progress):
                    await publish_upload_progress(user_id, video_id, "tiktok", progress)
                    last_published_progress = progress
            elif status == "PROCESSING_UPLOAD":
                # TikTok is processing the video: 50-90% range
                download_polls = min(poll_count, estimated_download_polls)
                upload_polls = poll_count - download_polls
                progress = 50 + int(min(upload_polls / estimated_upload_polls, 1.0) * 40)
                set_upload_progress(user_id, video_id, progress)
                set_platform_upload_progress(user_id, video_id, "tiktok", progress)
                if should_publish_progress(progress, last_published_progress):
                    await publish_upload_progress(user_id, video_id, "tiktok", progress)
                    last_published_progress = progress
            elif status == "PUBLISH_COMPLETE":
                # Upload complete: 100%
                video_id_from_status = status_data.get("video_id")
                progress = 100
                set_upload_progress(user_id, video_id, progress)
                set_platform_upload_progress(user_id, video_id, "tiktok", progress)
                await publish_upload_progress(user_id, video_id, "tiktok", progress)
                last_published_progress = progress
                tiktok_logger.info(
                    f"TikTok upload completed - PUBLISH_COMPLETE - User {user_id}, Video {video_id} ({video.filename}), "
                    f"publish_id: {publish_id}, tiktok_id: {video_id_from_status}"
                )
                break
            elif status == "PUBLISHED":
                # 404 returned PUBLISHED status - video was published, complete upload
                # video_id may be None, but status_checker can fetch it later if needed
                video_id_from_status = status_data.get("video_id")
                progress = 100
                set_upload_progress(user_id, video_id, progress)
                set_platform_upload_progress(user_id, video_id, "tiktok", progress)
                await publish_upload_progress(user_id, video_id, "tiktok", progress)
                last_published_progress = progress
                tiktok_logger.info(
                    f"TikTok upload completed - PUBLISHED (via 404) - User {user_id}, Video {video_id} ({video.filename}), "
                    f"publish_id: {publish_id}, tiktok_id: {video_id_from_status}"
                )
                break
            elif status == "FAILED":
                # Upload failed - log fail_reason from TikTok API
                fail_reason = status_data.get("fail_reason", "Unknown error")
                error_code = status_data.get("error_code", "")
                tiktok_logger.error(
                    f"TikTok upload FAILED - User {user_id}, Video {video_id} ({video.filename}), "
                    f"publish_id: {publish_id}, fail_reason: {fail_reason}, error_code: {error_code}",
                    extra={
                        "user_id": user_id,
                        "video_id": video_id,
                        "video_filename": video.filename,
                        "publish_id": publish_id,
                        "fail_reason": fail_reason,
                        "error_code": error_code,
                        "platform": "tiktok",
                        "error_type": "TikTokAPIFailure",
                    }
                )
                raise Exception(f"TikTok upload failed: {fail_reason}")
            
            # If we've been polling for a while and still processing, continue
            if status in ["PROCESSING_DOWNLOAD", "PROCESSING_UPLOAD"]:
                continue
        
        # If we exit the loop without PUBLISH_COMPLETE, it means we timed out
        if poll_count >= max_polls:
            # ROOT CAUSE FIX: Don't fail on timeout - hand off to status_checker
            # publish_id is already saved, so status_checker can continue monitoring
            # TikTok uploads can take longer than 10 minutes, especially for large files
            tiktok_logger.info(
                f"TikTok upload polling timeout after {max_polls * 5} seconds - "
                f"handing off to status_checker for User {user_id}, Video {video_id} ({video.filename}), "
                f"publish_id: {publish_id}. Status checker will continue monitoring."
            )
            # Ensure video status is "uploading" so status_checker picks it up
            update_video(video_id, user_id, db=db, status="uploading")
            # Return successfully - status_checker will complete the monitoring
            return
        
        # Check for cancellation before marking as success
        if _cancellation_flags.get(video_id, False):
            tiktok_logger.info(f"TikTok upload cancelled for video {video_id} before finalizing")
            raise Exception("Upload cancelled by user")
        
        # Success - update video in database
        custom_settings = custom_settings.copy() if custom_settings else {}
        custom_settings['tiktok_publish_id'] = publish_id
        update_video(video_id, user_id, db=db, status="uploaded", custom_settings=custom_settings)
        progress = 100
        set_upload_progress(user_id, video_id, progress)
        set_platform_upload_progress(user_id, video_id, "tiktok", progress)
        if should_publish_progress(progress, last_published_progress):
            await publish_upload_progress(user_id, video_id, "tiktok", progress)
            last_published_progress = progress
        # Log successful upload completion with all relevant details
        tiktok_logger.info(
            f"TikTok upload successful - User {user_id}, Video {video_id} ({video.filename}), "
            f"publish_id: {publish_id}, Source: PULL_FROM_URL, Status: uploaded"
        )
        
        # Increment successful uploads counter only on confirmed success
        # (status is already "uploaded" at this point, indicating confirmed success)
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
                        'platform': 'tiktok',
                        'tiktok_publish_id': publish_id,
                        'file_size_bytes': video.file_size_bytes,
                        'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2)
                    },
                    db=db
                )
            # Update tokens_consumed in video record to prevent double-charging
            update_video(video_id, user_id, db=db, tokens_consumed=tokens_required)
            tiktok_logger.info(f"Deducted {tokens_required} tokens for user {user_id} (first platform upload)")
        else:
            tiktok_logger.info(f"Tokens already deducted for this video (tokens_consumed={video.tokens_consumed}), skipping")
    
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
            "platform": "tiktok",
            "error_type": error_type,
            "error_message": error_msg,
        }
        
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
            if 'publish_id' in locals():
                context["tiktok_publish_id"] = publish_id
            if 'upload_url' in locals():
                context["tiktok_upload_url"] = upload_url
        except Exception:
            pass
        
        tiktok_logger.error(
            f"❌ TikTok upload FAILED - User {user_id}, Video {video_id} ({video.filename}): "
            f"{error_type}: {error_msg}",
            extra=context,
            exc_info=True
        )
        
        error_message = f"Upload failed: {error_type}: {error_msg}"
        record_platform_error(video_id, user_id, "tiktok", error_message, db=db)
        delete_upload_progress(user_id, video_id)
        
        failed_uploads_gauge.inc()

