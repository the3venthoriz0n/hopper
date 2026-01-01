"""Email service - SMTP/Transactional email logic"""
import logging
import hmac
import hashlib
import base64
import json
from typing import Optional, Dict, Any
from urllib.parse import quote
from datetime import datetime, timezone
import resend
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.email_event import EmailEvent

logger = logging.getLogger(__name__)

# Resend test email addresses for safe testing
# See: https://resend.com/docs/dashboard/emails/send-test-emails
RESEND_TEST_DELIVERED = "delivered@resend.dev"
RESEND_TEST_BOUNCED = "bounced@resend.dev"
RESEND_TEST_COMPLAINED = "complained@resend.dev"


def get_test_email(base: str, label: str) -> str:
    """Create labeled test email: base+label@resend.dev
    
    Args:
        base: Base email name (e.g., 'delivered', 'bounced', 'complained')
        label: Label to add after + symbol for tracking
        
    Returns:
        Labeled test email address
        
    Example:
        get_test_email('delivered', 'test1') -> 'delivered+test1@resend.dev'
    """
    if base.endswith("@resend.dev"):
        base = base.replace("@resend.dev", "")
    return f"{base}+{label}@resend.dev"


def validate_email_config() -> tuple[bool, str]:
    """
    Validate email service configuration.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not settings.RESEND_API_KEY:
        return False, "RESEND_API_KEY is not set in environment variables"
    
    if not settings.FRONTEND_URL:
        return False, "FRONTEND_URL is not set in environment variables"
    
    return True, ""


def _send_email(to: str, subject: str, html: str) -> bool:
    """
    Internal helper function to send email via Resend API.
    
    Args:
        to: Recipient email address
        subject: Email subject
        html: HTML email content
        
    Returns:
        bool: True on success, False on failure
    """
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not set; skipping email")
        return False
    
    try:
        resend.api_key = settings.RESEND_API_KEY
        
        response = resend.Emails.send(
            {
                "from": getattr(settings, "RESEND_FROM_EMAIL", "no-reply@hopper.dunkbox.net"),
                "to": to,
                "subject": subject,
                "html": html,
            }
        )
        
        # Check response for success - Resend returns dict with 'id' field on success
        # Handle both dict and object responses
        email_id = None
        if isinstance(response, dict):
            email_id = response.get('id')
        elif hasattr(response, 'id'):
            email_id = response.id
        
        if email_id:
            logger.info(f"Email sent successfully to {to} (id: {email_id})")
            return True
        else:
            logger.error(f"Email send returned invalid response: {response} (type: {type(response)})")
            return False
            
    except Exception as exc:
        logger.error(f"Failed to send email to {to}: {exc}", exc_info=True)
        return False


def send_verification_email(email: str, code: str) -> bool:
    """
    Send an email verification code using Resend.

    Args:
        email: Recipient email address
        code: Verification code to send
        
    Returns:
        bool: True on success, False on failure
    """
    html = f"""
    <p>Welcome! Please confirm your email address.</p>
    <p>Your verification code is:</p>
    <p style="font-size: 20px; font-weight: bold;">{code}</p>
    <p>This code will expire in 10 minutes.</p>
    """
    
    return _send_email(email, "Confirm your email address", html)


def send_password_reset_email(email: str, token: str) -> bool:
    """
    Send a password reset link using Resend.

    Args:
        email: Recipient email address
        token: Password reset token
        
    Returns:
        bool: True on success, False on failure
    """
    # Build link with token
    reset_link = f"{settings.FRONTEND_URL}/login?reset_token={quote(token)}"

    html = f"""
    <p>You requested to reset your password.</p>
    <p>Click the link below to reset your password:</p>
    <p style="margin: 20px 0;">
      <a href="{reset_link}" target="_blank" rel="noopener noreferrer" 
         style="display: inline-block; padding: 12px 24px; background-color: #e94560; color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">
        Reset your password
      </a>
    </p>
    <p>If you did not request this, you can safely ignore this email.</p>
    <p>This link will expire in 15 minutes.</p>
    <p style="color: #999; font-size: 12px; margin-top: 20px;">
      Or copy and paste this link into your browser:<br/>
      {reset_link}
    </p>
    """
    
    return _send_email(email, "Reset your hopper password", html)


def verify_resend_signature(payload: bytes, svix_id: str, svix_timestamp: str, svix_signature: str) -> bool:
    """Verify Resend webhook signature using Svix format (HMAC-SHA256)
    
    Resend uses Svix for webhook signing. The signature is computed as:
    HMAC-SHA256(timestamp + "." + id + "." + payload, secret)
    
    The svix-signature header can contain multiple signatures separated by spaces.
    Format: "v1,signature1 v1,signature2"
    """
    if not settings.RESEND_WEBHOOK_SECRET:
        logger.warning("Cannot verify webhook signature: RESEND_WEBHOOK_SECRET not set")
        return False
    
    if not svix_id or not svix_timestamp or not svix_signature:
        return False
    
    try:
        # Svix signature format: "v1,signature1 v1,signature2" (can have multiple)
        # We need to check if any of the signatures match
        signature_parts = svix_signature.split(" ")
        
        # Create the signed payload: timestamp.id.payload (all as bytes)
        # Svix format requires: timestamp + "." + id + "." + payload (all bytes)
        timestamp_bytes = svix_timestamp.encode('utf-8')
        id_bytes = svix_id.encode('utf-8')
        signed_payload = timestamp_bytes + b'.' + id_bytes + b'.' + payload
        
        # Compute expected signature using HMAC-SHA256, then base64 encode
        # Svix signatures are base64 encoded, not hex
        hmac_digest = hmac.new(
            settings.RESEND_WEBHOOK_SECRET.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hmac_digest).decode('utf-8')
        
        # Check each signature in the header
        for sig_part in signature_parts:
            if not sig_part.startswith("v1,"):
                continue
            
            # Extract the signature value (after "v1,") - it's base64 encoded
            provided_signature = sig_part.split(",", 1)[1] if "," in sig_part else None
            if provided_signature and hmac.compare_digest(expected_signature, provided_signature):
                logger.debug(f"Resend webhook signature verified successfully")
                return True
        
        logger.warning(f"Resend webhook signature verification failed - no matching signature found")
        return False
    except Exception as e:
        logger.error(f"Error verifying Resend signature: {e}", exc_info=True)
        return False


def log_email_event(resend_event_id: str, event_type: str, payload: dict, db: Session) -> EmailEvent:
    """Log Resend webhook event in database for idempotency and tracking"""
    email_event = db.query(EmailEvent).filter(EmailEvent.resend_event_id == resend_event_id).first()
    if not email_event:
        event_data = payload.get("data", {})
        email_event = EmailEvent(
            resend_event_id=resend_event_id,
            event_type=event_type,
            email_id=event_data.get("email_id"),
            to_email=event_data.get("to"),
            payload=payload,
            processed=False
        )
        db.add(email_event)
        db.commit()
        db.refresh(email_event)
    return email_event


def mark_email_event_processed(resend_event_id: str, db: Session, error_message: str = None):
    """Mark email event as processed"""
    email_event = db.query(EmailEvent).filter(EmailEvent.resend_event_id == resend_event_id).first()
    if email_event:
        email_event.processed = True
        email_event.processed_at = datetime.now(timezone.utc)
        if error_message:
            email_event.error_message = error_message
        db.commit()


def process_resend_webhook(payload: bytes, svix_id: str, svix_timestamp: str, svix_signature: str, db: Session) -> Dict[str, Any]:
    """Process Resend webhook event with idempotency logging
    
    Resend uses Svix for webhook signing with three headers:
    - svix-id: Unique message ID
    - svix-timestamp: Timestamp
    - svix-signature: Signature(s) in format "v1,sig1 v1,sig2"
    """
    # In production, require all Svix headers if secret is configured
    if settings.RESEND_WEBHOOK_SECRET and settings.ENVIRONMENT == "production":
        if not svix_id or not svix_timestamp or not svix_signature:
            logger.warning("Resend webhook missing required Svix headers in production")
            raise ValueError("Missing required Svix headers")
    
    # Verify webhook signature if all headers are present
    if svix_id and svix_timestamp and svix_signature:
        if not verify_resend_signature(payload, svix_id, svix_timestamp, svix_signature):
            if settings.RESEND_WEBHOOK_SECRET:
                logger.error("Invalid Resend webhook signature")
                raise ValueError("Invalid signature")
            else:
                logger.warning("Webhook signature not verified: RESEND_WEBHOOK_SECRET not set")
    else:
        # Missing headers - log warning but allow in development
        if settings.ENVIRONMENT != "production":
            logger.warning("Webhook received without Svix headers - allowing in development mode")
        elif settings.RESEND_WEBHOOK_SECRET:
            logger.warning("Webhook received without Svix headers in production - this is unusual")
    
    try:
        event = json.loads(payload)
        event_type = event.get("type")
        event_data = event.get("data", {})
        email_id = event_data.get("email_id", "unknown")
        resend_event_id = event.get("id") or email_id
        
        # Log event for idempotency
        email_event = log_email_event(resend_event_id, event_type, event, db)
        if email_event.processed:
            logger.info(f"Resend webhook event {resend_event_id} already processed, skipping")
            return {"status": "already_processed"}
        
        # Log event details
        logger.info(f"Resend webhook: {event_type} for email {email_id}")
        
        # Handle critical events (bounces, complaints)
        if event_type == "email.bounced":
            logger.warning(f"Email bounced: {email_id} - {event_data.get('bounce_type', 'unknown')}")
        elif event_type == "email.complained":
            logger.warning(f"Email complaint: {email_id}")
        
        mark_email_event_processed(resend_event_id, db)
        return {"status": "success"}
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Resend webhook payload")
        raise ValueError("Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing Resend webhook: {e}", exc_info=True)
        # Try to mark event as processed if we have the event ID
        try:
            event = json.loads(payload)
            event_data = event.get("data", {})
            email_id = event_data.get("email_id", "unknown")
            resend_event_id = event.get("id") or email_id
            mark_email_event_processed(resend_event_id, db, error_message=str(e))
        except:
            pass  # If we can't extract event ID, just log the error
        raise

