"""Redis client for session management"""
import redis
import os
import json
from typing import Optional

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Session TTL (30 days)
SESSION_TTL = 30 * 24 * 60 * 60


def set_session(session_id: str, user_id: int) -> None:
    """Store session in Redis"""
    key = f"session:{session_id}"
    redis_client.setex(key, SESSION_TTL, user_id)


def get_session(session_id: str) -> Optional[int]:
    """Get user_id from session"""
    key = f"session:{session_id}"
    user_id = redis_client.get(key)
    return int(user_id) if user_id else None


def delete_session(session_id: str) -> None:
    """Delete session from Redis"""
    key = f"session:{session_id}"
    redis_client.delete(key)


def set_csrf_token(session_id: str, token: str) -> None:
    """Store CSRF token in Redis"""
    key = f"csrf:{session_id}"
    redis_client.setex(key, SESSION_TTL, token)


def get_csrf_token(session_id: str) -> Optional[str]:
    """Get CSRF token from Redis"""
    key = f"csrf:{session_id}"
    return redis_client.get(key)


def set_upload_progress(user_id: int, video_id: int, progress: int) -> None:
    """Store upload progress in Redis"""
    key = f"progress:{user_id}:{video_id}"
    redis_client.setex(key, 3600, progress)  # 1 hour TTL


def get_upload_progress(user_id: int, video_id: int) -> Optional[int]:
    """Get upload progress from Redis"""
    key = f"progress:{user_id}:{video_id}"
    progress = redis_client.get(key)
    return int(progress) if progress else None


def delete_upload_progress(user_id: int, video_id: int) -> None:
    """Delete upload progress from Redis"""
    key = f"progress:{user_id}:{video_id}"
    redis_client.delete(key)


def increment_rate_limit(identifier: str, window: int) -> int:
    """Increment rate limit counter and return current count"""
    key = f"ratelimit:{identifier}"
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    results = pipe.execute()
    return results[0]


def get_rate_limit_count(identifier: str) -> int:
    """Get current rate limit count"""
    key = f"ratelimit:{identifier}"
    count = redis_client.get(key)
    return int(count) if count else 0

