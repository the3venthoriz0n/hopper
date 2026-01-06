"""Background status checker task for long-running uploads"""
import asyncio
import logging
import httpx
from typing import Dict, Any, Optional

from app.db.helpers import update_video, get_oauth_token, get_all_user_settings, get_all_oauth_tokens
from app.db.session import SessionLocal
from app.db.redis import set_upload_progress, get_upload_progress
from app.models.video import Video
from app.services.video.platforms.tiktok_api import fetch_tiktok_publish_status
from app.services.event_service import publish_video_status_changed, publish_video_updated
from app.core.config import INSTAGRAM_GRAPH_API_BASE
from app.utils.encryption import decrypt
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
                                # Video was published - get tiktok_id
                                tiktok_id = status_data.get("video_id")
                                if tiktok_id:
                                    # Update video with tiktok_id
                                    custom_settings = custom_settings.copy()
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
                                    
                                    if all_done and video.status != "uploaded":
                                        update_video(video.id, video.user_id, db=db, custom_settings=custom_settings, status="uploaded")
                                        
                                        # Refresh video and build full response (backend is source of truth)
                                        db.refresh(video)
                                        from app.services.event_service import publish_video_status_changed
                                        from app.services.video.helpers import build_video_response
                                        video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                        
                                        await publish_video_status_changed(video.user_id, video.id, old_status, "uploaded", video_dict=video_dict)
                                        status_logger.info(f"TikTok video {video.id} published successfully, tiktok_id: {tiktok_id}")
                                    else:
                                        update_video(video.id, video.user_id, db=db, custom_settings=custom_settings)
                                        
                                        # Refresh video and build full response (backend is source of truth)
                                        db.refresh(video)
                                        from app.services.event_service import publish_video_updated
                                        from app.services.video.helpers import build_video_response
                                        video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                        
                                        await publish_video_updated(video.user_id, video.id, {"tiktok_id": tiktok_id})
                                        status_logger.info(f"TikTok video {video.id} updated with tiktok_id: {tiktok_id}")
                                
                            elif status == "PROCESSING":
                                # Still processing - update progress
                                set_upload_progress(video.user_id, video.id, 75)
                                status_logger.debug(f"TikTok video {video.id} still processing")
                            
                            elif status == "FAILED":
                                # Upload failed
                                fail_reason = status_data.get("fail_reason", "Unknown error")
                                old_status = video.status
                                update_video(video.id, video.user_id, db=db, status="failed", error=f"TikTok upload failed: {fail_reason}")
                                
                                # Refresh video and build full response (backend is source of truth)
                                db.refresh(video)
                                from app.services.event_service import publish_video_status_changed
                                from app.services.video.helpers import build_video_response
                                from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
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
                                    # Container is ready - but we need to check if it was published
                                    # If video status is still "uploading", the publish step might have failed
                                    # or the container is ready but not published yet
                                    # For now, just update progress - the upload process should handle publishing
                                    set_upload_progress(video.user_id, video.id, 80)
                                    status_logger.debug(f"Instagram container {instagram_container_id} finished for video {video.id}")
                                
                                elif status_code == "ERROR":
                                    # Container processing failed
                                    old_status = video.status
                                    update_video(video.id, video.user_id, db=db, status="failed", error="Instagram container processing failed")
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_status_changed
                                    from app.services.video.helpers import build_video_response
                                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
                                    all_settings = get_all_user_settings(video.user_id, db=db)
                                    all_tokens = get_all_oauth_tokens(video.user_id, db=db)
                                    video_dict = build_video_response(video, all_settings, all_tokens, video.user_id)
                                    
                                    await publish_video_status_changed(video.user_id, video.id, old_status, "failed", video_dict=video_dict)
                                    status_logger.warning(f"Instagram container {instagram_container_id} failed for video {video.id}")
                                
                                elif status_code == "EXPIRED":
                                    # Container expired
                                    old_status = video.status
                                    update_video(video.id, video.user_id, db=db, status="failed", error="Instagram container expired (not published within 24 hours)")
                                    
                                    # Refresh video and build full response (backend is source of truth)
                                    db.refresh(video)
                                    from app.services.event_service import publish_video_status_changed
                                    from app.services.video.helpers import build_video_response
                                    from app.db.helpers import get_all_user_settings, get_all_oauth_tokens
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

