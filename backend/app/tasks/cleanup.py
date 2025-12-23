"""Background cleanup task for removing old uploaded videos and orphaned files"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.db.helpers import get_all_scheduled_videos
from app.db.session import SessionLocal
from app.models.video import Video
from app.services.video_service import cleanup_video_file

# Prometheus metrics (import from main if available, otherwise create placeholder)
try:
    from prometheus_client import Counter, Gauge, REGISTRY
    try:
        cleanup_runs_counter = Counter(
            'hopper_cleanup_runs_total',
            'Total number of cleanup job runs',
            ['status']
        )
    except ValueError:
        cleanup_runs_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_runs_total')
    
    try:
        cleanup_files_removed_counter = Counter(
            'hopper_cleanup_files_removed_total',
            'Total number of files removed by cleanup job'
        )
    except ValueError:
        cleanup_files_removed_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_files_removed_total')
    
    try:
        orphaned_videos_gauge = Gauge(
            'hopper_orphaned_videos',
            'Number of orphaned video files (files without database records)'
        )
    except ValueError:
        orphaned_videos_gauge = REGISTRY._names_to_collectors.get('hopper_orphaned_videos')
    
    try:
        storage_size_gauge = Gauge(
            'hopper_storage_size_bytes',
            'Storage size in bytes',
            ['type']
        )
    except ValueError:
        storage_size_gauge = REGISTRY._names_to_collectors.get('hopper_storage_size_bytes')
except ImportError:
    # Prometheus not available - create no-op metrics
    class NoOpCounter:
        def labels(self, **kwargs):
            return self
        def inc(self, value=1):
            pass
    class NoOpGauge:
        def labels(self, **kwargs):
            return self
        def set(self, value):
            pass
    cleanup_runs_counter = NoOpCounter()
    cleanup_files_removed_counter = NoOpCounter()
    orphaned_videos_gauge = NoOpGauge()
    storage_size_gauge = NoOpGauge()

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
                
                # 2. Find and remove orphaned files (files without database records)
                # IMPORTANT: Exclude files that belong to scheduled videos to prevent deletion before upload
                if settings.UPLOAD_DIR.exists():
                    all_files = set(settings.UPLOAD_DIR.glob("*"))
                    # Get all video paths from database - include ALL videos (scheduled, pending, etc.)
                    # ROOT CAUSE FIX: Resolve all paths to absolute to ensure proper comparison
                    all_video_paths = set(Path(v.path).resolve() for v in db.query(Video).all())
                    
                    # Also explicitly get paths of scheduled videos as extra protection
                    scheduled_video_paths = set(
                        Path(v.path).resolve() for v in db.query(Video).filter(
                            Video.status == "scheduled"
                        ).all()
                    )
                    
                    orphaned_files = all_files - all_video_paths
                    orphaned_count = 0
                    for orphaned_file in orphaned_files:
                        # Extra safety: double-check this file doesn't belong to a scheduled video
                        if orphaned_file in scheduled_video_paths:
                            cleanup_logger.warning(f"Skipping file that belongs to scheduled video: {orphaned_file.name}")
                            continue
                            
                        if orphaned_file.is_file():
                            try:
                                orphaned_file.unlink()
                                orphaned_count += 1
                                cleanup_files_removed_counter.inc()
                                cleanup_logger.info(f"Removed orphaned file: {orphaned_file.name}")
                            except Exception as e:
                                cleanup_logger.error(f"Failed to remove orphaned file {orphaned_file.name}: {e}")
                    
                    # Update orphaned videos metric (count remaining orphaned files)
                    remaining_orphaned = len([f for f in (all_files - all_video_paths) if f.is_file() and f not in scheduled_video_paths])
                    orphaned_videos_gauge.set(remaining_orphaned)
                    
                    if orphaned_count > 0:
                        cleanup_logger.info(f"Removed {orphaned_count} orphaned files")
                
                # Update storage metrics
                try:
                    if settings.UPLOAD_DIR.exists():
                        total_size = sum(f.stat().st_size for f in settings.UPLOAD_DIR.glob("*") if f.is_file())
                        storage_size_gauge.labels(type="upload_dir").set(total_size)
                except Exception as e:
                    cleanup_logger.warning(f"Failed to calculate storage size: {e}")
                
                cleanup_runs_counter.labels(status="success").inc()
                cleanup_logger.info("Cleanup task completed")
                
            finally:
                db.close()
                
        except Exception as e:
            cleanup_logger.error(f"Error in cleanup task: {e}", exc_info=True)
            cleanup_runs_counter.labels(status="failure").inc()
            await asyncio.sleep(3600)

