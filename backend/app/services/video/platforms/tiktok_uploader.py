"""TikTok upload service logic"""

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
from app.db.redis import set_upload_progress, delete_upload_progress
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
    record_platform_error,
    get_video_duration
)

tiktok_logger = logging.getLogger("tiktok")


def upload_video_to_tiktok(user_id: int, video_id: int, db: Session = None, session_id: str = None):
    """Upload a single video to TikTok - queries database directly"""
    # Import metrics from centralized location
    from app.core.metrics import successful_uploads_counter, failed_uploads_gauge
    
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
            failed_uploads_gauge.inc()
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
            failed_uploads_gauge.inc()
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
                failed_uploads_gauge.inc()
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
            failed_uploads_gauge.inc()
            return
    
    # Get settings from database
    tiktok_settings = get_user_settings(user_id, "tiktok", db=db)
    global_settings = get_user_settings(user_id, "global", db=db)
    
    try:
        update_video(video_id, user_id, db=db, status="uploading")
        set_upload_progress(user_id, video_id, 0)
        
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
                    failed_uploads_gauge.inc()
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
                        failed_uploads_gauge.inc()
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
                    failed_uploads_gauge.inc()
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
            failed_uploads_gauge.inc()
            raise Exception(error_msg)
        
        # Get video file
        stored_path = Path(video.path).resolve()
        fallback_path = (settings.UPLOAD_DIR / video.filename).resolve()
        
        if stored_path.exists():
            video_path = stored_path
        elif fallback_path.exists():
            video_path = fallback_path
            tiktok_logger.info(
                f"Using fallback path for TikTok upload - User {user_id}, Video {video_id} ({video.filename}): "
                f"Stored path not found: {stored_path}, using fallback: {fallback_path}"
            )
        else:
            error_msg = f"Video file not found at {stored_path} or {fallback_path}"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - File not found - User {user_id}, Video {video_id} ({video.filename}): "
                f"Stored path: {stored_path} (exists: {stored_path.exists()}), "
                f"Fallback path: {fallback_path} (exists: {fallback_path.exists()})",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "stored_path": str(stored_path),
                    "fallback_path": str(fallback_path),
                    "platform": "tiktok",
                    "error_type": "FileNotFound",
                }
            )
            raise FileNotFoundError(error_msg)
        
        video_size = video_path.stat().st_size
        if video_size == 0:
            error_msg = "Video file is empty"
            tiktok_logger.error(
                f"❌ TikTok upload FAILED - Empty file - User {user_id}, Video {video_id} ({video.filename}): "
                f"File size: {video_size} bytes",
                extra={
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "video_path": str(video_path),
                    "file_size": video_size,
                    "platform": "tiktok",
                    "error_type": "EmptyFile",
                }
            )
            raise Exception(error_msg)
        
        # Validate video duration against max_video_post_duration_sec (TikTok UX requirement 1c)
        max_video_post_duration_sec = creator_info.get("max_video_post_duration_sec")
        if max_video_post_duration_sec:
            try:
                video_duration_seconds = get_video_duration(video_path)
                if video_duration_seconds > max_video_post_duration_sec:
                    error_msg = (
                        f"TikTok: Video duration ({video_duration_seconds:.1f}s) exceeds maximum allowed duration "
                        f"({max_video_post_duration_sec}s). Please use a shorter video."
                    )
                    tiktok_logger.warning(
                        f"❌ TikTok upload BLOCKED - Video duration too long - User {user_id}, Video {video_id} ({video.filename}): "
                        f"Duration: {video_duration_seconds:.1f}s, Max: {max_video_post_duration_sec}s",
                        extra={
                            "user_id": user_id,
                            "video_id": video_id,
                            "video_filename": video.filename,
                            "video_duration_seconds": video_duration_seconds,
                            "max_video_post_duration_sec": max_video_post_duration_sec,
                            "platform": "tiktok",
                            "error_type": "VideoDurationExceeded",
                        }
                    )
                    record_platform_error(video_id, user_id, "tiktok", error_msg, db=db)
                    failed_uploads_gauge.inc()
                    raise Exception(error_msg)
                tiktok_logger.debug(f"Video duration validated: {video_duration_seconds:.1f}s <= {max_video_post_duration_sec}s")
            except Exception as duration_error:
                # If duration check fails (e.g., ffprobe not available), log warning but don't block upload
                if "exceeds maximum" in str(duration_error) or "exceeded" in str(duration_error).lower():
                    raise
                tiktok_logger.warning(
                    f"Could not validate video duration for user {user_id}, video {video_id}: {duration_error}. "
                    f"Upload will proceed, but duration validation is recommended."
                )
        
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
            failed_uploads_gauge.inc()
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
            failed_uploads_gauge.inc()
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
        
        tiktok_logger.info(f"Uploading {video.filename} ({video_size / (1024*1024):.2f} MB)")
        set_upload_progress(user_id, video_id, 5)
        
        # Determine upload method: prefer PULL_FROM_URL, fallback to FILE_UPLOAD
        use_pull_from_url = True
        video_url = None
        upload_method = None
        
        stored_path = Path(video.path).resolve()
        fallback_path = (settings.UPLOAD_DIR / video.filename).resolve()
        file_exists = stored_path.exists() or fallback_path.exists()
        
        if use_pull_from_url and file_exists:
            # Generate secure access token for video file (valid for 1 hour)
            video_access_token = generate_video_access_token(video_id, user_id, expires_in_hours=1)
            video_url = f"{settings.BACKEND_URL.rstrip('/')}/api/videos/{video_id}/file?token={video_access_token}"
            upload_method = "PULL_FROM_URL"
            actual_path = stored_path if stored_path.exists() else fallback_path
            tiktok_logger.info(
                f"TikTok upload method: PULL_FROM_URL (URL) - User {user_id}, Video {video_id} ({video.filename}), "
                f"file exists at: {actual_path}"
            )
        else:
            if use_pull_from_url and not file_exists:
                tiktok_logger.warning(
                    f"TikTok upload method: PULL_FROM_URL (URL) skipped - file not found, falling back to FILE_UPLOAD (file) - "
                    f"User {user_id}, Video {video_id} ({video.filename}). "
                    f"Stored path: {stored_path} (exists: {stored_path.exists()}), "
                    f"Fallback path: {fallback_path} (exists: {fallback_path.exists()})"
                )
            use_pull_from_url = False
            upload_method = "FILE_UPLOAD"
            tiktok_logger.info(
                f"TikTok upload method: FILE_UPLOAD (file) - User {user_id}, Video {video_id} ({video.filename})"
            )
        
        # Step 1: Initialize upload
        init_response = None
        try:
            if use_pull_from_url and video_url:
                source_info = {
                    "source": "PULL_FROM_URL",
                    "video_url": video_url
                }
            else:
                source_info = {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
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
        except Exception as init_error:
            # If PULL_FROM_URL fails, fallback to FILE_UPLOAD
            if use_pull_from_url and video_url:
                tiktok_logger.warning(
                    f"TikTok upload method changed: PULL_FROM_URL (URL) failed, falling back to FILE_UPLOAD (file) - "
                    f"User {user_id}, Video {video_id} ({video.filename}): {init_error}"
                )
                use_pull_from_url = False
                upload_method = "FILE_UPLOAD"
                source_info = {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1
                }
                try:
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
                except Exception as retry_error:
                    raise init_error
            else:
                raise
        
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
                        failed_uploads_gauge.inc()
                        return
                    refresh_token_decrypted = decrypt(tiktok_token.refresh_token) if tiktok_token.refresh_token else None
                    if refresh_token_decrypted:
                        try:
                            access_token = refresh_tiktok_token(user_id, refresh_token_decrypted, db)
                            tiktok_token = get_oauth_token(user_id, "tiktok", db=db)
                            if not tiktok_token:
                                raise Exception("Failed to retrieve token after refresh")
                            # Retry init upload with new token
                            if use_pull_from_url and video_url:
                                retry_source_info = {
                                    "source": "PULL_FROM_URL",
                                    "video_url": video_url
                                }
                            else:
                                retry_source_info = {
                                    "source": "FILE_UPLOAD",
                                    "video_size": video_size,
                                    "chunk_size": video_size,
                                    "total_chunk_count": 1
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
                            failed_uploads_gauge.inc()
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
            }
            
            try:
                response_data = init_response.json()
                error_context["response_data"] = json_module.dumps(response_data)
                error = response_data.get("error", {})
                error_code = error.get('code', '')
                error_message = error.get('message', 'Unknown error')
                error_context["error_code"] = error_code
                error_context["error_message"] = error_message
                
                if error_code == "unaudited_client_can_only_post_to_private_accounts":
                    user_friendly_error = (
                        "TikTok app is not audited. Unaudited apps can only post to private accounts. "
                        "Please set your TikTok privacy level to 'private' in settings, or wait for app audit completion."
                    )
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - Unaudited client limitation - User {user_id}, Video {video_id} ({video.filename}): "
                        f"{user_friendly_error}",
                        extra=error_context
                    )
                    raise Exception(user_friendly_error)
                
                tiktok_logger.error(
                    f"❌ TikTok upload FAILED - Init error - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {init_response.status_code} - {error_message}",
                    extra=error_context
                )
                tiktok_logger.error(f"Full response: {json_module.dumps(response_data, indent=2)}")
                raise Exception(f"Init failed: {error_message}")
            except Exception as parse_error:
                error_context["raw_response"] = init_response.text
                error_context["parse_error"] = str(parse_error)
                tiktok_logger.error(
                    f"❌ TikTok upload FAILED - Init error (parse failed) - User {user_id}, Video {video_id} ({video.filename}): "
                    f"HTTP {init_response.status_code}",
                    extra=error_context
                )
                tiktok_logger.error(f"Raw response text: {init_response.text}")
                raise Exception(f"Init failed: {init_response.status_code} - {init_response.text}")
        
        init_data = init_response.json()
        publish_id = init_data["data"]["publish_id"]
        
        tiktok_logger.info(f"Initialized, publish_id: {publish_id}")
        set_upload_progress(user_id, video_id, 10)
        
        # Step 2: Upload video file (only for FILE_UPLOAD method)
        if not use_pull_from_url:
            upload_url = init_data["data"].get("upload_url")
            if not upload_url:
                raise Exception("TikTok did not return upload_url for FILE_UPLOAD method")
            
            tiktok_logger.info(
                f"TikTok uploading video file using FILE_UPLOAD (file) method - "
                f"User {user_id}, Video {video_id} ({video.filename})"
            )
            
            file_ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
            content_type = {'mp4': 'video/mp4', 'mov': 'video/quicktime', 'webm': 'video/webm'}.get(file_ext, 'video/mp4')
            
            with open(video_path, 'rb') as f:
                upload_response = httpx.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                        "Content-Type": content_type
                    },
                    content=f.read(),
                    timeout=300.0
                )
            
            if upload_response.status_code not in [200, 201]:
                import json as json_module
                error_context = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "video_filename": video.filename,
                    "platform": "tiktok",
                    "http_status": upload_response.status_code,
                    "stage": "file_upload",
                    "publish_id": publish_id if 'publish_id' in locals() else None,
                    "video_size": video_size if 'video_size' in locals() else None,
                }
                
                try:
                    response_data = upload_response.json()
                    error_context["response_data"] = json_module.dumps(response_data)
                    error = response_data.get("error", {})
                    error_msg = error.get("message", upload_response.text)
                    error_context["error_code"] = error.get('code')
                    error_context["error_message"] = error_msg
                    
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - File upload error - User {user_id}, Video {video_id} ({video.filename}): "
                        f"HTTP {upload_response.status_code} - {error_msg}",
                        extra=error_context
                    )
                    tiktok_logger.error(f"Full upload response: {json_module.dumps(response_data, indent=2)}")
                except Exception as parse_error:
                    error_context["raw_response"] = upload_response.text
                    error_context["parse_error"] = str(parse_error)
                    error_msg = upload_response.text
                    tiktok_logger.error(
                        f"❌ TikTok upload FAILED - File upload error (parse failed) - User {user_id}, Video {video_id} ({video.filename}): "
                        f"HTTP {upload_response.status_code}",
                        extra=error_context
                    )
                    tiktok_logger.error(f"Raw upload response: {upload_response.text}")
                raise Exception(f"Upload failed: {upload_response.status_code} - {error_msg}")
            
            tiktok_logger.info("File upload completed")
        else:
            # PULL_FROM_URL method: TikTok will download the file automatically
            tiktok_logger.info(
                f"TikTok using PULL_FROM_URL (URL) method - TikTok will download the file automatically - "
                f"User {user_id}, Video {video_id} ({video.filename})"
            )
            set_upload_progress(user_id, video_id, 50)
        
        # Success - update video in database
        custom_settings = custom_settings.copy() if custom_settings else {}
        custom_settings['tiktok_publish_id'] = publish_id
        update_video(video_id, user_id, db=db, status="uploaded", custom_settings=custom_settings)
        set_upload_progress(user_id, video_id, 100)
        final_method = upload_method if 'upload_method' in locals() else ("PULL_FROM_URL" if use_pull_from_url else "FILE_UPLOAD")
        tiktok_logger.info(
            f"TikTok upload successful using {final_method} method - "
            f"User {user_id}, Video {video_id} ({video.filename}), publish_id: {publish_id}"
        )
        
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

