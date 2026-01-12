"""Background worker for processing upload tasks from Redis queue

Processes tasks with unlimited concurrency - spawns async tasks for each
queued item without blocking the main polling loop.
"""
import asyncio
import logging
from typing import Dict, Any

from app.db.session import SessionLocal
from app.db.task_queue import (
    dequeue_task, mark_task_processing, mark_task_completed,
    mark_task_failed, cleanup_stale_tasks
)
from app.services.video.orchestrator import upload_all_pending_videos

logger = logging.getLogger(__name__)
upload_logger = logging.getLogger("upload")


async def process_upload_task(task_data: Dict[str, Any]) -> None:
    """Process a single upload task (runs concurrently with other tasks)
    
    Args:
        task_data: Task data from queue
    """
    task_id = task_data.get("task_id")
    task_type = task_data.get("task_type")
    payload = task_data.get("payload", {})
    user_id = payload.get("user_id")
    
    if not user_id:
        logger.error(f"Task {task_id} missing user_id in payload")
        mark_task_failed(task_id, "Missing user_id in task payload", retry=False)
        return
    
    # Mark task as processing
    mark_task_processing(task_id)
    
    # Create DB session for this task
    db = SessionLocal()
    if db is None:
        error_msg = "Failed to create database session"
        logger.error(f"Task {task_id}: {error_msg}")
        mark_task_failed(task_id, error_msg, retry=True)
        return
    
    try:
        logger.info(f"Processing upload task {task_id} for user {user_id}")
        
        # Process the upload
        result = await upload_all_pending_videos(user_id, db)
        
        # Mark task as completed
        mark_task_completed(task_id, result)
        logger.info(
            f"Completed upload task {task_id} for user {user_id}: "
            f"{result.get('videos_uploaded', 0)} uploaded, "
            f"{result.get('videos_failed', 0)} failed"
        )
        
    except ValueError as e:
        # Validation errors - don't retry
        error_msg = str(e)
        logger.warning(f"Task {task_id} validation error: {error_msg}")
        mark_task_failed(task_id, error_msg, retry=False)
        
    except Exception as e:
        # Other errors - retry with exponential backoff
        error_msg = str(e)
        logger.error(f"Task {task_id} failed: {error_msg}", exc_info=True)
        mark_task_failed(task_id, error_msg, retry=True)
        
    finally:
        # Always close DB session
        try:
            db.close()
        except Exception as e:
            logger.warning(f"Error closing DB session for task {task_id}: {e}")


async def upload_worker_task() -> None:
    """Main worker loop that polls queue and processes tasks with unlimited concurrency
    
    Continuously polls the upload queue and spawns async tasks for processing.
    Each task processes independently, allowing unlimited concurrent uploads.
    """
    logger.info("Starting upload worker task")
    
    while True:
        try:
            # Clean up stale tasks every 10 minutes
            # (tasks that have been processing too long, likely from crashed workers)
            cleanup_stale_tasks(timeout_seconds=3600)
            
            # Dequeue task (blocking, 5 second timeout)
            task_data = await dequeue_task("upload_videos", timeout=5)
            
            if task_data is None:
                # Timeout - no tasks available, continue polling
                continue
            
            task_id = task_data.get("task_id")
            
            # Check if this is a retry task that needs delay (exponential backoff)
            # Get retry_after timestamp from metadata if it exists
            from app.db.task_queue import get_task_status
            task_meta = get_task_status(task_id)
            retry_after_str = task_meta.get("retry_after") if task_meta else None
            
            if retry_after_str:
                try:
                    from datetime import datetime, timezone
                    retry_after = datetime.fromisoformat(retry_after_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    
                    if retry_after > now:
                        # Need to wait before processing this retry
                        delay_seconds = (retry_after - now).total_seconds()
                        retry_count = task_data.get("retry_count", 0)
                        logger.info(
                            f"Task {task_id} is retry attempt {retry_count}, "
                            f"waiting {delay_seconds:.0f}s before processing (exponential backoff)"
                        )
                        await asyncio.sleep(delay_seconds)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing retry_after for task {task_id}: {e}")
            
            # Spawn async task to process (non-blocking - unlimited concurrency)
            asyncio.create_task(process_upload_task(task_data))
            
            # Continue immediately to next iteration (don't wait for task completion)
            
        except Exception as e:
            logger.error(f"Error in upload worker loop: {e}", exc_info=True)
            # Wait a bit before retrying to avoid tight error loops
            await asyncio.sleep(5)
