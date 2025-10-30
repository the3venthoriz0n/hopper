from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path
import uvicorn
import os

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

# CORS - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage
UPLOAD_DIR = Path("uploads")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Directory already exists or mounted

youtube_creds = None
videos = []
youtube_settings = {
    "visibility": "private",  # public, private, unlisted
    "made_for_kids": False
}

@app.get("/api/auth/youtube")
def auth_youtube(request: Request):
    """Start YouTube OAuth"""
    if not os.path.exists('client_secrets.json'):
        raise HTTPException(400, "client_secrets.json missing")
    
    # Build redirect URI dynamically based on request host
    host = request.headers.get("host", "localhost:8000")
    redirect_uri = f"http://{host}/api/auth/youtube/callback"
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    url, _ = flow.authorization_url(access_type='offline')
    return {"url": url}

@app.get("/api/auth/youtube/callback")
def auth_callback(code: str, request: Request):
    """OAuth callback"""
    global youtube_creds
    
    # Build redirect URI dynamically
    host = request.headers.get("host", "localhost:8000")
    redirect_uri = f"http://{host}/api/auth/youtube/callback"
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    flow.fetch_token(code=code)
    youtube_creds = flow.credentials
    
    # Redirect back to frontend (replace port 8000 with 3000)
    frontend_url = f"http://{host.replace(':8000', ':3000')}?connected=youtube"
    return RedirectResponse(frontend_url)

@app.get("/api/destinations")
def get_destinations():
    """Get destination status"""
    return {
        "youtube": {
            "connected": youtube_creds is not None,
            "enabled": False
        }
    }

@app.post("/api/auth/youtube/disconnect")
def disconnect_youtube():
    """Disconnect YouTube account"""
    global youtube_creds
    youtube_creds = None
    return {"message": "Disconnected"}

@app.get("/api/youtube/settings")
def get_youtube_settings():
    """Get YouTube upload settings"""
    return youtube_settings

@app.post("/api/youtube/settings")
def update_youtube_settings(visibility: str = None, made_for_kids: bool = None):
    """Update YouTube upload settings"""
    global youtube_settings
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        youtube_settings["visibility"] = visibility
    
    if made_for_kids is not None:
        youtube_settings["made_for_kids"] = made_for_kids
    
    return youtube_settings

@app.post("/api/videos")
async def add_video(file: UploadFile = File(...)):
    """Add video to queue"""
    path = UPLOAD_DIR / file.filename
    
    with open(path, "wb") as f:
        f.write(await file.read())
    
    video = {
        "id": len(videos) + 1,
        "filename": file.filename,
        "path": str(path),
        "status": "pending"
    }
    videos.append(video)
    return video

@app.get("/api/videos")
def get_videos():
    """Get video queue"""
    return videos

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int):
    """Remove from queue"""
    global videos
    videos = [v for v in videos if v['id'] != video_id]
    return {"ok": True}

@app.post("/api/upload")
def upload_videos():
    """Upload all pending videos to YouTube"""
    if not youtube_creds:
        raise HTTPException(400, "YouTube not connected")
    
    youtube = build('youtube', 'v3', credentials=youtube_creds)
    
    for video in videos:
        if video['status'] != 'pending':
            continue
        
        try:
            title = video['filename'].rsplit('.', 1)[0]
            
            request = youtube.videos().insert(
                part='snippet,status',
                body={
                    'snippet': {
                        'title': title,
                        'description': 'Uploaded via Hopper',
                        'categoryId': '22'
                    },
                    'status': {
                        'privacyStatus': youtube_settings['visibility'],
                        'selfDeclaredMadeForKids': youtube_settings['made_for_kids']
                    }
                },
                media_body=MediaFileUpload(video['path'], resumable=True)
            )
            
            response = None
            while response is None:
                _, response = request.next_chunk()
            
            video['status'] = 'uploaded'
            video['youtube_id'] = response['id']
            
        except Exception as e:
            video['status'] = 'failed'
            video['error'] = str(e)
    
    return {"uploaded": len([v for v in videos if v['status'] == 'uploaded'])}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

