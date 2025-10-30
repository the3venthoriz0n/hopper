from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from database import get_db
from models import Video, Destination
from pathlib import Path
import json
import shutil

router = APIRouter()

# Upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


class VideoResponse(BaseModel):
    id: int
    filename: str
    title: Optional[str]
    description: Optional[str]
    status: str
    scheduled_time: Optional[datetime]
    upload_destinations: Optional[List[int]]
    created_at: datetime
    
    class Config:
        from_attributes = True


class UpdateVideoRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_time: Optional[datetime] = None
    upload_destinations: Optional[List[int]] = None


@router.post("/upload")
async def upload_video(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload a video to the hopper"""
    # Create user-specific upload directory
    user_dir = UPLOAD_DIR / str(user_id)
    user_dir.mkdir(exist_ok=True)
    
    # Save file
    file_path = user_dir / file.filename
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create video record
    video = Video(
        user_id=user_id,
        filename=file.filename,
        file_path=str(file_path),
        status="pending",
        upload_destinations=[]
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    
    return VideoResponse.model_validate(video)


@router.get("/user/{user_id}")
async def get_user_videos(user_id: int, db: AsyncSession = Depends(get_db)):
    """Get all videos for a user"""
    result = await db.execute(
        select(Video).where(Video.user_id == user_id).order_by(Video.created_at.desc())
    )
    videos = result.scalars().all()
    
    return [VideoResponse.model_validate(v) for v in videos]


@router.patch("/{video_id}")
async def update_video(
    video_id: int,
    request: UpdateVideoRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update video metadata"""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if request.title is not None:
        video.title = request.title
    if request.description is not None:
        video.description = request.description
    if request.scheduled_time is not None:
        video.scheduled_time = request.scheduled_time
    if request.upload_destinations is not None:
        video.upload_destinations = request.upload_destinations
    
    await db.commit()
    await db.refresh(video)
    
    return VideoResponse.model_validate(video)


@router.delete("/{video_id}")
async def delete_video(video_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a video from the hopper"""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Delete file
    file_path = Path(video.file_path)
    if file_path.exists():
        file_path.unlink()
    
    await db.delete(video)
    await db.commit()
    
    return {"status": "success"}


@router.post("/{video_id}/upload")
async def trigger_upload(video_id: int, db: AsyncSession = Depends(get_db)):
    """Manually trigger upload for a video"""
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if not video.upload_destinations:
        raise HTTPException(status_code=400, detail="No destinations selected")
    
    # Get enabled destinations
    result = await db.execute(
        select(Destination).where(
            Destination.id.in_(video.upload_destinations),
            Destination.enabled == True
        )
    )
    destinations = result.scalars().all()
    
    if not destinations:
        raise HTTPException(status_code=400, detail="No enabled destinations")
    
    # Update status
    video.status = "scheduled"
    await db.commit()
    
    # TODO: Queue the upload job
    # This would be handled by a background worker in production
    
    return {"status": "scheduled", "destinations": len(destinations)}

