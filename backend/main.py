from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import uvicorn
import os
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
youtube_credentials = None
video_queue = []

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/api/youtube/connect")
def youtube_connect():
    """Start YouTube OAuth"""
    if not os.path.exists('client_secrets.json'):
        raise HTTPException(status_code=400, detail="client_secrets.json not found")
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri='http://localhost:8000/api/youtube/callback'
    )
    
    auth_url, _ = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    return {"url": auth_url}

@app.get("/api/youtube/callback")
def youtube_callback(code: str):
    """Handle YouTube OAuth callback"""
    global youtube_credentials
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri='http://localhost:8000/api/youtube/callback'
    )
    
    flow.fetch_token(code=code)
    youtube_credentials = flow.credentials
    
    return RedirectResponse("http://localhost:3000?connected=true")

@app.get("/api/youtube/status")
def youtube_status():
    """Check if YouTube is connected"""
    return {"connected": youtube_credentials is not None}

@app.post("/api/videos/add")
async def add_video(file: UploadFile = File(...)):
    """Add video to queue"""
    video_path = UPLOAD_DIR / file.filename
    
    with open(video_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    video = {
        "id": len(video_queue) + 1,
        "filename": file.filename,
        "path": str(video_path),
        "status": "pending"
    }
    video_queue.append(video)
    
    return video

@app.get("/api/videos")
def get_videos():
    """Get video queue"""
    return {"videos": video_queue}

@app.post("/api/videos/upload")
def upload_videos():
    """Upload all videos to YouTube"""
    if not youtube_credentials:
        raise HTTPException(status_code=400, detail="YouTube not connected")
    
    if not video_queue:
        raise HTTPException(status_code=400, detail="No videos in queue")
    
    youtube = build('youtube', 'v3', credentials=youtube_credentials)
    
    for video in video_queue:
        if video['status'] != 'pending':
            continue
            
        try:
            # Use filename as title
            title = video['filename'].rsplit('.', 1)[0]
            
            body = {
                'snippet': {
                    'title': title,
                    'description': 'Uploaded via Hopper',
                    'categoryId': '22'
                },
                'status': {'privacyStatus': 'private'}
            }
            
            media = MediaFileUpload(video['path'], resumable=True)
            request = youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
            
            video['status'] = 'uploaded'
            video['youtube_id'] = response['id']
            
        except Exception as e:
            video['status'] = 'failed'
            video['error'] = str(e)
    
    return {"message": "Upload complete", "videos": video_queue}

@app.delete("/api/videos/{video_id}")
def remove_video(video_id: int):
    """Remove video from queue"""
    global video_queue
    video_queue = [v for v in video_queue if v['id'] != video_id]
    return {"message": "Removed"}

if __name__ == "__main__":
    print("🚀 Hopper Backend")
    print("📍 http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
