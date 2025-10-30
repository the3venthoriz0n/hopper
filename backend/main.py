from fastapi import FastAPI, UploadFile, File, HTTPException
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

@app.get("/api/auth/youtube")
def auth_youtube():
    """Start YouTube OAuth"""
    if not os.path.exists('client_secrets.json'):
        raise HTTPException(400, "client_secrets.json missing")
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri='http://localhost:8000/api/auth/youtube/callback'
    )
    
    url, _ = flow.authorization_url(access_type='offline')
    return {"url": url}

@app.get("/api/auth/youtube/callback")
def auth_callback(code: str):
    """OAuth callback"""
    global youtube_creds
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri='http://localhost:8000/api/auth/youtube/callback'
    )
    
    flow.fetch_token(code=code)
    youtube_creds = flow.credentials
    
    return RedirectResponse("http://localhost:3000?connected=youtube")

@app.get("/api/destinations")
def get_destinations():
    """Get destination status"""
    return {
        "youtube": {
            "connected": youtube_creds is not None,
            "enabled": False
        }
    }

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
                    'status': {'privacyStatus': 'private'}
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

