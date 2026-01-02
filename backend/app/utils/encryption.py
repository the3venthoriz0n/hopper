"""Encryption utilities for sensitive data like OAuth tokens"""
from cryptography.fernet import Fernet
import base64
from typing import Optional
from app.core.config import settings

# Load encryption key from environment variable
ENCRYPTION_KEY_STR = getattr(settings, 'ENCRYPTION_KEY', None)

if not ENCRYPTION_KEY_STR:
    raise ValueError(
        "ENCRYPTION_KEY environment variable is required. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# Convert string to bytes (Fernet expects bytes)
if isinstance(ENCRYPTION_KEY_STR, bytes):
    ENCRYPTION_KEY = ENCRYPTION_KEY_STR
else:
    ENCRYPTION_KEY = ENCRYPTION_KEY_STR.encode()

# Validate the key format by creating a Fernet instance
try:
    cipher = Fernet(ENCRYPTION_KEY)
except ValueError as e:
    raise ValueError(
        f"Invalid ENCRYPTION_KEY format: {e}. "
        "The key must be 32 bytes, base64-encoded (URL-safe), resulting in 44 characters. "
        "Generate a new key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def encrypt(plaintext: str) -> str:
    """Encrypt a string"""
    if not plaintext:
        return ""
    return cipher.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> Optional[str]:
    """Decrypt a string
    
    Raises:
        ValueError: If decryption fails (invalid token, wrong key, corrupted data)
    """
    if not ciphertext:
        return None
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception as e:
        # ROOT CAUSE FIX: Raise ValueError instead of returning None
        # This forces callers to handle decryption failures explicitly
        # and ensures db_helpers.py hits the except block to log warnings properly
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Decryption failed: {type(e).__name__}: {str(e)}")
        raise ValueError(f"Decryption failed: {type(e).__name__}: {str(e)}")

