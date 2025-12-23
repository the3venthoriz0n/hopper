"""OAuth API routes"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from app.core.security import require_auth
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["oauth"])


@router.get("/google/login")
def google_login():
    """Initiate Google OAuth login"""
    # Placeholder - full implementation would handle OAuth flow
    raise HTTPException(501, "OAuth not yet implemented in new structure")


@router.get("/youtube")
def youtube_auth(user_id: int = Depends(require_auth)):
    """Get YouTube OAuth status"""
    # Placeholder
    raise HTTPException(501, "OAuth not yet implemented in new structure")


@router.get("/tiktok")
def tiktok_auth(user_id: int = Depends(require_auth)):
    """Initiate TikTok OAuth"""
    # Placeholder
    raise HTTPException(501, "OAuth not yet implemented in new structure")


@router.get("/instagram")
def instagram_auth(user_id: int = Depends(require_auth)):
    """Initiate Instagram OAuth"""
    # Placeholder
    raise HTTPException(501, "OAuth not yet implemented in new structure")

