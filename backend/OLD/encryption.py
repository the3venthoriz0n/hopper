"""Encryption utilities for sensitive data like OAuth tokens"""
from cryptography.fernet import Fernet
import os
import base64
from typing import Optional

# Load encryption key from environment variable
# Fernet keys must be 32 bytes, base64-encoded (URL-safe), resulting in 44 characters
# Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY_STR = os.getenv("ENCRYPTION_KEY")

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
    """Decrypt a string"""
    if not ciphertext:
        return None
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Decryption failed: {type(e).__name__}: {str(e)}")
        return None

