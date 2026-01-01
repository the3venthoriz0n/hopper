"""Email webhook endpoints"""
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.email_service import process_resend_webhook

router = APIRouter(prefix="/api/email", tags=["email"])
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def resend_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Resend webhook events"""
    payload = await request.body()
    signature = request.headers.get("resend-signature")
    
    if not signature:
        logger.warning("Resend webhook received without signature header")
        raise HTTPException(status_code=400, detail="Missing resend-signature header")
    
    try:
        return process_resend_webhook(payload, signature, db)
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        # Return 200 to prevent Resend from retrying infinitely
        return {"status": "error", "message": "Webhook processing failed"}

