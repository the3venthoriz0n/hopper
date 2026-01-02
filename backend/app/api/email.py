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
    headers = dict(request.headers)
    
    # Log headers for debugging (in development)
    if settings.ENVIRONMENT != "production":
        logger.info(f"Webhook headers: {headers}")
        svix_id = headers.get("svix-id")
        svix_timestamp = headers.get("svix-timestamp")
        svix_signature = headers.get("svix-signature")
        logger.info(f"Svix headers - id: {svix_id is not None}, timestamp: {svix_timestamp is not None}, signature: {svix_signature is not None}")
    
    try:
        return process_resend_webhook(payload, headers, db)
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        # Return 200 to prevent Resend from retrying infinitely
        return {"status": "error", "message": "Webhook processing failed"}

