"""Background scheduler tasks for video posting queue and token resets"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from app.db.helpers import get_all_scheduled_videos, update_video
from app.db.session import SessionLocal
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.models.video import Video
from app.services.token_service import reset_tokens_for_subscription
from app.services.video_service import (
    DESTINATION_UPLOADERS, build_upload_context, check_upload_success, cleanup_video_file
)

# Import Prometheus metrics from centralized location
from app.core.metrics import (
    successful_uploads_counter,
    scheduler_runs_counter,
    scheduler_videos_processed_counter
)

logger = logging.getLogger(__name__)
upload_logger = logging.getLogger("upload")


async def scheduler_task():
    """Background task that checks for scheduled videos and uploads them to all enabled destinations
    Optimized to use batch queries instead of querying per user/video"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = datetime.now(timezone.utc)
            
            # Batch query: Get all scheduled videos across all users in a single query
            db = SessionLocal()
            if db is None:
                logger.error("Failed to create database session in scheduler task")
                continue
            try:
                # Single query to get all scheduled videos, grouped by user_id
                videos_by_user = get_all_scheduled_videos(db=db)
                
                videos_processed = 0
                # Process videos grouped by user (allows batch loading of user settings/tokens)
                for user_id, videos in videos_by_user.items():
                    # Build upload context (enabled destinations, settings, tokens)
                    # ROOT CAUSE FIX: Ensure session is valid before use, create new one if invalid
                    if db is None:
                        db = SessionLocal()
                    try:
                        upload_context = build_upload_context(user_id, db)
                    except Exception as context_err:
                        # Session might be invalid - create a new one
                        logger.warning(f"Session invalid when building upload context for user {user_id}, creating new session: {context_err}")
                        if db is not None:
                            try:
                                db.close()
                            except Exception:
                                pass
                        db = SessionLocal()
                        upload_context = build_upload_context(user_id, db)
                    
                    enabled_destinations = upload_context["enabled_destinations"]
                    
                    if not enabled_destinations:
                        # Skip this user if no destinations are enabled
                        continue
                    
                    # Process each scheduled video for this user
                    for video in videos:
                        try:
                            scheduled_time = datetime.fromisoformat(video.scheduled_time) if isinstance(video.scheduled_time, str) else video.scheduled_time
                            
                            # ROOT CAUSE FIX: Upload if scheduled time has passed
                            # This handles both:
                            # 1. Videos scheduled for future upload (status="scheduled")
                            # 2. Videos that were uploading when server restarted (status="uploading")
                            if current_time >= scheduled_time:
                                video_id = video.id
                                videos_processed += 1
                                scheduler_videos_processed_counter.inc()
                                
                                # Log whether this is a retry or new upload
                                if video.status == "uploading":
                                    upload_logger.info(f"Retrying upload for video that was in progress: {video.filename} (user {user_id})")
                                else:
                                    upload_logger.info(f"Uploading scheduled video for user {user_id}: {video.filename}")
                                
                                # Mark as uploading - use shared session
                                # This is idempotent - safe to call even if already "uploading"
                                # ROOT CAUSE FIX: Ensure session is valid before use
                                if db is None:
                                    db = SessionLocal()
                                try:
                                    update_video(video_id, user_id, db=db, status="uploading")
                                except Exception as update_err:
                                    # Session might be invalid - create a new one
                                    logger.warning(f"Session invalid when updating video {video_id}, creating new session: {update_err}")
                                    if db is not None:
                                        try:
                                            db.close()
                                        except Exception:
                                            pass
                                    db = SessionLocal()
                                    update_video(video_id, user_id, db=db, status="uploading")
                                
                                # Upload to each enabled destination - uploader functions query DB directly
                                # Note: Upload functions create their own sessions (backward compatible)
                                success_count = 0
                                for dest_name in enabled_destinations:
                                    uploader_func = DESTINATION_UPLOADERS.get(dest_name)
                                    if uploader_func:
                                        try:
                                            logger.debug(f"  Uploading to {dest_name}...")
                                            # Pass user_id, video_id, and db session - uploader functions need db
                                            # ROOT CAUSE FIX: Pass db session to uploader functions so they don't receive None
                                            if dest_name == "instagram":
                                                await uploader_func(user_id, video_id, db=db)
                                            else:
                                                uploader_func(user_id, video_id, db=db)
                                            
                                            # Expire the video object from this session to force fresh query
                                            # The upload function uses its own session, so we need to refresh
                                            # ROOT CAUSE FIX: Ensure session is valid before use, create new one if invalid
                                            if db is None:
                                                db = SessionLocal()
                                            try:
                                                db.expire_all()
                                                
                                                # Check if upload succeeded by querying updated video - use shared session
                                                # Note: We could optimize this further by caching the video object, but for now
                                                # we'll query to ensure we have the latest state
                                                updated_video = db.query(Video).filter(Video.id == video_id).first()
                                                if updated_video and check_upload_success(updated_video, dest_name):
                                                    success_count += 1
                                            except Exception as db_err:
                                                # Session might be invalid - create a new one to check upload status
                                                logger.warning(f"Session invalid when checking upload status for video {video_id}, creating new session: {db_err}")
                                                if db is not None:
                                                    try:
                                                        db.close()
                                                    except Exception:
                                                        pass
                                                db = SessionLocal()
                                                try:
                                                    updated_video = db.query(Video).filter(Video.id == video_id).first()
                                                    if updated_video and check_upload_success(updated_video, dest_name):
                                                        success_count += 1
                                                except Exception:
                                                    # If still failing, use temporary session
                                                    temp_db = SessionLocal()
                                                    try:
                                                        updated_video = temp_db.query(Video).filter(Video.id == video_id).first()
                                                        if updated_video and check_upload_success(updated_video, dest_name):
                                                            success_count += 1
                                                    finally:
                                                        temp_db.close()
                                        except Exception as upload_err:
                                            error_type = type(upload_err).__name__
                                            error_msg = str(upload_err)
                                            
                                            # Gather context for troubleshooting
                                            # Note: Use 'video_filename' instead of 'filename' to avoid conflict with LogRecord.filename
                                            context = {
                                                "user_id": user_id,
                                                "video_id": video_id,
                                                "video_filename": video.filename,
                                                "platform": dest_name,
                                                "error_type": error_type,
                                                "error_message": error_msg,
                                                "scheduled_time": str(scheduled_time) if 'scheduled_time' in locals() else None,
                                            }
                                            
                                            # Log comprehensive error
                                            upload_logger.error(
                                                f"❌ Upload FAILED in scheduler - User {user_id}, Video {video_id} ({video.filename}), "
                                                f"Platform {dest_name}: {error_type}: {error_msg}",
                                                extra=context,
                                                exc_info=True
                                            )
                                            
                                            logger.debug(f"  Error uploading to {dest_name}: {upload_err}")
                                
                                # Update final status - use shared session if valid, otherwise create new one
                                # ROOT CAUSE FIX: Ensure session is valid before use
                                if db is None:
                                    db = SessionLocal()
                                
                                if success_count == len(enabled_destinations):
                                    try:
                                        update_video(video_id, user_id, db=db, status="uploaded")
                                    except Exception as update_err:
                                        # Session might be invalid - create a new one
                                        logger.warning(f"Session invalid when updating video {video_id} to uploaded, creating new session: {update_err}")
                                        if db is not None:
                                            try:
                                                db.close()
                                            except Exception:
                                                pass
                                        db = SessionLocal()
                                        update_video(video_id, user_id, db=db, status="uploaded")
                                    
                                    # Increment successful uploads counter
                                    successful_uploads_counter.inc()
                                    
                                    # Cleanup: Delete video file after successful upload to all destinations
                                    # Keep database record for history
                                    try:
                                        updated_video = db.query(Video).filter(Video.id == video_id).first()
                                        if updated_video:
                                            cleanup_video_file(updated_video)
                                    except Exception as query_err:
                                        # Session might be invalid - create a new one
                                        logger.warning(f"Session invalid when querying video {video_id}, creating new session: {query_err}")
                                        if db is not None:
                                            try:
                                                db.close()
                                            except Exception:
                                                pass
                                        db = SessionLocal()
                                        updated_video = db.query(Video).filter(Video.id == video_id).first()
                                        if updated_video:
                                            cleanup_video_file(updated_video)
                                else:
                                    try:
                                        update_video(video_id, user_id, db=db, status="failed", error=f"Upload failed for some destinations")
                                    except Exception as update_err:
                                        # Session might be invalid - create a new one
                                        logger.warning(f"Session invalid when updating video {video_id} to failed, creating new session: {update_err}")
                                        if db is not None:
                                            try:
                                                db.close()
                                            except Exception:
                                                pass
                                        db = SessionLocal()
                                        update_video(video_id, user_id, db=db, status="failed", error=f"Upload failed for some destinations")
                                    
                        except Exception as e:
                            error_type = type(e).__name__
                            error_msg = str(e)
                            
                            # Gather context for troubleshooting
                            # Note: Use 'video_filename' instead of 'filename' to avoid conflict with LogRecord.filename
                            context = {
                                "user_id": user_id,
                                "video_id": video_id if 'video_id' in locals() else None,
                                "video_filename": video.filename,
                                "video_status": video.status,
                                "error_type": error_type,
                                "error_message": error_msg,
                                "scheduled_time": str(scheduled_time) if 'scheduled_time' in locals() else None,
                            }
                            
                            # Log comprehensive error
                            upload_logger.error(
                                f"❌ Scheduler task FAILED - User {user_id}, Video {video.id if hasattr(video, 'id') else 'unknown'} "
                                f"({video.filename}): {error_type}: {error_msg}",
                                extra={"context": context},
                                exc_info=True
                            )
                            
                            logger.debug(f"Error processing scheduled video {video.filename}: {e}")
                            if 'video_id' in locals():
                                detailed_error = f"Scheduler error: {error_type}: {error_msg}"
                                if db is not None:
                                    try:
                                        update_video(video_id, user_id, db=db, status="failed", error=detailed_error)
                                    except Exception:
                                        # Session invalid - create new one
                                        temp_db = SessionLocal()
                                        try:
                                            update_video(video_id, user_id, db=temp_db, status="failed", error=detailed_error)
                                        finally:
                                            temp_db.close()
                                else:
                                    temp_db = SessionLocal()
                                    try:
                                        update_video(video_id, user_id, db=temp_db, status="failed", error=detailed_error)
                                    finally:
                                        temp_db.close()
                
                scheduler_runs_counter.labels(status="success").inc()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in scheduler task: {e}", exc_info=True)
            scheduler_runs_counter.labels(status="failure").inc()
            await asyncio.sleep(30)


async def token_reset_scheduler_task():
    """Background task to reset tokens for subscriptions that have reached their period end"""
    logger.info("Starting token reset scheduler task...")
    
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                
                # Find subscriptions that need token reset (period_end has passed, but tokens not reset)
                # This handles both Stripe subscriptions (renewed via webhooks) and free subscriptions (renewed manually)
                subscriptions = db.query(Subscription).filter(
                    Subscription.status == 'active',
                    Subscription.current_period_end <= now
                ).all()
                
                for subscription in subscriptions:
                    # Check if tokens have been reset for this period
                    balance = db.query(TokenBalance).filter(
                        TokenBalance.user_id == subscription.user_id
                    ).first()
                    
                    # Reset if period_end has passed and last_reset_at is before period_end
                    should_reset = False
                    is_renewal = False
                    if not balance:
                        should_reset = True
                        is_renewal = False  # New subscription, add tokens
                    elif not balance.last_reset_at:
                        should_reset = True
                        is_renewal = False  # First time setup, add tokens
                    elif balance.last_reset_at < subscription.current_period_end:
                        should_reset = True
                        # Check if this is a renewal: if token balance period_end exists and is different from subscription period_end
                        # This indicates the subscription period has moved forward (renewal)
                        if balance.period_end and balance.period_end != subscription.current_period_end:
                            # Period changed - check if it's a renewal
                            # Use the same logic as handle_subscription_renewal: period advanced by at least 20 days
                            period_diff_days = (subscription.current_period_end - balance.period_end).total_seconds() / 86400
                            if 20 <= period_diff_days < 365:  # Reasonable billing cycle (monthly, bi-monthly, quarterly, etc.)
                                is_renewal = True
                            else:
                                is_renewal = False  # Period changed but not by a reasonable amount (plan switch or other)
                        else:
                            is_renewal = False  # First time for this period, but not a renewal
                    
                    if should_reset:
                        # For free subscriptions, we need to update the period dates when renewing
                        # Stripe subscriptions have their periods updated via webhooks
                        period_start = subscription.current_period_start
                        period_end = subscription.current_period_end
                        
                        # If period has ended, calculate new period (for free plans or missed renewals)
                        if subscription.current_period_end <= now:
                            # Calculate new period: extend by one month from current period_end
                            period_start = subscription.current_period_end
                            # Add approximately one month (30 days)
                            period_end = period_start + timedelta(days=30)
                            
                            # Update subscription period (especially important for free plans)
                            subscription.current_period_start = period_start
                            subscription.current_period_end = period_end
                            subscription.updated_at = now
                            db.flush()  # Flush to ensure period is updated before token reset
                            
                            logger.info(f"Updated subscription period for user {subscription.user_id}: {period_start} -> {period_end}")
                        
                        logger.info(f"Resetting tokens for user {subscription.user_id} (subscription {subscription.id}, plan: {subscription.plan_type}), is_renewal={is_renewal}")
                        reset_tokens_for_subscription(
                            subscription.user_id,
                            subscription.plan_type,
                            period_start,
                            period_end,
                            db,
                            is_renewal=is_renewal
                        )
                
                db.commit()
                
            except Exception as e:
                logger.error(f"Error in token reset scheduler: {e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Fatal error in token reset scheduler: {e}", exc_info=True)
            await asyncio.sleep(3600)  # Wait before retrying

