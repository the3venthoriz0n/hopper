"""Video service - Route entry point with backward compatibility

This module maintains backward compatibility by re-exporting all public functions
from the modularized video service submodules. Route handlers and other code can
continue to import from this module as before.

The actual implementation has been moved to:
- app.services.video.helpers - General helper functions
- app.services.video.file_handler - File upload/streaming
- app.services.video.orchestrator - Background tasks, retries
- app.services.video.settings - Settings management
- app.services.video.platforms.youtube - YouTube uploader
- app.services.video.platforms.tiktok_api - TikTok API client
- app.services.video.platforms.tiktok_uploader - TikTok uploader
- app.services.video.platforms.instagram - Instagram uploader
- app.services.video.config - Configuration constants
"""

# Import and re-export configuration
from app.services.video.config import PLATFORM_CONFIG, TOKEN_REFRESH_LOCK_TIMEOUT, DATA_REFRESH_COOLDOWN

# Import and re-export helper functions
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

# Import and re-export file handling
from app.services.video.file_handler import (
    handle_file_upload,
    delete_video_files,
    serve_video_file,
)

# Import and re-export orchestration
from app.services.video.orchestrator import (
    calculate_scheduled_time,
    upload_all_pending_videos,
    retry_failed_upload,
    cancel_scheduled_videos,
)

# Import and re-export settings management
from app.services.video.settings import (
    recompute_video_title,
    update_video_settings,
    recompute_all_videos_for_platform,
)

# Import and re-export platform uploaders
from app.services.video.platforms.youtube import upload_video_to_youtube
from app.services.video.platforms.tiktok_uploader import upload_video_to_tiktok
from app.services.video.platforms.instagram import upload_video_to_instagram

# Import and re-export TikTok API functions (for backward compatibility)
from app.services.video.platforms.tiktok_api import (
    check_tiktok_rate_limit,
    refresh_tiktok_token,
    get_tiktok_creator_info,
    _ensure_fresh_token,
    _fetch_creator_info_safe,
    fetch_tiktok_publish_status,
    map_privacy_level_to_tiktok,
)

# Destination upload functions registry
DESTINATION_UPLOADERS = {
    "youtube": upload_video_to_youtube,
    "tiktok": upload_video_to_tiktok,
    "instagram": upload_video_to_instagram,
}

# Re-export for backward compatibility
__all__ = [
    # Config
    "PLATFORM_CONFIG",
    "TOKEN_REFRESH_LOCK_TIMEOUT",
    "DATA_REFRESH_COOLDOWN",
    # Helpers
    "format_platform_error",
    "build_upload_context",
    "build_video_response",
    "check_upload_success",
    "get_platform_statuses",
    "record_platform_error",
    "cleanup_video_file",
    "get_video_duration",
    "get_google_client_config",
    # File handling
    "handle_file_upload",
    "delete_video_files",
    "serve_video_file",
    # Orchestration
    "calculate_scheduled_time",
    "upload_all_pending_videos",
    "retry_failed_upload",
    "cancel_scheduled_videos",
    # Settings
    "recompute_video_title",
    "update_video_settings",
    "recompute_all_videos_for_platform",
    # Platform uploaders
    "upload_video_to_youtube",
    "upload_video_to_tiktok",
    "upload_video_to_instagram",
    # TikTok API (for backward compatibility)
    "check_tiktok_rate_limit",
    "refresh_tiktok_token",
    "get_tiktok_creator_info",
    "_ensure_fresh_token",
    "_fetch_creator_info_safe",
    "fetch_tiktok_publish_status",
    "map_privacy_level_to_tiktok",
    # Registry
    "DESTINATION_UPLOADERS",
]
