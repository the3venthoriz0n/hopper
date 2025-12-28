"""Email webhook endpoints"""
import hmac
import hashlib
import json
import logging
from fastapi import APIRouter, Request, HTTPException
from app.core.config import settings

router = APIRouter(prefix="/api/email", tags=["email"])
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def resend_webhook(request: Request):
    """Handle Resend webhook events"""
    payload = await request.body()
    signature = request.headers.get("resend-signature")
    
    if not signature:
        logger.warning("Resend webhook received without signature header")
        raise HTTPException(status_code=400, detail="Missing resend-signature header")
    
    # Verify webhook signature
    if not verify_resend_signature(payload, signature):
        logger.error("Invalid Resend webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    try:
        event = json.loads(payload)
        event_type = event.get("type")
        event_data = event.get("data", {})
        email_id = event_data.get("email_id", "unknown")
        
        # Log event (keep it simple)
        logger.info(f"Resend webhook: {event_type} for email {email_id}")
        
        # Handle critical events (bounces, complaints)
        if event_type == "email.bounced":
            logger.warning(f"Email bounced: {email_id} - {event_data.get('bounce_type', 'unknown')}")
        elif event_type == "email.complained":
            logger.warning(f"Email complaint: {email_id}")
        
        return {"status": "ok"}
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Resend webhook payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Error processing Resend webhook: {e}", exc_info=True)
        # Return 200 to prevent Resend from retrying
        return {"status": "error", "message": str(e)}


def verify_resend_signature(payload: bytes, signature: str) -> bool:
    """Verify Resend webhook signature using HMAC-SHA256"""
    if not settings.RESEND_WEBHOOK_SECRET:
        logger.warning("Cannot verify webhook signature: RESEND_WEBHOOK_SECRET not set")
        return False
    
    try:
        # Resend signature format: timestamp,hash
        # Parse: t=timestamp,v1=hash
        parts = signature.split(",")
        timestamp = None
        hash_value = None
        
        for part in parts:
            if part.startswith("t="):
                timestamp = part.split("=")[1]
            elif part.startswith("v1="):
                hash_value = part.split("=")[1]
        
        if not timestamp or not hash_value:
            return False
        
        # Create expected signature: HMAC-SHA256(timestamp.payload, webhook_secret)
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        expected_signature = hmac.new(
            settings.RESEND_WEBHOOK_SECRET.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, hash_value)
    except Exception as e:
        logger.error(f"Error verifying Resend signature: {e}")
        return False

