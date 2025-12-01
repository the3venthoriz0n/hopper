"""Redis client for session management"""
import redis
import os
import json
from typing import Optional, Dict

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
    """Increment rate limit counter and return current count.
    Uses Lua script to atomically increment and set TTL only for new keys (fixed window rate limiting)."""
    key = f"ratelimit:{identifier}"
    
    # Lua script: increment counter, set TTL if key is new (count == 1), return count
    lua_script = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return count
    """
    
    # Execute Lua script atomically
    count = redis_client.eval(lua_script, 1, key, window)
    return int(count)


def get_rate_limit_count(identifier: str) -> int:
    """Get current rate limit count"""
    key = f"ratelimit:{identifier}"
    count = redis_client.get(key)
    return int(count) if count else 0


# Cache TTLs
SETTINGS_CACHE_TTL = 5 * 60  # 5 minutes
OAUTH_TOKEN_CACHE_TTL = 60  # 1 minute


def get_cached_settings(user_id: int, category: str) -> Optional[Dict]:
    """Get cached user settings from Redis"""
    key = f"cache:settings:{user_id}:{category}"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_settings(user_id: int, category: str, settings: Dict) -> None:
    """Cache user settings in Redis"""
    key = f"cache:settings:{user_id}:{category}"
    redis_client.setex(key, SETTINGS_CACHE_TTL, json.dumps(settings))


def invalidate_settings_cache(user_id: int, category: Optional[str] = None) -> None:
    """Invalidate cached settings for a user (all categories or specific category)"""
    if category:
        # Invalidate specific category
        key = f"cache:settings:{user_id}:{category}"
        redis_client.delete(key)
        # Also invalidate all_settings cache
        all_key = f"cache:settings:{user_id}:all"
        redis_client.delete(all_key)
    else:
        # Invalidate all categories for this user
        pattern = f"cache:settings:{user_id}:*"
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)


def get_cached_oauth_token(user_id: int, platform: str) -> Optional[Dict]:
    """Get cached OAuth token from Redis"""
    key = f"cache:oauth:{user_id}:{platform}"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_oauth_token(user_id: int, platform: str, token_data: Dict) -> None:
    """Cache OAuth token in Redis (stores serialized token data)"""
    key = f"cache:oauth:{user_id}:{platform}"
    redis_client.setex(key, OAUTH_TOKEN_CACHE_TTL, json.dumps(token_data))


def get_cached_all_oauth_tokens(user_id: int) -> Optional[Dict]:
    """Get cached all OAuth tokens from Redis"""
    key = f"cache:oauth:{user_id}:all"
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_all_oauth_tokens(user_id: int, tokens: Dict) -> None:
    """Cache all OAuth tokens in Redis"""
    key = f"cache:oauth:{user_id}:all"
    redis_client.setex(key, OAUTH_TOKEN_CACHE_TTL, json.dumps(tokens))


def invalidate_oauth_token_cache(user_id: int, platform: Optional[str] = None) -> None:
    """Invalidate cached OAuth tokens for a user (all platforms or specific platform)"""
    if platform:
        # Invalidate specific platform
        key = f"cache:oauth:{user_id}:{platform}"
        redis_client.delete(key)
        # Also invalidate all_tokens cache
        all_key = f"cache:oauth:{user_id}:all"
        redis_client.delete(all_key)
    else:
        # Invalidate all platforms for this user
        pattern = f"cache:oauth:{user_id}:*"
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)

