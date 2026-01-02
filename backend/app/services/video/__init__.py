"""Video service module - public API exports"""

# Import registry
from app.services.video.registry import DESTINATION_UPLOADERS

# Re-export all public functions from submodules
from app.services.video.helpers import (
    format_platform_error,
    build_upload_context,
    build_video_response,
    check_upload_success,
    get_platform_statuses,
    record_platform_error,
    cleanup_video_file,
    get_video_duration,
    get_google_client_config,
)

from app.services.video.file_handler import (
    handle_file_upload,
    delete_video_files,
    serve_video_file,
)

from app.services.video.orchestrator import (
    calculate_scheduled_time,
    upload_all_pending_videos,
    retry_failed_upload,
    cancel_scheduled_videos,
)

from app.services.video.settings import (
    recompute_video_title,
    update_video_settings,
    recompute_all_videos_for_platform,
)

from app.services.video.platforms.tiktok_api import (
    _ensure_fresh_token,
    _fetch_creator_info_safe,
    _parse_and_save_tiktok_token_response,
)

# Re-export platform uploaders
from app.services.video.platforms.youtube import upload_video_to_youtube
from app.services.video.platforms.tiktok_uploader import upload_video_to_tiktok
from app.services.video.platforms.instagram import upload_video_to_instagram

__all__ = [
    "DESTINATION_UPLOADERS",
    "upload_video_to_youtube",
    "upload_video_to_tiktok",
    "upload_video_to_instagram",
    "format_platform_error",
    "build_upload_context",
    "build_video_response",
    "check_upload_success",
    "get_platform_statuses",
    "record_platform_error",
    "cleanup_video_file",
    "get_video_duration",
    "get_google_client_config",
    "handle_file_upload",
    "delete_video_files",
    "serve_video_file",
    "calculate_scheduled_time",
    "upload_all_pending_videos",
    "retry_failed_upload",
    "cancel_scheduled_videos",
    "recompute_video_title",
    "update_video_settings",
    "recompute_all_videos_for_platform",
    "_ensure_fresh_token",
    "_fetch_creator_info_safe",
    "_parse_and_save_tiktok_token_response",
]
