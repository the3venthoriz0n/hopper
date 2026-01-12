"""Redis-based task queue for background job processing

DRY, reusable task queue implementation using Redis Lists and Hashes.
Supports unlimited concurrency, automatic retries, and task persistence.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db.redis import get_redis_client, get_async_redis_client

logger = logging.getLogger(__name__)

# Redis key prefixes
QUEUE_KEY_PREFIX = "task:queue:"
META_KEY_PREFIX = "task:meta:"
PROCESSING_SET_KEY = "task:processing"

# Task TTL (24 hours for completed/failed tasks metadata)
TASK_META_TTL = 24 * 60 * 60


def enqueue_task(
    task_type: str,
    payload: Dict[str, Any],
    retry_count: int = 0,
    max_retries: int = 3
) -> str:
    """Enqueue a task to the Redis queue
    
    Args:
        task_type: Type of task (e.g., 'upload_videos')
        payload: Task payload (must include 'user_id' for upload tasks)
        retry_count: Current retry attempt (0 for new tasks)
        max_retries: Maximum number of automatic retries
        
    Returns:
        task_id: Unique task identifier
    """
    task_id = str(uuid.uuid4())
    
    task_data = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": payload,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending"
    }
    
    # Store task metadata in Redis hash
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    client.hset(meta_key, mapping={
        "task_id": task_id,
        "task_type": task_type,
        "payload": json.dumps(payload),
        "retry_count": str(retry_count),
        "max_retries": str(max_retries),
        "created_at": task_data["created_at"],
        "status": "pending"
    })
    client.expire(meta_key, TASK_META_TTL)
    
    # Enqueue task to appropriate queue
    queue_key = f"{QUEUE_KEY_PREFIX}{task_type}"
    task_json = json.dumps(task_data)
    client.lpush(queue_key, task_json)
    
    logger.info(f"Enqueued task {task_id} of type {task_type} (retry_count={retry_count})")
    return task_id


async def dequeue_task(task_type: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
    """Dequeue a task from the Redis queue (blocking)
    
    Args:
        task_type: Type of task to dequeue
        timeout: Blocking timeout in seconds
        
    Returns:
        Task dict if task available, None if timeout
    """
    queue_key = f"{QUEUE_KEY_PREFIX}{task_type}"
    client = get_async_redis_client()
    
    if client is None:
        logger.error("Async Redis client not available")
        return None
    
    try:
        # BRPOP returns [queue_name, task_json] or None
        result = await client.brpop(queue_key, timeout=timeout)
        
        if result is None:
            return None
        
        _, task_json = result
        task_data = json.loads(task_json)
        return task_data
    except Exception as e:
        logger.error(f"Error dequeuing task: {e}", exc_info=True)
        return None


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """Get task status and metadata
    
    Args:
        task_id: Task identifier
        
    Returns:
        Task metadata dict or None if not found
    """
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    
    meta = client.hgetall(meta_key)
    if not meta:
        return None
    
    # Parse JSON fields
    if "payload" in meta:
        meta["payload"] = json.loads(meta["payload"])
    
    # Convert numeric fields
    if "retry_count" in meta:
        meta["retry_count"] = int(meta["retry_count"])
    if "max_retries" in meta:
        meta["max_retries"] = int(meta["max_retries"])
    
    return meta


def mark_task_processing(task_id: str) -> None:
    """Mark task as processing
    
    Args:
        task_id: Task identifier
    """
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    
    client.hset(meta_key, "status", "processing")
    client.hset(meta_key, "started_at", datetime.now(timezone.utc).isoformat())
    client.sadd(PROCESSING_SET_KEY, task_id)
    
    logger.debug(f"Marked task {task_id} as processing")


def mark_task_completed(task_id: str, result: Optional[Dict[str, Any]] = None) -> None:
    """Mark task as completed
    
    Args:
        task_id: Task identifier
        result: Optional result data to store
    """
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    
    client.hset(meta_key, "status", "completed")
    client.hset(meta_key, "completed_at", datetime.now(timezone.utc).isoformat())
    
    if result:
        client.hset(meta_key, "result", json.dumps(result))
    
    client.srem(PROCESSING_SET_KEY, task_id)
    
    logger.info(f"Marked task {task_id} as completed")


def mark_task_failed(task_id: str, error: str, retry: bool = True) -> Optional[str]:
    """Mark task as failed and optionally schedule retry
    
    Args:
        task_id: Task identifier
        error: Error message
        retry: Whether to schedule automatic retry
        
    Returns:
        New task_id if retry scheduled, None otherwise
    """
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    
    meta = client.hgetall(meta_key)
    if not meta:
        logger.warning(f"Task {task_id} metadata not found")
        return None
    
    retry_count = int(meta.get("retry_count", "0"))
    max_retries = int(meta.get("max_retries", "3"))
    task_type = meta.get("task_type")
    payload_json = meta.get("payload")
    
    if not payload_json:
        logger.error(f"Task {task_id} missing payload")
        return None
    
    payload = json.loads(payload_json)
    
    # Check if we should retry
    if retry and retry_count < max_retries:
        # Schedule retry with exponential backoff
        new_retry_count = retry_count + 1
        delay_seconds = min(300, 2 ** new_retry_count)  # Max 5 minutes
        
        logger.info(
            f"Task {task_id} failed (attempt {retry_count + 1}/{max_retries + 1}), "
            f"scheduling retry in {delay_seconds}s: {error}"
        )
        
        # Store retry info
        client.hset(meta_key, "status", "retrying")
        client.hset(meta_key, "error", error)
        client.hset(meta_key, "retry_scheduled_at", datetime.now(timezone.utc).isoformat())
        client.hset(meta_key, "retry_delay_seconds", str(delay_seconds))
        client.srem(PROCESSING_SET_KEY, task_id)
        
        # Calculate when retry should be processed (exponential backoff)
        from datetime import timedelta
        retry_after = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        
        # Store retry_after timestamp in metadata for the new task
        # Enqueue retry task immediately (worker will check retry_after before processing)
        new_task_id = enqueue_task(
            task_type=task_type,
            payload=payload,
            retry_count=new_retry_count,
            max_retries=max_retries
        )
        
        # Store retry_after timestamp in new task's metadata
        new_meta_key = f"{META_KEY_PREFIX}{new_task_id}"
        client.hset(new_meta_key, "retry_after", retry_after.isoformat())
        
        return new_task_id
    else:
        # Max retries exceeded, mark as failed
        client.hset(meta_key, "status", "failed")
        client.hset(meta_key, "error", error)
        client.hset(meta_key, "failed_at", datetime.now(timezone.utc).isoformat())
        client.srem(PROCESSING_SET_KEY, task_id)
        
        logger.warning(
            f"Task {task_id} failed permanently after {retry_count + 1} attempts: {error}"
        )
        return None


def retry_task(task_id: str) -> Optional[str]:
    """Manually retry a failed task
    
    Args:
        task_id: Task identifier
        
    Returns:
        New task_id if retry scheduled, None if task not found
    """
    meta_key = f"{META_KEY_PREFIX}{task_id}"
    client = get_redis_client()
    
    meta = client.hgetall(meta_key)
    if not meta:
        logger.warning(f"Task {task_id} not found for retry")
        return None
    
    task_type = meta.get("task_type")
    payload_json = meta.get("payload")
    
    if not payload_json:
        logger.error(f"Task {task_id} missing payload")
        return None
    
    payload = json.loads(payload_json)
    
    # Create new task with retry_count reset to 0 (fresh attempt)
    new_task_id = enqueue_task(
        task_type=task_type,
        payload=payload,
        retry_count=0,
        max_retries=int(meta.get("max_retries", "3"))
    )
    
    logger.info(f"Manually retrying task {task_id} as new task {new_task_id}")
    return new_task_id


def get_processing_tasks() -> list[str]:
    """Get list of currently processing task IDs
    
    Returns:
        List of task IDs currently being processed
    """
    client = get_redis_client()
    return list(client.smembers(PROCESSING_SET_KEY))


def cleanup_stale_tasks(timeout_seconds: int = 3600) -> int:
    """Clean up tasks that have been in processing state too long (likely crashed)
    
    Args:
        timeout_seconds: Time in seconds after which a processing task is considered stale
        
    Returns:
        Number of tasks cleaned up
    """
    client = get_redis_client()
    processing_tasks = get_processing_tasks()
    cleaned = 0
    
    for task_id in processing_tasks:
        meta_key = f"{META_KEY_PREFIX}{task_id}"
        started_at_str = client.hget(meta_key, "started_at")
        
        if started_at_str:
            try:
                started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                
                if elapsed > timeout_seconds:
                    # Task has been processing too long, likely crashed
                    logger.warning(
                        f"Cleaning up stale task {task_id} "
                        f"(processing for {elapsed:.0f}s, timeout={timeout_seconds}s)"
                    )
                    client.srem(PROCESSING_SET_KEY, task_id)
                    client.hset(meta_key, "status", "failed")
                    client.hset(meta_key, "error", f"Task timeout after {elapsed:.0f} seconds")
                    cleaned += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Error parsing started_at for task {task_id}: {e}")
                # Remove from processing set if we can't parse the time
                client.srem(PROCESSING_SET_KEY, task_id)
                cleaned += 1
    
    return cleaned
