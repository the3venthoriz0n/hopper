from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pathlib import Path
import uvicorn
import os
import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

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
SESSIONS_DIR = Path("sessions")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # Directory already exists or mounted

# Session storage: {session_id: {youtube_creds, videos, youtube_settings, upload_progress}}
sessions = {}

def get_default_settings():
    """Return default YouTube settings"""
    return {
        "visibility": "private",
        "made_for_kids": False,
        "title_template": "{filename}",
        "description_template": "Uploaded via Hopper",
        "upload_immediately": True,
        "schedule_mode": "spaced",
        "schedule_interval_value": 1,
        "schedule_interval_unit": "hours",
        "schedule_start_time": ""
    }

def get_session(session_id: str):
    """Get or create a session"""
    if session_id not in sessions:
        sessions[session_id] = {
            "youtube_creds": None,
            "videos": [],
            "youtube_settings": get_default_settings(),
            "upload_progress": {}
        }
        # Try to load from disk
        load_session(session_id)
    return sessions[session_id]

def save_session(session_id: str):
    """Save session to disk"""
    if session_id not in sessions:
        return
    
    session_data = sessions[session_id].copy()
    
    # Convert Credentials object to dict for JSON serialization
    if session_data["youtube_creds"]:
        creds = session_data["youtube_creds"]
        session_data["youtube_creds"] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
    
    session_file = SESSIONS_DIR / f"{session_id}.json"
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
    except Exception as e:
        print(f"Error saving session: {e}")

def load_session(session_id: str):
    """Load session from disk"""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return
    
    try:
        with open(session_file, 'r') as f:
            session_data = json.load(f)
        
        # Convert credentials dict back to Credentials object
        if session_data.get("youtube_creds"):
            creds_data = session_data["youtube_creds"]
            session_data["youtube_creds"] = Credentials(
                token=creds_data.get("token"),
                refresh_token=creds_data.get("refresh_token"),
                token_uri=creds_data.get("token_uri"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                scopes=creds_data.get("scopes")
            )
        
        sessions[session_id] = session_data
        print(f"Loaded session {session_id}")
    except Exception as e:
        print(f"Error loading session: {e}")

def get_or_create_session_id(request: Request, response: Response) -> str:
    """Get existing session ID from cookie or create new one"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,  # 30 days
            samesite="lax"
        )
    return session_id

@app.get("/api/auth/youtube")
def auth_youtube(request: Request, response: Response):
    """Start YouTube OAuth"""
    if not os.path.exists('client_secrets.json'):
        raise HTTPException(400, "client_secrets.json missing")
    
    # Ensure session exists
    session_id = get_or_create_session_id(request, response)
    
    # Build redirect URI dynamically based on request host
    host = request.headers.get("host", "localhost:8000")
    redirect_uri = f"http://{host}/api/auth/youtube/callback"
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    # Store session_id in state parameter
    url, state = flow.authorization_url(access_type='offline', state=session_id)
    return {"url": url}

@app.get("/api/auth/youtube/callback")
def auth_callback(code: str, state: str, request: Request, response: Response):
    """OAuth callback"""
    # Get session from state parameter
    session_id = state
    session = get_session(session_id)
    
    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=30*24*60*60,
        samesite="lax"
    )
    
    # Build redirect URI dynamically
    host = request.headers.get("host", "localhost:8000")
    redirect_uri = f"http://{host}/api/auth/youtube/callback"
    
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/youtube.upload'],
        redirect_uri=redirect_uri
    )
    
    flow.fetch_token(code=code)
    session["youtube_creds"] = flow.credentials
    save_session(session_id)
    
    # Redirect back to frontend (replace port 8000 with 3000)
    frontend_url = f"http://{host.replace(':8000', ':3000')}?connected=youtube"
    return RedirectResponse(frontend_url)

@app.get("/api/destinations")
def get_destinations(request: Request, response: Response):
    """Get destination status"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    scheduled_count = len([v for v in session["videos"] if v['status'] == 'scheduled'])
    return {
        "youtube": {
            "connected": session["youtube_creds"] is not None,
            "enabled": False
        },
        "scheduled_videos": scheduled_count
    }

@app.post("/api/auth/youtube/disconnect")
def disconnect_youtube(request: Request, response: Response):
    """Disconnect YouTube account"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["youtube_creds"] = None
    save_session(session_id)
    return {"message": "Disconnected"}

@app.get("/api/youtube/settings")
def get_youtube_settings(request: Request, response: Response):
    """Get YouTube upload settings"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    return session["youtube_settings"]

@app.post("/api/youtube/settings")
def update_youtube_settings(
    request: Request,
    response: Response,
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
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    settings = session["youtube_settings"]
    
    if visibility is not None:
        if visibility not in ["public", "private", "unlisted"]:
            raise HTTPException(400, "Invalid visibility option")
        settings["visibility"] = visibility
    
    if made_for_kids is not None:
        settings["made_for_kids"] = made_for_kids
    
    if title_template is not None:
        settings["title_template"] = title_template
    
    if description_template is not None:
        settings["description_template"] = description_template
    
    if upload_immediately is not None:
        settings["upload_immediately"] = upload_immediately
    
    if schedule_mode is not None:
        if schedule_mode not in ["spaced", "specific_time"]:
            raise HTTPException(400, "Invalid schedule mode")
        settings["schedule_mode"] = schedule_mode
    
    if schedule_interval_value is not None:
        if schedule_interval_value < 1:
            raise HTTPException(400, "Interval value must be at least 1")
        settings["schedule_interval_value"] = schedule_interval_value
    
    if schedule_interval_unit is not None:
        if schedule_interval_unit not in ["minutes", "hours", "days"]:
            raise HTTPException(400, "Invalid interval unit")
        settings["schedule_interval_unit"] = schedule_interval_unit
    
    if schedule_start_time is not None:
        settings["schedule_start_time"] = schedule_start_time
    
    save_session(session_id)
    return settings

@app.post("/api/videos")
async def add_video(file: UploadFile = File(...), request: Request = None, response: Response = None):
    """Add video to queue"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    path = UPLOAD_DIR / file.filename
    
    with open(path, "wb") as f:
        f.write(await file.read())
    
    video = {
        "id": len(session["videos"]) + 1,
        "filename": file.filename,
        "path": str(path),
        "status": "pending"
    }
    session["videos"].append(video)
    save_session(session_id)
    return video

@app.get("/api/videos")
def get_videos(request: Request, response: Response):
    """Get video queue with progress and computed titles"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    # Add progress info and computed YouTube titles to videos
    videos_with_info = []
    for video in session["videos"]:
        video_copy = video.copy()
        
        # Add upload progress if available
        if video['id'] in session["upload_progress"]:
            video_copy['upload_progress'] = session["upload_progress"][video['id']]
        
        # Compute YouTube title from template
        filename_no_ext = video['filename'].rsplit('.', 1)[0]
        youtube_title = session["youtube_settings"]['title_template'].replace('{filename}', filename_no_ext)
        video_copy['youtube_title'] = youtube_title
        
        videos_with_info.append(video_copy)
    return videos_with_info

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, request: Request, response: Response):
    """Remove from queue"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    session["videos"] = [v for v in session["videos"] if v['id'] != video_id]
    save_session(session_id)
    return {"ok": True}

def upload_video_to_youtube(video, session):
    """Helper function to upload a single video to YouTube"""
    youtube_creds = session["youtube_creds"]
    youtube_settings = session["youtube_settings"]
    upload_progress = session["upload_progress"]
    
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
            
            # Check all sessions for scheduled videos
            for session_id, session in list(sessions.items()):
                for video in session["videos"]:
                    if video['status'] == 'scheduled' and 'scheduled_time' in video:
                        try:
                            scheduled_time = datetime.fromisoformat(video['scheduled_time'])
                            
                            # If scheduled time has passed, upload the video
                            if current_time >= scheduled_time:
                                print(f"Uploading scheduled video for session {session_id}: {video['filename']}")
                                upload_video_to_youtube(video, session)
                                save_session(session_id)
                        except Exception as e:
                            print(f"Error processing scheduled video {video['filename']}: {e}")
                            video['status'] = 'failed'
                            video['error'] = str(e)
                            save_session(session_id)
        except Exception as e:
            print(f"Error in scheduler task: {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    """Start the scheduler when the app starts"""
    asyncio.create_task(scheduler_task())
    print("Scheduler task started")

@app.post("/api/upload")
def upload_videos(request: Request, response: Response):
    """Upload all pending videos to YouTube (immediate or scheduled)"""
    session_id = get_or_create_session_id(request, response)
    session = get_session(session_id)
    
    if not session["youtube_creds"]:
        raise HTTPException(400, "YouTube not connected")
    
    pending_videos = [v for v in session["videos"] if v['status'] == 'pending']
    
    if not pending_videos:
        raise HTTPException(400, "No pending videos to upload")
    
    # If upload immediately is enabled, upload all at once
    if session["youtube_settings"]['upload_immediately']:
        for video in pending_videos:
            upload_video_to_youtube(video, session)
        
        save_session(session_id)
        return {
            "uploaded": len([v for v in session["videos"] if v['status'] == 'uploaded']),
            "message": "Videos uploaded immediately"
        }
    
    # Otherwise, mark for scheduled upload
    if session["youtube_settings"]['schedule_mode'] == 'spaced':
        # Calculate interval in minutes
        value = session["youtube_settings"]['schedule_interval_value']
        unit = session["youtube_settings"]['schedule_interval_unit']
        
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
        
        save_session(session_id)
        return {
            "scheduled": len(pending_videos),
            "message": f"Videos scheduled with {value} {unit} interval"
        }
    
    elif session["youtube_settings"]['schedule_mode'] == 'specific_time':
        # Schedule all for a specific time
        if session["youtube_settings"]['schedule_start_time']:
            for video in pending_videos:
                video['scheduled_time'] = session["youtube_settings"]['schedule_start_time']
                video['status'] = 'scheduled'
            
            save_session(session_id)
            return {
                "scheduled": len(pending_videos),
                "message": f"Videos scheduled for {session['youtube_settings']['schedule_start_time']}"
            }
        else:
            raise HTTPException(400, "No start time specified for scheduled upload")
    
    return {"message": "Upload processing"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

