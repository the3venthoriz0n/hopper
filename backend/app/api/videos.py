"""Videos API routes"""
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session
from app.core.security import require_auth, require_csrf_new
from app.db.session import get_db
from app.services.video_service import get_user_videos, get_video, delete_video

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("")
def list_videos(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get all videos for current user"""
    videos = get_user_videos(user_id, db)
    return {"videos": [{"id": v.id, "filename": v.filename, "status": v.status} for v in videos]}


@router.get("/{video_id}")
def get_video_by_id(
    video_id: int,
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get a specific video"""
    video = get_video(video_id, user_id, db)
    if not video:
        raise HTTPException(404, "Video not found")
    return {"video": {"id": video.id, "filename": video.filename, "status": video.status}}


@router.delete("/{video_id}")
def delete_video_by_id(
    video_id: int,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Delete a video"""
    if not delete_video(video_id, user_id, db):
        raise HTTPException(404, "Video not found")
    return {"message": "Video deleted successfully"}


@router.post("")
async def upload_video(
    file: UploadFile = File(...),
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Upload a video file"""
    # Placeholder - full implementation would handle file upload
    raise HTTPException(501, "Video upload not yet implemented in new structure")

