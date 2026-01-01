"""Email webhook endpoints"""
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings
from app.services.email_service import process_resend_webhook

router = APIRouter(prefix="/api/email", tags=["email"])
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def resend_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Resend webhook events (uses Svix for webhook signing)"""
    payload = await request.body()
    
    # Resend uses Svix for webhook signing - extract the three required headers
    svix_id = request.headers.get("svix-id")
    svix_timestamp = request.headers.get("svix-timestamp")
    svix_signature = request.headers.get("svix-signature")
    
    # Log headers for debugging (in development)
    if settings.ENVIRONMENT != "production":
        logger.info(f"Webhook headers: {dict(request.headers)}")
        logger.info(f"Svix headers - id: {svix_id is not None}, timestamp: {svix_timestamp is not None}, signature: {svix_signature is not None}")
    
    # In production, require all Svix headers if secret is configured
    if settings.RESEND_WEBHOOK_SECRET and settings.ENVIRONMENT == "production":
        if not svix_id or not svix_timestamp or not svix_signature:
            logger.warning("Resend webhook missing required Svix headers in production")
            raise HTTPException(status_code=400, detail="Missing required Svix headers")
    
    try:
        return process_resend_webhook(payload, svix_id, svix_timestamp, svix_signature, db)
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        # Return 200 to prevent Resend from retrying infinitely
        return {"status": "error", "message": "Webhook processing failed"}

