"""Encryption utilities for sensitive data like OAuth tokens"""
from cryptography.fernet import Fernet
import os
import base64
from typing import Optional

# Generate or load encryption key
# In production, this should be stored in environment variables
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    # Generate a key for development (this will be different each restart)
    # In production, you MUST set ENCRYPTION_KEY environment variable
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("WARNING: Using auto-generated encryption key. Set ENCRYPTION_KEY environment variable for production!")

# Ensure key is bytes
if isinstance(ENCRYPTION_KEY, str):
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()

cipher = Fernet(ENCRYPTION_KEY)


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
    except Exception:
        return None

