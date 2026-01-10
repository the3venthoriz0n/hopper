"""Redis client for session management and caching"""
import redis
import redis.asyncio as aioredis
import json
import logging
from typing import Optional, Dict
from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy initialization - no connection at import time
_client = None
_async_client = None

def get_redis_client():
    """Get or create Redis client (lazy initialization)
    
    This prevents connection attempts during import, allowing mocks to be applied first.
    """
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client

def get_async_redis_client():
    """Get or create async Redis client (lazy initialization)
    
    Automatically recreates the client if it's tied to a different event loop,
    which can happen when tests create new event loops.
    """
    global _async_client
    import asyncio
    
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop is running (shouldn't happen during a test call)
        # Return None to prevent creating a client without a loop
        return None

    # If client exists, check if its internal loop matches the current running loop
    if _async_client is not None:
        # Look deep into the connection pool's loop reference
        client_loop = getattr(_async_client.connection_pool, '_loop', None)
        if client_loop is not current_loop:
            # Loop mismatch detected! Clear the stale client.
            _async_client = None

    if _async_client is None:
        _async_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20
        )
        # Explicitly set the loop on the connection pool for clarity
        _async_client.connection_pool._loop = current_loop
        
    return _async_client

# For backward compatibility - these variables are deprecated
# Use get_redis_client() and get_async_redis_client() instead
# Setting to None prevents import-time connections - they'll be created on first use via getters
redis_client = None
async_redis_client = None

# Session TTL (30 days)
SESSION_TTL = 30 * 24 * 60 * 60

# Activity tracking TTL (1 hour - users active within last hour)
ACTIVITY_TTL = 60 * 60

# Rate limiting configuration
# In development, use more lenient limits
if settings.ENVIRONMENT == "development":
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_REQUESTS = 1000  # requests per window (very lenient for dev)
    RATE_LIMIT_STRICT_WINDOW = 60  # seconds
    RATE_LIMIT_STRICT_REQUESTS = 1000  # requests per window for state-changing operations (very lenient for dev)
else:
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_REQUESTS = 1000  # requests per window (matching dev)
    RATE_LIMIT_STRICT_WINDOW = 60  # seconds
    RATE_LIMIT_STRICT_REQUESTS = 1000  # requests per window for state-changing operations (matching dev)

# Cache TTLs
SETTINGS_CACHE_TTL = 5 * 60  # 5 minutes
OAUTH_TOKEN_CACHE_TTL = 60  # 1 minute
EMAIL_VERIFICATION_TTL = 10 * 60  # 10 minutes
PENDING_REGISTRATION_TTL = 30 * 60  # 30 minutes for pending sign-ups
PASSWORD_RESET_TTL = 15 * 60  # 15 minutes for password reset codes


def set_session(session_id: str, user_id: int) -> None:
    """Store session in Redis"""
    key = f"session:{session_id}"
    get_redis_client().setex(key, SESSION_TTL, user_id)


def get_session(session_id: str) -> Optional[int]:
    """Get user_id from session"""
    key = f"session:{session_id}"
    user_id = get_redis_client().get(key)
    return int(user_id) if user_id else None


async def async_get_session(session_id: str) -> Optional[int]:
    """Get user_id from session (async)"""
    key = f"session:{session_id}"
    user_id = await get_async_redis_client().get(key)
    return int(user_id) if user_id else None


def delete_session(session_id: str) -> None:
    """Delete session from Redis"""
    key = f"session:{session_id}"
    get_redis_client().delete(key)


def set_csrf_token(session_id: str, token: str) -> None:
    """Store CSRF token in Redis"""
    key = f"csrf:{session_id}"
    get_redis_client().setex(key, SESSION_TTL, token)


def get_csrf_token(session_id: str) -> Optional[str]:
    """Get CSRF token from Redis"""
    key = f"csrf:{session_id}"
    return get_redis_client().get(key)


def get_or_create_csrf_token(session_id: str) -> str:
    """Get existing CSRF token or create new one if it doesn't exist
    
    Args:
        session_id: Session ID
        
    Returns:
        str: CSRF token
    """
    import secrets
    
    # Check Redis for existing token
    csrf_token = get_csrf_token(session_id)
    
    # If no token in Redis, create one
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        set_csrf_token(session_id, csrf_token)
    
    return csrf_token


def set_upload_progress(user_id: int, video_id: int, progress: int) -> None:
    """Store upload progress in Redis"""
    key = f"progress:{user_id}:{video_id}"
    get_redis_client().setex(key, 3600, progress)  # 1 hour TTL


def get_upload_progress(user_id: int, video_id: int) -> Optional[int]:
    """Get upload progress from Redis"""
    key = f"progress:{user_id}:{video_id}"
    progress = get_redis_client().get(key)
    return int(progress) if progress else None


def delete_upload_progress(user_id: int, video_id: int) -> None:
    """Delete upload progress from Redis"""
    key = f"progress:{user_id}:{video_id}"
    get_redis_client().delete(key)


def set_active_upload_session(video_id: int, platform: str) -> None:
    """Mark that an upload session is actively processing a video"""
    key = f"upload_active:{video_id}:{platform}"
    get_redis_client().setex(key, 3600, "1")  # 1 hour TTL


def is_upload_active(video_id: int, platform: str) -> bool:
    """Check if an upload session is actively processing a video"""
    key = f"upload_active:{video_id}:{platform}"
    return get_redis_client().exists(key) > 0


def clear_active_upload_session(video_id: int, platform: str) -> None:
    """Clear the active upload session flag"""
    key = f"upload_active:{video_id}:{platform}"
    get_redis_client().delete(key)


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
    count = get_redis_client().eval(lua_script, 1, key, window)
    return int(count)


def check_rate_limit(identifier: str, strict: bool = False) -> bool:
    """Check if request is within rate limit using Redis. Returns True if allowed, False if rate limited."""
    window = RATE_LIMIT_STRICT_WINDOW if strict else RATE_LIMIT_WINDOW
    max_requests = RATE_LIMIT_STRICT_REQUESTS if strict else RATE_LIMIT_REQUESTS
    
    # Increment counter in Redis (with TTL)
    current_count = increment_rate_limit(identifier, window)
    
    # Check if limit exceeded
    if current_count > max_requests:
        return False
    
    return True


def get_rate_limit_count(identifier: str) -> int:
    """Get current rate limit count"""
    key = f"ratelimit:{identifier}"
    count = get_redis_client().get(key)
    return int(count) if count else 0


def get_cached_settings(user_id: int, category: str) -> Optional[Dict]:
    """Get cached user settings from Redis"""
    key = f"cache:settings:{user_id}:{category}"
    cached = get_redis_client().get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_settings(user_id: int, category: str, settings: Dict) -> None:
    """Cache user settings in Redis"""
    key = f"cache:settings:{user_id}:{category}"
    get_redis_client().setex(key, SETTINGS_CACHE_TTL, json.dumps(settings))


def invalidate_settings_cache(user_id: int, category: Optional[str] = None) -> None:
    """Invalidate cached settings for a user (all categories or specific category)
    
    Gracefully handles Redis failures - cache invalidation should not break user operations.
    """
    try:
        client = get_redis_client()
        if category:
            # Invalidate specific category
            key = f"cache:settings:{user_id}:{category}"
            client.delete(key)
            # Also invalidate all_settings cache
            all_key = f"cache:settings:{user_id}:all"
            client.delete(all_key)
        else:
            # Invalidate all categories for this user
            pattern = f"cache:settings:{user_id}:*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)
    except Exception as e:
        # Log but don't fail - cache invalidation is best-effort
        logger.warning(f"Failed to invalidate settings cache for user {user_id}: {e}")
        # In test mode, this is expected if Redis isn't available
        if settings.ENVIRONMENT.lower() != "test":
            # In production, log but continue - don't break user operations
            pass


def get_cached_oauth_token(user_id: int, platform: str) -> Optional[Dict]:
    """Get cached OAuth token from Redis"""
    key = f"cache:oauth:{user_id}:{platform}"
    cached = get_redis_client().get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_oauth_token(user_id: int, platform: str, token_data: Dict) -> None:
    """Cache OAuth token in Redis (stores serialized token data)"""
    key = f"cache:oauth:{user_id}:{platform}"
    get_redis_client().setex(key, OAUTH_TOKEN_CACHE_TTL, json.dumps(token_data))


def get_cached_all_oauth_tokens(user_id: int) -> Optional[Dict]:
    """Get cached all OAuth tokens from Redis"""
    key = f"cache:oauth:{user_id}:all"
    cached = get_redis_client().get(key)
    if cached:
        return json.loads(cached)
    return None


def set_cached_all_oauth_tokens(user_id: int, tokens: Dict) -> None:
    """Cache all OAuth tokens in Redis"""
    key = f"cache:oauth:{user_id}:all"
    get_redis_client().setex(key, OAUTH_TOKEN_CACHE_TTL, json.dumps(tokens))


def invalidate_oauth_token_cache(user_id: int, platform: Optional[str] = None) -> None:
    """Invalidate cached OAuth tokens for a user (all platforms or specific platform)
    
    Gracefully handles Redis failures - cache invalidation should not break user operations.
    """
    try:
        client = get_redis_client()
        if platform:
            # Invalidate specific platform
            key = f"cache:oauth:{user_id}:{platform}"
            client.delete(key)
            # Also invalidate all_tokens cache
            all_key = f"cache:oauth:{user_id}:all"
            client.delete(all_key)
        else:
            # Invalidate all platforms for this user
            pattern = f"cache:oauth:{user_id}:*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)
    except Exception as e:
        # Log but don't fail - cache invalidation is best-effort
        logger.warning(f"Failed to invalidate OAuth token cache for user {user_id}: {e}")
        if settings.ENVIRONMENT.lower() != "test":
            pass


def delete_all_user_sessions(user_id: int) -> int:
    """Delete all sessions for a user by scanning session keys.
    
    This scans all session:* keys and deletes those that match the user_id.
    Also deletes associated CSRF tokens.
    
    Args:
        user_id: User ID to delete sessions for
        
    Returns:
        Number of sessions deleted
    """
    try:
        client = get_redis_client()
        deleted_count = 0
        
        # Scan all session keys
        session_keys = client.keys("session:*")
        for key in session_keys:
            try:
                # Get the user_id stored in this session
                stored_user_id = client.get(key)
                if stored_user_id and int(stored_user_id) == user_id:
                    # Extract session_id from key format "session:{session_id}"
                    session_id = key.split(":", 1)[1]
                    
                    # Delete the session
                    client.delete(key)
                    deleted_count += 1
                    
                    # Also delete associated CSRF token
                    csrf_key = f"csrf:{session_id}"
                    client.delete(csrf_key)
            except (ValueError, IndexError, TypeError):
                # Skip invalid keys or conversion errors
                continue
        
        return deleted_count
    except Exception as e:
        # Log but don't fail - session deletion is best-effort
        logger.warning(f"Failed to delete all sessions for user {user_id}: {e}")
        return 0


def invalidate_all_user_caches(user_id: int) -> int:
    """Invalidate all cached data and sessions for a user
    
    This is used during account deletion to clean up all Redis data.
    Deletes: settings cache, OAuth token cache, upload progress, sessions, CSRF tokens.
    
    Args:
        user_id: User ID to invalidate caches for
        
    Returns:
        Total number of keys deleted
    """
    try:
        client = get_redis_client()
        deleted_count = 0
        
        # Invalidate settings cache
        pattern = f"cache:settings:{user_id}:*"
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
            deleted_count += len(keys)
        
        # Invalidate OAuth token cache
        pattern = f"cache:oauth:{user_id}:*"
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
            deleted_count += len(keys)
        
        # Invalidate upload progress
        pattern = f"progress:{user_id}:*"
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
            deleted_count += len(keys)
        
        # Delete all sessions for this user
        sessions_deleted = delete_all_user_sessions(user_id)
        deleted_count += sessions_deleted
        
        return deleted_count
    except Exception as e:
        # Log but don't fail - cache invalidation is best-effort
        logger.warning(f"Failed to invalidate all caches for user {user_id}: {e}")
        return 0


def set_email_verification_code(email: str, code: str) -> None:
    """Store email verification code in Redis with a short TTL."""
    key = f"email_verification:{email}"
    get_redis_client().setex(key, EMAIL_VERIFICATION_TTL, code)


def get_email_verification_code(email: str) -> Optional[str]:
    """Retrieve stored email verification code for an email."""
    key = f"email_verification:{email}"
    return get_redis_client().get(key)


def delete_email_verification_code(email: str) -> None:
    """Delete email verification code for an email."""
    key = f"email_verification:{email}"
    get_redis_client().delete(key)


def set_pending_registration(email: str, password_hash: str) -> None:
    """Store pending registration data (hashed password) for an email."""
    key = f"pending_registration:{email}"
    data = {"password_hash": password_hash}
    get_redis_client().setex(key, PENDING_REGISTRATION_TTL, json.dumps(data))


def get_pending_registration(email: str) -> Optional[Dict]:
    """Get pending registration data for an email."""
    key = f"pending_registration:{email}"
    raw = get_redis_client().get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def delete_pending_registration(email: str) -> None:
    """Delete pending registration data for an email."""
    key = f"pending_registration:{email}"
    get_redis_client().delete(key)


def set_password_reset_token(token: str, email: str) -> None:
    """Store password reset token with associated email."""
    key = f"password_reset_token:{token}"
    get_redis_client().setex(key, PASSWORD_RESET_TTL, email)


def get_password_reset_email(token: str) -> Optional[str]:
    """Retrieve email associated with a password reset token."""
    key = f"password_reset_token:{token}"
    return get_redis_client().get(key)


def delete_password_reset_token(token: str) -> None:
    """Delete password reset token."""
    key = f"password_reset_token:{token}"
    get_redis_client().delete(key)


def set_user_activity(user_id: int) -> None:
    """Track user activity - sets a heartbeat key with TTL and timestamp.
    
    This is used to track users who are currently active (using the site).
    The key automatically expires after ACTIVITY_TTL, so only recent activity is counted.
    Stores timestamp so we can show actual last login time.
    
    Args:
        user_id: User ID to track activity for
    """
    from datetime import datetime, timezone
    key = f"activity:{user_id}"
    # Store timestamp as JSON so we can retrieve it later
    timestamp = datetime.now(timezone.utc).isoformat()
    data = {"timestamp": timestamp}
    get_redis_client().setex(key, ACTIVITY_TTL, json.dumps(data))


async def async_set_user_activity(user_id: int) -> None:
    """Track user activity - sets a heartbeat key with TTL and timestamp (async)
    
    This is used to track users who are currently active (using the site).
    The key automatically expires after ACTIVITY_TTL, so only recent activity is counted.
    Stores timestamp so we can show actual last login time.
    
    Args:
        user_id: User ID to track activity for
    """
    from datetime import datetime, timezone
    key = f"activity:{user_id}"
    # Store timestamp as JSON so we can retrieve it later
    timestamp = datetime.now(timezone.utc).isoformat()
    data = {"timestamp": timestamp}
    await get_async_redis_client().setex(key, ACTIVITY_TTL, json.dumps(data))


def get_active_user_ids() -> set[int]:
    """Get set of user IDs who have been active within the last hour.
    
    Returns:
        Set of user IDs with recent activity
    """
    activity_keys = get_redis_client().keys("activity:*")
    active_user_ids = set()
    
    for key in activity_keys:
        # Extract user_id from key format "activity:{user_id}"
        try:
            user_id_str = key.split(":", 1)[1]
            user_id = int(user_id_str)
            active_user_ids.add(user_id)
        except (ValueError, IndexError):
            # Skip invalid keys
            continue
    
    return active_user_ids


def get_active_users_with_timestamps() -> Dict[int, str]:
    """Get active user IDs with their last activity timestamps.
    
    Returns:
        Dictionary mapping user_id to ISO timestamp string
    """
    activity_keys = get_redis_client().keys("activity:*")
    active_users = {}
    
    for key in activity_keys:
        try:
            # Extract user_id from key format "activity:{user_id}"
            user_id_str = key.split(":", 1)[1]
            user_id = int(user_id_str)
            
            # Get the stored data (should be JSON with timestamp)
            data_str = get_redis_client().get(key)
            if data_str:
                try:
                    data = json.loads(data_str)
                    # Check if data is a dict (new format) or just an int/string (old format)
                    if isinstance(data, dict):
                        timestamp = data.get("timestamp")
                        if timestamp:
                            active_users[user_id] = timestamp
                        else:
                            # Fallback: if no timestamp in dict, use current time
                            from datetime import datetime, timezone
                            active_users[user_id] = datetime.now(timezone.utc).isoformat()
                    else:
                        # Old format (just "1" or integer) - use current time as fallback
                        from datetime import datetime, timezone
                        active_users[user_id] = datetime.now(timezone.utc).isoformat()
                except (json.JSONDecodeError, TypeError, AttributeError):
                    # Old format or invalid JSON - use current time as fallback
                    from datetime import datetime, timezone
                    active_users[user_id] = datetime.now(timezone.utc).isoformat()
            else:
                # Key exists but no value - shouldn't happen, but handle gracefully
                from datetime import datetime, timezone
                active_users[user_id] = datetime.now(timezone.utc).isoformat()
        except (ValueError, IndexError):
            # Skip invalid keys
            continue
    
    return active_users


def acquire_lock(lock_key: str, timeout: int = 30) -> bool:
    """Acquire a distributed lock using Redis SET with NX and EX.
    
    Args:
        lock_key: The lock key to acquire
        timeout: Lock timeout in seconds (default 30)
        
    Returns:
        True if lock was acquired, False if lock already exists
    """
    # SET key value NX EX timeout - atomically set if not exists with expiration
    result = get_redis_client().set(lock_key, "1", nx=True, ex=timeout)
    return result is True


def release_lock(lock_key: str) -> None:
    """Release a distributed lock by deleting the key.
    
    Args:
        lock_key: The lock key to release
    """
    get_redis_client().delete(lock_key)


def set_token_check_cooldown(user_id: int, platform: str, ttl: int = 30) -> None:
    """Set a cooldown flag to prevent multiple token expiration checks within a time window.
    
    This prevents the "thundering herd" problem where multiple requests simultaneously
    check token expiration and trigger refresh cycles.
    
    Args:
        user_id: User ID
        platform: Platform name (e.g., "tiktok")
        ttl: Time-to-live in seconds (default 30)
    """
    key = f"token_check_cooldown:{user_id}:{platform}"
    get_redis_client().setex(key, ttl, "1")


def get_token_check_cooldown(user_id: int, platform: str) -> bool:
    """Check if token expiration check is in cooldown period.
    
    Args:
        user_id: User ID
        platform: Platform name (e.g., "tiktok")
        
    Returns:
        True if in cooldown (should skip expiration check), False otherwise
    """
    key = f"token_check_cooldown:{user_id}:{platform}"
    return get_redis_client().get(key) is not None

