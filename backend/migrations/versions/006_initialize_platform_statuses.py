"""Initialize platform_statuses for all existing videos

Revision ID: 006
Revises: 005
Create Date: 2026-01-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
import json
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Initialize platform_statuses in custom_settings for all existing videos"""
    conn = op.get_bind()
    
    # Query all videos
    result = conn.execute(text("""
        SELECT id, user_id, status, custom_settings
        FROM videos
    """))
    
    videos = result.fetchall()
    migrated_count = 0
    
    # Import Redis client to check platform progress
    try:
        from app.db.redis import get_redis_client
        redis_client = get_redis_client()
    except Exception as e:
        # If Redis is not available, continue without progress checks
        print(f"Warning: Could not connect to Redis: {e}. Migration will continue without progress checks.")
        redis_client = None
    
    # Import helper to get enabled destinations
    try:
        from app.db.helpers import get_user_settings, get_all_oauth_tokens
        from app.models.oauth_token import OAuthToken
    except ImportError:
        # If imports fail, we'll use a simpler approach
        get_user_settings = None
        get_all_oauth_tokens = None
    
    for video_row in videos:
        video_id = video_row[0]
        user_id = video_row[1]
        global_status = video_row[2]
        custom_settings_json = video_row[3]
        
        try:
            # Parse custom_settings
            if custom_settings_json:
                custom_settings = json.loads(custom_settings_json) if isinstance(custom_settings_json, str) else custom_settings_json
            else:
                custom_settings = {}
            
            # Initialize platform_statuses if not present
            if "platform_statuses" not in custom_settings:
                custom_settings["platform_statuses"] = {}
            
            platform_statuses = custom_settings["platform_statuses"]
            platform_errors = custom_settings.get("platform_errors", {})
            
            # Get enabled destinations for this user
            enabled_destinations = []
            if get_user_settings and get_all_oauth_tokens:
                try:
                    # Create a temporary session to get user settings
                    from app.db.session import SessionLocal
                    db = SessionLocal()
                    try:
                        dest_settings = get_user_settings(user_id, "destinations", db=db)
                        all_tokens = get_all_oauth_tokens(user_id, db=db)
                        
                        for platform_name in ["youtube", "tiktok", "instagram"]:
                            enabled_key = f"{platform_name}_enabled"
                            is_enabled = dest_settings.get(enabled_key, False)
                            has_token = all_tokens.get(platform_name) is not None
                            if is_enabled and has_token:
                                enabled_destinations.append(platform_name)
                    finally:
                        db.close()
                except Exception as e:
                    # If we can't get settings, assume all platforms are enabled
                    enabled_destinations = ["youtube", "tiktok", "instagram"]
            else:
                # Fallback: assume all platforms are enabled
                enabled_destinations = ["youtube", "tiktok", "instagram"]
            
            # Infer platform statuses for each enabled platform
            for platform_name in enabled_destinations:
                if platform_name in platform_statuses:
                    # Already has status, skip
                    continue
                
                # Check platform ID
                has_id = False
                if platform_name == "youtube":
                    has_id = bool(custom_settings.get("youtube_id"))
                elif platform_name == "tiktok":
                    has_id = bool(custom_settings.get("tiktok_id") or custom_settings.get("tiktok_publish_id"))
                elif platform_name == "instagram":
                    has_id = bool(custom_settings.get("instagram_id"))
                
                # Check platform error
                has_error = platform_name in platform_errors
                
                # Check Redis for platform progress (if available)
                has_progress = False
                if redis_client:
                    try:
                        progress_key = f"progress:{user_id}:{video_id}:{platform_name}"
                        progress = redis_client.get(progress_key)
                        if progress:
                            progress_value = int(progress)
                            has_progress = 0 < progress_value < 100
                    except Exception:
                        pass
                
                # Determine platform status based on priority:
                # 1. Error -> failed
                # 2. Progress (0-99) -> uploading
                # 3. ID -> success
                # 4. Global status -> infer
                # 5. Default -> pending
                
                if has_error:
                    platform_statuses[platform_name] = {
                        "status": "failed",
                        "error": platform_errors[platform_name],
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif has_progress:
                    platform_statuses[platform_name] = {
                        "status": "uploading",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif has_id:
                    platform_statuses[platform_name] = {
                        "status": "success",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif global_status == "cancelled":
                    platform_statuses[platform_name] = {
                        "status": "cancelled",
                        "error": "Upload cancelled by user",
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif global_status == "uploading":
                    # If uploading but no progress, check if other platforms have progress
                    # Otherwise, mark as pending (not started yet)
                    platform_statuses[platform_name] = {
                        "status": "pending",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif global_status in ["uploaded", "completed"]:
                    # Video marked as uploaded but no ID for this platform
                    # If no error, it means platform was never attempted
                    platform_statuses[platform_name] = {
                        "status": "pending",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                elif global_status == "failed":
                    # If failed but no error for this platform, it might not have been attempted
                    platform_statuses[platform_name] = {
                        "status": "pending",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    # Default to pending
                    platform_statuses[platform_name] = {
                        "status": "pending",
                        "error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
            
            # Compute global status from platform statuses
            enabled_statuses = [
                platform_statuses.get(platform, {}).get("status", "pending")
                for platform in enabled_destinations
            ]
            
            new_global_status = global_status
            if enabled_statuses:
                if all(s == "success" for s in enabled_statuses):
                    new_global_status = "uploaded"
                elif any(s == "uploading" for s in enabled_statuses):
                    new_global_status = "uploading"
                elif all(s == "failed" for s in enabled_statuses):
                    new_global_status = "failed"
                elif all(s == "cancelled" for s in enabled_statuses):
                    new_global_status = "cancelled"
                elif any(s == "success" for s in enabled_statuses):
                    new_global_status = "partial"
                else:
                    new_global_status = "pending"
            
            # Update custom_settings with platform_statuses
            custom_settings["platform_statuses"] = platform_statuses
            
            # Update video in database
            conn.execute(text("""
                UPDATE videos
                SET custom_settings = :custom_settings,
                    status = :status
                WHERE id = :video_id
            """), {
                "custom_settings": json.dumps(custom_settings),
                "status": new_global_status,
                "video_id": video_id
            })
            
            migrated_count += 1
            
        except Exception as e:
            print(f"Error migrating video {video_id}: {e}")
            continue
    
    conn.commit()
    print(f"Migration completed: {migrated_count} videos migrated")


def downgrade() -> None:
    """Remove platform_statuses from custom_settings"""
    conn = op.get_bind()
    
    # Query all videos with platform_statuses
    result = conn.execute(text("""
        SELECT id, custom_settings
        FROM videos
        WHERE custom_settings::text LIKE '%platform_statuses%'
    """))
    
    videos = result.fetchall()
    
    for video_row in videos:
        video_id = video_row[0]
        custom_settings_json = video_row[1]
        
        try:
            # Parse custom_settings
            if custom_settings_json:
                custom_settings = json.loads(custom_settings_json) if isinstance(custom_settings_json, str) else custom_settings_json
            else:
                custom_settings = {}
            
            # Remove platform_statuses
            if "platform_statuses" in custom_settings:
                del custom_settings["platform_statuses"]
            
            # Update video in database
            conn.execute(text("""
                UPDATE videos
                SET custom_settings = :custom_settings
                WHERE id = :video_id
            """), {
                "custom_settings": json.dumps(custom_settings),
                "video_id": video_id
            })
            
        except Exception as e:
            print(f"Error downgrading video {video_id}: {e}")
            continue
    
    conn.commit()
