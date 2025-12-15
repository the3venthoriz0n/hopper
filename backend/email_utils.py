"""Email utilities (Resend integration)"""
import os
import logging
from typing import Optional

import resend

logger = logging.getLogger(__name__)

# Configure Resend API key from environment
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "no-reply@hopper.dunkbox.net")


def send_verification_email(email: str, code: str) -> bool:
    """
    Send an email verification code using Resend.

    Returns True on success, False on failure.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not set; skipping verification email")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        html = f"""
        <p>Welcome! Please confirm your email address.</p>
        <p>Your verification code is:</p>
        <p style="font-size: 20px; font-weight: bold;">{code}</p>
        <p>This code will expire in 10 minutes.</p>
        """

        resend.Emails.send(
            {
                "from": RESEND_FROM_EMAIL,
                "to": email,
                "subject": "Confirm your email address",
                "html": html,
            }
        )
        logger.info(f"Sent verification email to {email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send verification email to {email}: {exc}", exc_info=True)
        return False


