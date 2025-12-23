"""Video file access token utilities for TikTok PULL_FROM_URL

Provides secure, time-limited token generation and verification for video file access.
Uses HMAC-SHA256 signing to prevent tampering.
"""
import base64
import hmac
import hashlib
import time
from urllib.parse import quote, unquote

from app.core.config import settings


def generate_video_access_token(video_id: int, user_id: int, expires_in_hours: int = 1) -> str:
    """Generate a time-limited signed token for video file access
    
    Uses HMAC-SHA256 to create a tamper-proof token that includes:
    - video_id: Ensures token only works for specific video
    - user_id: Ensures token only works for video owner
    - expiry_timestamp: Token expires after specified hours
    - HMAC signature: Prevents tampering
    
    Args:
        video_id: Video ID
        user_id: User ID (for additional security)
        expires_in_hours: Token validity period in hours (default 1 hour)
    
    Returns:
        URL-safe base64-encoded signed token
    
    Raises:
        ValueError: If ENCRYPTION_KEY environment variable is not set
    """
    expiry_timestamp = int(time.time()) + (expires_in_hours * 3600)
    # Create message: video_id:user_id:expiry_timestamp
    message = f"{video_id}:{user_id}:{expiry_timestamp}"
    
    # Sign with HMAC using ENCRYPTION_KEY as secret
    # Fernet keys are base64-encoded 32-byte keys, decode to get raw bytes for HMAC
    encryption_key_str = settings.ENCRYPTION_KEY
    if not encryption_key_str:
        raise ValueError("ENCRYPTION_KEY environment variable is required")
    # Decode base64-encoded Fernet key to get raw 32 bytes
    secret = base64.urlsafe_b64decode(encryption_key_str.encode())
    signature = hmac.new(secret, message.encode(), hashlib.sha256).digest()
    
    # Combine message and signature, then base64 encode
    token_data = f"{message}:{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    return quote(token_data)  # URL-encode for safe use in URLs


def verify_video_access_token(token: str, video_id: int, user_id: int) -> bool:
    """Verify a video access token
    
    Args:
        token: The token to verify (URL-encoded)
        video_id: Expected video ID
        user_id: Expected user ID
    
    Returns:
        True if token is valid and not expired, False otherwise
    """
    try:
        token_data = unquote(token)
        parts = token_data.split(':')
        if len(parts) != 4:
            return False
        
        token_video_id, token_user_id, expiry_timestamp, signature_b64 = parts
        
        # Verify video_id and user_id match
        if int(token_video_id) != video_id or int(token_user_id) != user_id:
            return False
        
        # Check expiry
        if int(expiry_timestamp) < int(time.time()):
            return False
        
        # Reconstruct message and verify signature
        message = f"{token_video_id}:{token_user_id}:{expiry_timestamp}"
        # Get the original base64-encoded string from env and decode to raw bytes
        encryption_key_str = settings.ENCRYPTION_KEY
        if not encryption_key_str:
            return False
        # Decode base64-encoded Fernet key to get raw 32 bytes
        secret = base64.urlsafe_b64decode(encryption_key_str.encode())
        expected_signature = hmac.new(secret, message.encode(), hashlib.sha256).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).decode().rstrip('=')
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature_b64, expected_signature_b64)
    except (ValueError, IndexError, TypeError):
        return False

