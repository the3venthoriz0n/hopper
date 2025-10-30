from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from config import settings
from database import get_db
from models import User, Destination
import json

router = APIRouter()

# YouTube OAuth scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']


@router.get("/youtube/url")
async def get_youtube_auth_url():
    """Generate YouTube OAuth URL"""
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise HTTPException(status_code=500, detail="YouTube OAuth not configured")
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.youtube_redirect_uri]
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.youtube_redirect_uri
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    
    return {"url": authorization_url, "state": state}


@router.post("/youtube/callback")
async def youtube_callback(code: str, user_email: str, db: AsyncSession = Depends(get_db)):
    """Handle YouTube OAuth callback"""
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise HTTPException(status_code=500, detail="YouTube OAuth not configured")
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.youtube_redirect_uri]
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.youtube_redirect_uri
    )
    
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    # Get or create user
    result = await db.execute(select(User).where(User.email == user_email))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(email=user_email)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    # Store credentials
    credentials_dict = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    # Create or update destination
    result = await db.execute(
        select(Destination).where(
            Destination.user_id == user.id,
            Destination.platform == "youtube"
        )
    )
    destination = result.scalar_one_or_none()
    
    if destination:
        destination.credentials = json.dumps(credentials_dict)
        destination.enabled = True
    else:
        destination = Destination(
            user_id=user.id,
            platform="youtube",
            enabled=True,
            credentials=json.dumps(credentials_dict)
        )
        db.add(destination)
    
    await db.commit()
    
    return {"status": "success", "user_id": user.id}

