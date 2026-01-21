"""Background status checker task for long-running uploads"""
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional

from app.db.helpers import update_video, get_oauth_token, get_all_user_settings, get_all_oauth_tokens
from app.db.session import SessionLocal
from app.db.redis import set_upload_progress, get_upload_progress, is_upload_active, set_platform_upload_progress, delete_upload_progress
from app.models.video import Video
from app.services.video.platforms.tiktok_api import fetch_tiktok_publish_status
from app.services.event_service import publish_video_status_changed, publish_video_updated, publish_upload_progress
from app.core.config import INSTAGRAM_GRAPH_API_BASE
from app.utils.encryption import decrypt
from app.services.token_service import deduct_tokens, calculate_tokens_from_bytes
from app.core.metrics import successful_uploads_counter
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)
status_logger = logging.getLogger("status_checker")


async def status_checker_task():
    """Background task that periodically checks status for in-progress uploads
    
    Checks:
    - TikTok: Videos with tiktok_publish_id but no tiktok_id (PULL_FROM_URL in progress)
    - Instagram: Videos with instagram_container_id and status="uploading"
    
    Publishes WebSocket events when status changes.
    """
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            db = SessionLocal()
            if db is None:
                logger.error("Failed to create database session in status checker task")
                await asyncio.sleep(30)
                continue
            
            try:
                # Query TikTok videos with publish_id but no tiktok_id (PULL_FROM_URL in progress)
                tiktok_videos = db.query(Video).filter(
                    Video.status.in_(['uploading', 'uploaded']),
                    Video.custom_settings.isnot(None)
                ).all()
                
                tiktok_videos_to_check = []
                for video in tiktok_videos:
                    custom_settings = video.custom_settings or {}
                    tiktok_publish_id = custom_settings.get("tiktok_publish_id")
                    tiktok_id = custom_settings.get("tiktok_id")
                    # Has publish_id but no tiktok_id yet - still processing
                    if tiktok_publish_id and not tiktok_id:
                        tiktok_videos_to_check.append(video)
                
                # Query Instagram videos with container_id and status="uploading"
                instagram_videos = db.query(Video).filter(
                    Video.status == "uploading",
                    Video.custom_settings.isnot(None)
                ).all()
                
                instagram_videos_to_check = []
                for video in instagram_videos:
                    custom_settings = video.custom_settings or {}
                    instagram_container_id = custom_settings.get("instagram_container_id")
                    # Has container_id but still uploading - check if container is finished
                    if instagram_container_id:
                        instagram_videos_to_check.append(video)
                
                # Check TikTok videos
                for video in tiktok_videos_to_check:
                    try:
                        custom_settings = video.custom_settings or {}
                        tiktok_publish_id = custom_settings.get("tiktok_publish_id")
                        
                        if not tiktok_publish_id:
                            continue
                        
                        status_data = fetch_tiktok_publish_status(video.user_id, tiktok_publish_id, db=db)
                        
                        if status_data:
                            status = status_data.get("status", "UNKNOWN")
                            
                            if status == "PUBLISHED":
                                # Video was published - get tiktok_id (may be None if 404 was returned)
                                tiktok_id = status_data.get("video_id")
                                # ROOT CAUSE FIX: Handle PUBLISHED status even when video_id is None (from 404)
                                # Having tiktok_publish_id means video was published, so we should mark it as uploaded
                                custom_settings = custom_settings.copy()
                                if tiktok_id:
                                    custom_settings["tiktok_id"] = tiktok_id
                                old_status = video.status
                                
                                # Check if all destinations are done
                                from app.services.video import check_upload_success
                                all_settings = get_all_user_settings(video.user_id, db=db)
                                all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                dest_settings = all_settings.get("destinations", {})
                                
                                # Check all enabled destinations
                                enabled_destinations = []
                                if all_settings.get("youtube", {}).get("youtube_enabled"):
                                    enabled_destinations.append("youtube")
                                if all_settings.get("tiktok", {}).get("tiktok_enabled"):
                                    enabled_destinations.append("tiktok")
                                if all_settings.get("instagram", {}).get("instagram_enabled"):
                                    enabled_destinations.append("instagram")
                                
                                all_done = all(check_upload_success(video, dest) for dest in enabled_destinations)
                                
                                # Refresh video to get latest state before checking tokens
                                db.refresh(video)
                                
                                # Deduct tokens if not already deducted (matches upload function behavior)
                                if video.tokens_consumed == 0:
                                    tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
                                    if tokens_required > 0:
                                        await deduct_tokens(
                                            user_id=video.user_id,
                                            tokens=tokens_required,
                                            transaction_type='upload',
                                            video_id=video.id,
                                            metadata={
                                                'filename': video.filename,
                                                'platform': 'tiktok',
                                                'tiktok_publish_id': tiktok_publish_id,
                                                'tiktok_id': tiktok_id,
                                                'file_size_bytes': video.file_size_bytes,
                                                'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else 0
                                            },
                                            db=db
                                        )
                                        update_video(video.id, video.user_id, db=db, tokens_consumed=tokens_required)
                                        status_logger.info(f"Deducted {tokens_required} tokens for user {video.user_id} (TikTok upload via status_checker)")
                                
                                if all_done and video.status != "uploaded":
                                    update_video(video.id, video.user_id, db=db, custom_settings=custom_settings, status="uploaded")
                                    
                                    # Increment successful uploads counter
                                    successful_uploads_counter.inc()
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_status_changed
                                    from app.services.video.helpers import build_video_response
                                    video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                    
                                    await publish_video_status_changed(video.user_id, video.id, old_status, "uploaded", video_dict=video_dict)
                                    if tiktok_id:
                                        status_logger.info(f"TikTok video {video.id} published successfully, tiktok_id: {tiktok_id}")
                                    else:
                                        status_logger.info(f"TikTok video {video.id} published successfully (via 404), publish_id: {tiktok_publish_id}")
                                else:
                                    update_video(video.id, video.user_id, db=db, custom_settings=custom_settings)
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_updated
                                    from app.services.video.helpers import build_video_response
                                    video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                    
                                    await publish_video_updated(video.user_id, video.id, video_dict=video_dict)
                                    if tiktok_id:
                                        status_logger.info(f"TikTok video {video.id} updated with tiktok_id: {tiktok_id}")
                                    else:
                                        status_logger.info(f"TikTok video {video.id} updated (published via 404), publish_id: {tiktok_publish_id}")
                                
                            elif status in ["PROCESSING_DOWNLOAD", "PROCESSING_UPLOAD", "PROCESSING"]:
                                # Map status to progress percentages
                                # PROCESSING_DOWNLOAD: 10-50% (TikTok downloading from our server)
                                # PROCESSING_UPLOAD: 50-90% (TikTok processing the video)
                                # PROCESSING: legacy status, treat as PROCESSING_UPLOAD (50-90%)
                                
                                from app.services.video.helpers import should_publish_progress
                                from app.services.event_service import publish_upload_progress
                                
                                # Get current progress to determine which range we're in
                                current_progress = get_upload_progress(video.user_id, video.id) or 0
                                
                                if status == "PROCESSING_DOWNLOAD":
                                    # Estimate 10-50% based on time (we don't know exact progress)
                                    # Use a simple increment approach: start at 10%, gradually move to 50%
                                    if current_progress < 10:
                                        progress = 10
                                    elif current_progress < 50:
                                        # Increment by 5% each check (every 30 seconds)
                                        progress = min(current_progress + 5, 50)
                                    else:
                                        progress = 50
                                elif status in ["PROCESSING_UPLOAD", "PROCESSING"]:
                                    # Estimate 50-90% based on time
                                    if current_progress < 50:
                                        progress = 50
                                    elif current_progress < 90:
                                        # Increment by 5% each check
                                        progress = min(current_progress + 5, 90)
                                    else:
                                        progress = 90
                                else:
                                    progress = current_progress
                                
                                set_upload_progress(video.user_id, video.id, progress)
                                
                                # Publish progress updates (1% increments)
                                if should_publish_progress(progress, current_progress):
                                    await publish_upload_progress(video.user_id, video.id, "tiktok", progress)
                                
                                status_logger.debug(f"TikTok video {video.id} still processing: {status}, progress: {progress}%")
                            
                            elif status == "FAILED":
                                # Upload failed
                                fail_reason = status_data.get("fail_reason", "Unknown error")
                                old_status = video.status
                                update_video(video.id, video.user_id, db=db, status="failed", error=f"TikTok upload failed: {fail_reason}")
                                
                                # Refresh video and build full response (backend is source of truth)
                                db.refresh(video)
                                from app.services.event_service import publish_video_status_changed
                                from app.services.video.helpers import build_video_response
                                all_settings = get_all_user_settings(video.user_id, db=db)
                                all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                
                                await publish_video_status_changed(video.user_id, video.id, old_status, "failed", video_dict=video_dict)
                                status_logger.warning(f"TikTok video {video.id} failed: {fail_reason}")
                    
                    except Exception as e:
                        status_logger.error(f"Error checking TikTok status for video {video.id}: {e}", exc_info=True)
                        continue
                
                # Check Instagram videos
                for video in instagram_videos_to_check:
                    try:
                        custom_settings = video.custom_settings or {}
                        instagram_container_id = custom_settings.get("instagram_container_id")
                        
                        if not instagram_container_id:
                            continue
                        
                        # Get Instagram token
                        instagram_token = get_oauth_token(video.user_id, "instagram", db=db)
                        if not instagram_token:
                            continue
                        
                        access_token = decrypt(instagram_token.access_token)
                        if not access_token:
                            continue
                        
                        # Check container status
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            status_url = f"{INSTAGRAM_GRAPH_API_BASE}/{instagram_container_id}"
                            status_params = {
                                "fields": "status_code",
                                "access_token": access_token.strip()
                            }
                            
                            status_response = await client.get(status_url, params=status_params)
                            
                            if status_response.status_code == 200:
                                status_data = status_response.json()
                                status_code = status_data.get('status_code')
                                
                                if status_code == "FINISHED":
                                    # Container is ready - check if it was already published
                                    instagram_id = custom_settings.get("instagram_id")
                                    if instagram_id:
                                        # Already published - just update progress
                                        set_upload_progress(video.user_id, video.id, 100)
                                        set_platform_upload_progress(video.user_id, video.id, "instagram", 100)
                                        status_logger.debug(f"Instagram container {instagram_container_id} already published for video {video.id} (instagram_id: {instagram_id})")
                                        continue
                                    
                                    # Check if upload is actively being processed - if yes, let upload function handle it
                                    if is_upload_active(video.id, "instagram"):
                                        status_logger.debug(f"Instagram container {instagram_container_id} finished but upload is active - letting upload function handle publishing")
                                        set_upload_progress(video.user_id, video.id, 90)
                                        set_platform_upload_progress(video.user_id, video.id, "instagram", 90)
                                        continue
                                    
                                    # Container is FINISHED and not published - publish it now
                                    status_logger.info(f"Instagram container {instagram_container_id} finished for video {video.id} - publishing via status_checker")
                                    
                                    try:
                                        # Get business_account_id from token extra_data
                                        extra_data = instagram_token.extra_data or {}
                                        business_account_id = extra_data.get("business_account_id")
                                        if not business_account_id:
                                            status_logger.error(f"No business_account_id for video {video.id} - cannot publish")
                                            continue
                                        
                                        # Publish the container
                                        publish_url = f"{INSTAGRAM_GRAPH_API_BASE}/{business_account_id}/media_publish"
                                        publish_data = {
                                            "creation_id": instagram_container_id
                                        }
                                        publish_headers = {
                                            "Authorization": f"Bearer {access_token.strip()}",
                                            "Content-Type": "application/json"
                                        }
                                        
                                        publish_response = await client.post(
                                            publish_url,
                                            json=publish_data,
                                            headers=publish_headers
                                        )
                                        
                                        if publish_response.status_code != 200:
                                            import json as json_module
                                            error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else publish_response.text
                                            status_logger.error(
                                                f"Failed to publish Instagram container {instagram_container_id} for video {video.id}: "
                                                f"HTTP {publish_response.status_code} - {error_data}"
                                            )
                                            continue
                                        
                                        publish_result = publish_response.json()
                                        media_id = publish_result.get('id')
                                        
                                        if not media_id:
                                            status_logger.error(f"No media ID in publish response for video {video.id}: {publish_result}")
                                            continue
                                        
                                        # Update video with instagram_id and status
                                        custom_settings = custom_settings.copy()
                                        custom_settings['instagram_id'] = media_id
                                        old_status = video.status
                                        
                                        # Check if all destinations are done
                                        from app.services.video import check_upload_success
                                        all_settings = get_all_user_settings(video.user_id, db=db)
                                        all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                        
                                        # Check all enabled destinations
                                        enabled_destinations = []
                                        if all_settings.get("youtube", {}).get("youtube_enabled"):
                                            enabled_destinations.append("youtube")
                                        if all_settings.get("tiktok", {}).get("tiktok_enabled"):
                                            enabled_destinations.append("tiktok")
                                        if all_settings.get("instagram", {}).get("instagram_enabled"):
                                            enabled_destinations.append("instagram")
                                        
                                        all_done = all(check_upload_success(video, dest) for dest in enabled_destinations)
                                        
                                        # Update status based on whether all destinations are done
                                        if all_done:
                                            update_video(video.id, video.user_id, db=db, custom_settings=custom_settings, status="completed")
                                        else:
                                            update_video(video.id, video.user_id, db=db, custom_settings=custom_settings)
                                        
                                        # Update progress to 100%
                                        set_upload_progress(video.user_id, video.id, 100)
                                        set_platform_upload_progress(video.user_id, video.id, "instagram", 100)
                                        await publish_upload_progress(video.user_id, video.id, "instagram", 100)
                                        
                                        # Increment successful uploads counter
                                        successful_uploads_counter.inc()
                                        
                                        # Deduct tokens if not already deducted
                                        db.refresh(video)
                                        if video.tokens_consumed == 0:
                                            tokens_required = video.tokens_required if video.tokens_required is not None else (calculate_tokens_from_bytes(video.file_size_bytes) if video.file_size_bytes else 0)
                                            if tokens_required > 0:
                                                await deduct_tokens(
                                                    user_id=video.user_id,
                                                    tokens=tokens_required,
                                                    transaction_type='upload',
                                                    video_id=video.id,
                                                    metadata={
                                                        'filename': video.filename,
                                                        'platform': 'instagram',
                                                        'instagram_id': media_id,
                                                        'file_size_bytes': video.file_size_bytes,
                                                        'file_size_mb': round(video.file_size_bytes / (1024 * 1024), 2) if video.file_size_bytes else 0
                                                    },
                                                    db=db
                                                )
                                                update_video(video.id, video.user_id, db=db, tokens_consumed=tokens_required)
                                                status_logger.info(f"Deducted {tokens_required} tokens for user {video.user_id} (Instagram upload via status_checker)")
                                        
                                        # Refresh video and build full response
                                        db.refresh(video)
                                        from app.services.video.helpers import build_video_response
                                        video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                        
                                        if all_done and old_status != "completed":
                                            await publish_video_status_changed(video.user_id, video.id, old_status, "completed", video_dict=video_dict)
                                        else:
                                            await publish_video_updated(video.user_id, video.id, video_dict=video_dict)
                                        
                                        status_logger.info(f"Successfully published Instagram container {instagram_container_id} for video {video.id} via status_checker (media_id: {media_id})")
                                        
                                        # Clean up progress after a delay
                                        await asyncio.sleep(2)
                                        delete_upload_progress(video.user_id, video.id)
                                        
                                    except Exception as publish_error:
                                        status_logger.error(
                                            f"Error publishing Instagram container {instagram_container_id} for video {video.id}: {publish_error}",
                                            exc_info=True
                                        )
                                        continue
                                
                                elif status_code == "ERROR":
                                    # ROOT CAUSE FIX: Only mark as failed if upload is NOT actively being processed
                                    # Check 1: If video already has instagram_id, upload succeeded - don't mark as failed
                                    instagram_id = custom_settings.get("instagram_id")
                                    if instagram_id:
                                        status_logger.debug(
                                            f"Ignoring ERROR status for video {video.id} - already published successfully "
                                            f"(instagram_id: {instagram_id})"
                                        )
                                        continue
                                    
                                    # Check 2: If upload is actively being processed, don't interfere
                                    if is_upload_active(video.id, "instagram"):
                                        status_logger.debug(
                                            f"Ignoring ERROR status for video {video.id} - upload is actively being processed"
                                        )
                                        continue
                                    
                                    # Check 3: Only mark as failed if video has been stuck for a while
                                    # Check if progress exists (indicates recent activity)
                                    recent_progress = get_upload_progress(video.user_id, video.id)
                                    if recent_progress is not None:
                                        # Progress exists = upload was active recently, might still be processing
                                        status_logger.debug(
                                            f"Ignoring ERROR status for video {video.id} - progress exists "
                                            f"(progress: {recent_progress}%), upload may still be active"
                                        )
                                        continue
                                    
                                    # All checks passed - container is truly in ERROR state and upload is not active
                                    # Container processing failed and video wasn't published - mark as failed
                                    old_status = video.status
                                    update_video(video.id, video.user_id, db=db, status="failed", error="Instagram container processing failed")
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_status_changed
                                    from app.services.video.helpers import build_video_response
                                    all_settings = get_all_user_settings(video.user_id, db=db)
                                    all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                    video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                    
                                    await publish_video_status_changed(video.user_id, video.id, old_status, "failed", video_dict=video_dict)
                                    status_logger.warning(f"Instagram container {instagram_container_id} failed for video {video.id}")
                                
                                elif status_code == "EXPIRED":
                                    # ROOT CAUSE FIX: Only mark as failed if upload is NOT actively being processed
                                    instagram_id = custom_settings.get("instagram_id")
                                    if instagram_id:
                                        status_logger.debug(
                                            f"Ignoring EXPIRED status for video {video.id} - already published successfully "
                                            f"(instagram_id: {instagram_id})"
                                        )
                                        continue
                                    
                                    # Check if upload is actively being processed
                                    if is_upload_active(video.id, "instagram"):
                                        status_logger.debug(
                                            f"Ignoring EXPIRED status for video {video.id} - upload is actively being processed"
                                        )
                                        continue
                                    
                                    # Container expired and video wasn't published - mark as failed
                                    old_status = video.status
                                    update_video(video.id, video.user_id, db=db, status="failed", error="Instagram container expired (not published within 24 hours)")
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_status_changed
                                    from app.services.video.helpers import build_video_response
                                    all_settings = get_all_user_settings(video.user_id, db=db)
                                    all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                    video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                    
                                    await publish_video_status_changed(video.user_id, video.id, old_status, "failed", video_dict=video_dict)
                                    status_logger.warning(f"Instagram container {instagram_container_id} expired for video {video.id}")
                                
                                # IN_PROGRESS - continue waiting
                                else:
                                    # Update progress based on how long we've been waiting
                                    current_progress = get_upload_progress(video.user_id, video.id) or 40
                                    if current_progress < 80:
                                        new_progress = min(current_progress + 5, 80)
                                        set_upload_progress(video.user_id, video.id, new_progress)
                                    status_logger.debug(f"Instagram container {instagram_container_id} still processing for video {video.id}")
                    
                    except Exception as e:
                        status_logger.error(f"Error checking Instagram status for video {video.id}: {e}", exc_info=True)
                        continue
                
            except Exception as e:
                logger.error(f"Error in status checker task: {e}", exc_info=True)
            finally:
                if db:
                    db.close()
        
        except Exception as e:
            logger.error(f"Fatal error in status checker task: {e}", exc_info=True)
            await asyncio.sleep(30)  # Wait before retrying

