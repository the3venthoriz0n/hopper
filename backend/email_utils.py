"""Email utilities (Resend integration)"""
import os
import logging
from typing import Optional
from urllib.parse import quote

import resend

logger = logging.getLogger(__name__)

# Configure Resend API key from environment
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "no-reply@hopper.dunkbox.net")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://hopper.dunkbox.net")


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


def send_password_reset_email(email: str, code: str) -> bool:
    """
    Send a password reset code using Resend, including a link to the reset page.

    Returns True on success, False on failure.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not set; skipping password reset email")
        return False

    try:
        resend.api_key = RESEND_API_KEY

        # Build link that will open the frontend login page in reset-password mode
        reset_link = f"{FRONTEND_URL}/login?reset_email={quote(email)}&reset_code={quote(code)}"

        html = f"""
        <p>You requested to reset your password.</p>
        <p>Your password reset code is:</p>
        <p style="font-size: 20px; font-weight: bold;">{code}</p>
        <p>You can also reset your password directly by clicking this link:</p>
        <p><a href="{reset_link}" target="_blank" rel="noopener noreferrer">Reset your password</a></p>
        <p>If you did not request this, you can safely ignore this email.</p>
        <p>This code will expire in 15 minutes.</p>
        """

        resend.Emails.send(
            {
                "from": RESEND_FROM_EMAIL,
                "to": email,
                "subject": "Reset your Hopper password",
                "html": html,
            }
        )
        logger.info(f"Sent password reset email to {email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send password reset email to {email}: {exc}", exc_info=True)
        return False

