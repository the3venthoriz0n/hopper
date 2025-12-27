"""Platform uploader registry"""

from app.services.video.platforms.youtube import upload_video_to_youtube
from app.services.video.platforms.tiktok_uploader import upload_video_to_tiktok
from app.services.video.platforms.instagram import upload_video_to_instagram

DESTINATION_UPLOADERS = {
    "youtube": upload_video_to_youtube,
    "tiktok": upload_video_to_tiktok,
    "instagram": upload_video_to_instagram,
}

