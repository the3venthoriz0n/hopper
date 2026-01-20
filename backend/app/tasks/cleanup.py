"""Background cleanup task for removing old uploaded videos and orphaned files"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.db.helpers import get_all_scheduled_videos
from app.db.session import SessionLocal
from app.models.video import Video
from app.services.video.helpers import cleanup_video_file

# Import Prometheus metrics from centralized location
from app.core.metrics import (
    cleanup_runs_counter,
    cleanup_files_removed_counter,
    orphaned_videos_gauge,
    storage_size_gauge
)

cleanup_logger = logging.getLogger("cleanup")


async def cleanup_task():
    """Background task that cleans up old uploaded videos and orphaned files
    
    Runs every hour to:
    1. Delete video files for videos uploaded more than 24 hours ago
    2. Remove orphaned files (files on disk without database records)
    """
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            db = SessionLocal()
            try:
                cleanup_logger.info("Starting cleanup task...")
                
                # 1. Clean up old uploaded videos (older than 24 hours)
                # ROOT CAUSE FIX: Only clean up videos that:
                # - Have status "uploaded" (never touch pending, scheduled, uploading, or failed)
                # - Were never scheduled (scheduled_time is None) - protects scheduled videos even after upload
                # - Are older than 24 hours (based on created_at)
                # This ensures scheduled videos are NEVER cleaned before or after upload
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                old_uploaded_videos = db.query(Video).filter(
                    Video.status == "uploaded",  # Only uploaded videos
                    Video.scheduled_time.is_(None),  # Never delete files from videos that were scheduled
                    Video.created_at < cutoff_time  # Only old videos
                ).all()
                
                cleaned_count = 0
                for video in old_uploaded_videos:
                    if cleanup_video_file(video):
                        cleaned_count += 1
                
                if cleaned_count > 0:
                    cleanup_logger.info(f"Cleaned up {cleaned_count} old uploaded video files")
                
                # 2. Orphaned file cleanup removed - R2 storage doesn't have orphaned files in the same way
                # R2 objects are managed through the database path field, so orphaned objects would need
                # R2 API calls to detect. This is not implemented as it's not critical for operation.
                # If needed, a separate R2 cleanup task could be added to list and compare R2 objects.
                
                # Update storage metrics - R2 storage size tracking would require R2 API calls
                # For now, set to 0 as we're no longer using local storage
                try:
                    storage_size_gauge.labels(type="upload_dir").set(0)
                    orphaned_videos_gauge.set(0)
                except Exception as e:
                    cleanup_logger.warning(f"Failed to update storage metrics: {e}")
                
                cleanup_runs_counter.labels(status="success").inc()
                cleanup_logger.info("Cleanup task completed")
                
            finally:
                db.close()
                
        except Exception as e:
            cleanup_logger.error(f"Error in cleanup task: {e}", exc_info=True)
            cleanup_runs_counter.labels(status="failure").inc()
            await asyncio.sleep(3600)

