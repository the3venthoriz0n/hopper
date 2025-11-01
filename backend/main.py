from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path
import uvicorn
import os
import asyncio
from datetime import datetime, timedelta, timezone

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
    "made_for_kids": False,
    "title_template": "{filename}",  # {filename} will be replaced with video filename
    "description_template": "Uploaded via Hopper",
    "upload_immediately": True,  # If True, upload right away; if False, schedule
    "schedule_mode": "spaced",  # spaced, specific_time
    "schedule_interval_value": 1,  # numeric value for interval
    "schedule_interval_unit": "hours",  # minutes, hours, days
    "schedule_start_time": ""  # ISO format datetime for specific_time mode
}
upload_progress = {}  # Track upload progress: {video_id: progress_percent}

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
    scheduled_count = len([v for v in videos if v['status'] == 'scheduled'])
    return {
        "youtube": {
            "connected": youtube_creds is not None,
            "enabled": False
        },
        "scheduled_videos": scheduled_count
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
def update_youtube_settings(
    visibility: str = None, 
    made_for_kids: bool = None,
    title_template: str = None,
    description_template: str = None,
    upload_immediately: bool = None,
    schedule_mode: str = None,
    schedule_interval_value: int = None,
    schedule_interval_unit: str = None,
    schedule_start_time: str = None
):
    """Update YouTube upload settings"""
    global youtube_settings
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        youtube_settings["visibility"] = visibility
    
    if made_for_kids is not None:
        youtube_settings["made_for_kids"] = made_for_kids
    
    if title_template is not None:
        youtube_settings["title_template"] = title_template
    
    if description_template is not None:
        youtube_settings["description_template"] = description_template
    
    if upload_immediately is not None:
        youtube_settings["upload_immediately"] = upload_immediately
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        youtube_settings["schedule_mode"] = schedule_mode
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        youtube_settings["schedule_interval_value"] = schedule_interval_value
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        youtube_settings["schedule_interval_unit"] = schedule_interval_unit
    
    if schedule_start_time is not None:
        youtube_settings["schedule_start_time"] = schedule_start_time
    
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
    """Get video queue with progress and computed titles"""
    # Add progress info and computed YouTube titles to videos
    videos_with_info = []
    for video in videos:
        video_copy = video.copy()
        
        # Add upload progress if available
        if video['id'] in upload_progress:
            video_copy['upload_progress'] = upload_progress[video['id']]
        
        # Compute YouTube title from template
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        youtube_title = youtube_settings['title_template'].replace('{filename}', filename_no_ext)
        video_copy['youtube_title'] = youtube_title
        
        videos_with_info.append(video_copy)
    return videos_with_info

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int):
    """Remove from queue"""
    global videos
    videos = [v for v in videos if v['id'] != video_id]
    return {"ok": True}

def upload_video_to_youtube(video):
    """Helper function to upload a single video to YouTube"""
    global upload_progress
    
    if not youtube_creds:
        video['status'] = 'failed'
        video['error'] = 'No YouTube credentials'
        return
    
    try:
        video['status'] = 'uploading'
        upload_progress[video['id']] = 0
        
        youtube = build('youtube', 'v3', credentials=youtube_creds)
        
        # Generate title and description from templates
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        title = youtube_settings['title_template'].replace('{filename}', filename_no_ext)
        description = youtube_settings['description_template'].replace('{filename}', filename_no_ext)
        
        request = youtube.videos().insert(
            part='snippet,status',
            body={
                'snippet': {
                    'title': title,
                    'description': description,
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
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                upload_progress[video['id']] = progress
        
        video['status'] = 'uploaded'
        video['youtube_id'] = response['id']
        upload_progress[video['id']] = 100
        
    except Exception as e:
        video['status'] = 'failed'
        video['error'] = str(e)
        if video['id'] in upload_progress:
            del upload_progress[video['id']]

async def scheduler_task():
    """Background task that checks for scheduled videos and uploads them"""
    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            current_time = datetime.now(timezone.utc)
            
            # Find videos that are scheduled and due for upload
            for video in videos:
                if video['status'] == 'scheduled' and 'scheduled_time' in video:
                    try:
                        scheduled_time = datetime.fromisoformat(video['scheduled_time'])
                        
                        # If scheduled time has passed, upload the video
                        if current_time >= scheduled_time:
                            print(f"Uploading scheduled video: {video['filename']}")
                            upload_video_to_youtube(video)
                    except Exception as e:
                        print(f"Error processing scheduled video {video['filename']}: {e}")
                        video['status'] = 'failed'
                        video['error'] = str(e)
        except Exception as e:
            print(f"Error in scheduler task: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    """Start the scheduler when the app starts"""
    asyncio.create_task(scheduler_task())
    print("Scheduler task started")

@app.post("/api/upload")
def upload_videos():
    """Upload all pending videos to YouTube (immediate or scheduled)"""
    if not youtube_creds:
        raise HTTPException(400, "YouTube not connected")
    
    pending_videos = [v for v in videos if v['status'] == 'pending']
    
    if not pending_videos:
        raise HTTPException(400, "No pending videos to upload")
    
    # If upload immediately is enabled, upload all at once
    if youtube_settings['upload_immediately']:
        for video in pending_videos:
            upload_video_to_youtube(video)
        
        return {
            "uploaded": len([v for v in videos if v['status'] == 'uploaded']),
            "message": "Videos uploaded immediately"
        }
    
    # Otherwise, mark for scheduled upload
    if youtube_settings['schedule_mode'] == 'spaced':
        # Calculate interval in minutes
        value = youtube_settings['schedule_interval_value']
        unit = youtube_settings['schedule_interval_unit']
        
        if unit == 'minutes':
            interval_minutes = value
        elif unit == 'hours':
            interval_minutes = value * 60
        elif unit == 'days':
            interval_minutes = value * 1440
        else:
            interval_minutes = 60  # default to 1 hour
        
        # Set scheduled time for each video (use timezone-aware datetime)
        current_time = datetime.now(timezone.utc)
        for i, video in enumerate(pending_videos):
            scheduled_time = current_time + timedelta(minutes=interval_minutes * i)
            video['scheduled_time'] = scheduled_time.isoformat()
            video['status'] = 'scheduled'
        
        return {
            "scheduled": len(pending_videos),
            "message": f"Videos scheduled with {value} {unit} interval"
        }
    
    elif youtube_settings['schedule_mode'] == 'specific_time':
        # Schedule all for a specific time
        if youtube_settings['schedule_start_time']:
            for video in pending_videos:
                video['scheduled_time'] = youtube_settings['schedule_start_time']
                video['status'] = 'scheduled'
            
            return {
                "scheduled": len(pending_videos),
                "message": f"Videos scheduled for {youtube_settings['schedule_start_time']}"
            }
        else:
            raise HTTPException(400, "No start time specified for scheduled upload")
    
    return {"message": "Upload processing"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

