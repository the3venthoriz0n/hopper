"""Encryption utilities for sensitive data like OAuth tokens"""
from cryptography.fernet import Fernet
import base64
from typing import Optional
from app.core.config import settings

# Lazy initialization - cipher is created on first use
_cipher = None
_ENCRYPTION_KEY = None


def _get_cipher():
    """Get or create Fernet cipher instance (lazy initialization)
    
    Raises:
        ValueError: If ENCRYPTION_KEY is missing or invalid
    """
    global _cipher, _ENCRYPTION_KEY
    
    if _cipher is not None:
        return _cipher
    
    # Load encryption key from environment variable
    ENCRYPTION_KEY_STR = getattr(settings, 'ENCRYPTION_KEY', None)
    
    if not ENCRYPTION_KEY_STR:
        raise ValueError(
            "ENCRYPTION_KEY environment variable is required. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    
    # Convert string to bytes (Fernet expects bytes)
    if isinstance(ENCRYPTION_KEY_STR, bytes):
        _ENCRYPTION_KEY = ENCRYPTION_KEY_STR
    else:
        _ENCRYPTION_KEY = ENCRYPTION_KEY_STR.encode()
    
    # Validate the key format by creating a Fernet instance
    try:
        _cipher = Fernet(_ENCRYPTION_KEY)
    except ValueError as e:
        raise ValueError(
            f"Invalid ENCRYPTION_KEY format: {e}. "
            "The key must be 32 bytes, base64-encoded (URL-safe), resulting in 44 characters. "
            "Generate a new key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    
    return _cipher


def encrypt(plaintext: str) -> str:
    """Encrypt a string"""
    if not plaintext:
        return ""
    cipher = _get_cipher()
    return cipher.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> Optional[str]:
    """Decrypt a string
    
    Raises:
        ValueError: If decryption fails (invalid token, wrong key, corrupted data)
    """
    if not ciphertext:
        return None
    try:
        cipher = _get_cipher()
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception as e:
        # ROOT CAUSE FIX: Raise ValueError instead of returning None
        # This forces callers to handle decryption failures explicitly
        # and ensures db_helpers.py hits the except block to log warnings properly
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Decryption failed: {type(e).__name__}: {str(e)}")
        raise ValueError(f"Decryption failed: {type(e).__name__}: {str(e)}")

