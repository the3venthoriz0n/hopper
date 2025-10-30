from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
from datetime import datetime
import os
from pathlib import Path

app = FastAPI(title="Video Upload Scheduler API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Models (simplified)
class VideoMetadata(BaseModel):
    title: str
    description: Optional[str] = ""

# In-memory storage (replace with database in production)
oauth_tokens = {}
video_queue = []

@app.get("/")
async def root():
    return {"message": "Video Upload Scheduler API", "status": "running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

# OAuth endpoints
@app.get("/api/auth/youtube")
async def youtube_oauth():
    """Initiate YouTube OAuth flow"""
    try:
        from google_auth_oauthlib.flow import Flow
        
        if not os.path.exists('client_secrets.json'):
            return JSONResponse(
                status_code=400,
                content={"error": "client_secrets.json not found. Please add your YouTube API credentials."}
            )
        
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/youtube.upload'],
            redirect_uri='http://localhost:8000/api/auth/youtube/callback'
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        
        return {"url": authorization_url, "state": state}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"OAuth initialization failed: {str(e)}"}
        )

@app.get("/api/auth/youtube/callback")
async def youtube_oauth_callback(code: str):
    """Handle YouTube OAuth callback"""
    try:
        from google_auth_oauthlib.flow import Flow
        
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/youtube.upload'],
            redirect_uri='http://localhost:8000/api/auth/youtube/callback'
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Store tokens
        oauth_tokens['youtube'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        return RedirectResponse("http://localhost:3000?connected=youtube")
    except Exception as e:
        return RedirectResponse(f"http://localhost:3000?error={str(e)}")

@app.get("/api/destinations")
async def get_destinations():
    """Get list of available destinations and their status"""
    return {
        "youtube": {
            "connected": "youtube" in oauth_tokens,
            "enabled": False
        }
    }

@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload video file to server"""
    try:
        # Save video temporarily
        video_path = UPLOAD_DIR / file.filename
        
        with open(video_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        video_id = len(video_queue) + 1
        video_data = {
            "id": video_id,
            "filename": file.filename,
            "path": str(video_path),
            "size": len(content),
            "status": "pending",
            "uploaded_at": datetime.now().isoformat()
        }
        video_queue.append(video_data)
        
        return video_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/start")
async def start_upload_queue():
    """Start uploading videos immediately"""
    try:
        if 'youtube' not in oauth_tokens:
            raise HTTPException(status_code=400, detail="YouTube not connected")
        
        if not video_queue:
            raise HTTPException(status_code=400, detail="No videos in queue")
        
        # Import uploader and helpers
        from youtube_uploader import YouTubeUploader
        from scheduler import UploadScheduler
        from title_generator import TitleGenerator
        
        uploader = YouTubeUploader(oauth_tokens['youtube'])
        scheduler = UploadScheduler()
        title_gen = TitleGenerator()
        
        # Generate titles for videos
        for video in video_queue:
            title = title_gen.generate(video['filename'])
            video['metadata'] = {
                'title': title,
                'description': f"Uploaded via Hopper"
            }
        
        # Upload immediately
        scheduler.schedule_uploads(video_queue, uploader)
        
        return {
            "message": "Videos uploaded successfully",
            "queue_size": len(video_queue)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/queue")
async def get_queue():
    """Get current upload queue"""
    return {"videos": video_queue, "count": len(video_queue)}

@app.delete("/api/queue/{video_id}")
async def remove_from_queue(video_id: int):
    """Remove a video from the queue"""
    global video_queue
    video_queue = [v for v in video_queue if v['id'] != video_id]
    return {"message": "Video removed", "queue_size": len(video_queue)}

@app.delete("/api/queue")
async def clear_queue():
    """Clear the entire queue"""
    global video_queue
    video_queue = []
    return {"message": "Queue cleared"}

if __name__ == "__main__":
    print("🚀 Starting Video Upload Scheduler API...")
    print("📍 Server running at: http://localhost:8000")
    print("📚 API docs at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)