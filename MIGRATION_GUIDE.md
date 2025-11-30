# Hopper Backend Migration Guide: File-Based Sessions → Database + Redis

## Overview
This guide documents the complete migration from file-based sessions to a proper multi-user database-backed system.

## ✅ Already Completed

### 1. Database Infrastructure
- ✅ `models.py` - User, Video, Setting, OAuthToken models
- ✅ `auth.py` - Password hashing, user authentication
- ✅ `redis_client.py` - Session management
- ✅ `db_helpers.py` - Database operations for settings, videos, OAuth tokens
- ✅ `encryption.py` - OAuth token encryption using Fernet

### 2. Authentication Endpoints
- ✅ `/api/auth/register` - Creates user, stores in DB, creates Redis session
- ✅ `/api/auth/login` - Authenticates user, creates Redis session  
- ✅ `/api/auth/logout` - Deletes Redis session
- ✅ `/api/auth/me` - Returns current user from session

### 3. Frontend
- ✅ Login component integrated into App.js
- ✅ Auth state management
- ✅ 401 error handling with redirect

### 4. Configuration
- ✅ ENCRYPTION_KEY added to docker-compose and env.example
- ✅ Database and Redis already in docker-compose

## 🔄 Migration Pattern

### OLD (File-Based Session):
```python
@app.get("/api/videos")
def get_videos(session_id: str = Depends(get_or_create_session)):
    session = get_session(session_id)  # File-based dict
    videos = session["videos"]
    settings = session["global_settings"]
    return videos
```

### NEW (Database-Backed):
```python
@app.get("/api/videos")
def get_videos(user_id: int = Depends(require_auth)):
    videos = db_helpers.get_user_videos(user_id)
    return [video_to_dict(v) for v in videos]
```

## 📋 Endpoints to Migrate

### Settings Endpoints (4)
1. `GET /api/global/settings` - Use `db_helpers.get_user_settings(user_id, "global")`
2. `POST /api/global/settings` - Use `db_helpers.set_user_setting(user_id, "global", key, value)`
3. `GET /api/youtube/settings` - Use `db_helpers.get_user_settings(user_id, "youtube")`
4. `POST /api/youtube/settings` - Use `db_helpers.set_user_setting(user_id, "youtube", key, value)`
5. `GET /api/tiktok/settings` - Use `db_helpers.get_user_settings(user_id, "tiktok")`
6. `POST /api/tiktok/settings` - Use `db_helpers.set_user_setting(user_id, "tiktok", key, value)`
7. `GET /api/instagram/settings` - Use `db_helpers.get_user_settings(user_id, "instagram")`
8. `POST /api/instagram/settings` - Use `db_helpers.set_user_setting(user_id, "instagram", key, value)`

### Video Endpoints (7)
1. `POST /api/videos` - Use `db_helpers.add_user_video()`
2. `GET /api/videos` - Use `db_helpers.get_user_videos()`
3. `DELETE /api/videos/{id}` - Use `db_helpers.delete_video()`
4. `PATCH /api/videos/{id}` - Use `db_helpers.update_video()`
5. `POST /api/videos/reorder` - Update video order in DB
6. `POST /api/videos/{id}/recompute-title` - Update in DB
7. `POST /api/videos/cancel-scheduled` - Update status in DB

### OAuth Endpoints (9) 
1. `GET /api/auth/youtube` - ✅ Already updated to use require_auth
2. `GET /api/auth/youtube/callback` - ✅ Need to complete (save to DB)
3. `POST /api/auth/youtube/disconnect` - Use `db_helpers.delete_oauth_token()`
4. `GET /api/auth/youtube/account` - Use `db_helpers.get_oauth_token()` + API call
5. `GET /api/auth/tiktok` - Same pattern as YouTube
6. `GET /api/auth/tiktok/callback` - Save to DB with encryption
7. `POST /api/auth/tiktok/disconnect` - Use `db_helpers.delete_oauth_token()`
8. `GET /api/auth/instagram` - Same pattern as YouTube
9. `GET /api/auth/instagram/callback` - Save to DB with encryption
10. `POST /api/auth/instagram/disconnect` - Use `db_helpers.delete_oauth_token()`

### Destination Toggle Endpoints (3)
1. `POST /api/destinations/youtube/toggle` - Use `db_helpers.set_user_setting(user_id, "destinations", "youtube_enabled", value)`
2. `POST /api/destinations/tiktok/toggle` - Same pattern
3. `POST /api/destinations/instagram/toggle` - Same pattern

### Wordbank Endpoints (3)
1. `POST /api/global/wordbank` - Get wordbank list, append, save back
2. `DELETE /api/global/wordbank/{word}` - Get list, remove, save back
3. `DELETE /api/global/wordbank` - Set to empty list

### Upload Endpoint (1)
1. `POST /api/upload` - Most complex, needs to:
   - Get user's videos from DB
   - Get user's settings from DB
   - Get OAuth tokens from DB (decrypt)
   - Upload to platforms
   - Update video status in DB

## 🗑️ Code to Remove

### 1. Global Variables
```python
sessions = {}  # Line ~568 - REMOVE
SESSIONS_DIR = Path("sessions")  # Line ~560 - REMOVE (keep UPLOAD_DIR)
```

### 2. Functions to Remove
```python
def get_session(session_id: str)  # Line ~631
def save_session(session_id: str)  # Line ~661  
def load_session(session_id: str)  # Line ~687
def get_or_create_session_id(...)  # Line ~678
def get_default_global_settings()  # Move to db_helpers
def get_default_youtube_settings()  # Move to db_helpers
def get_default_tiktok_settings()  # Move to db_helpers
def get_default_instagram_settings()  # Move to db_helpers
```

### 3. Old Dependencies
Replace all occurrences:
- `Depends(get_or_create_session)` → `Depends(require_auth)`
- `Depends(require_session)` → `Depends(require_auth)`
- `Depends(require_csrf)` → `Depends(require_csrf_new)`

## 🔐 OAuth Token Storage Pattern

### Saving (Encrypt):
```python
# After OAuth callback, get credentials
creds = flow.credentials

# Convert to token data
token_data = db_helpers.credentials_to_oauth_token_data(
    creds, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
)

# Save (automatically encrypted)
db_helpers.save_oauth_token(
    user_id=user_id,
    platform="youtube",  # or "tiktok", "instagram"
    access_token=token_data["access_token"],
    refresh_token=token_data["refresh_token"],
    expires_at=token_data["expires_at"],
    extra_data=token_data["extra_data"]
)
```

### Loading (Decrypt):
```python
# Get token from DB
token = db_helpers.get_oauth_token(user_id, "youtube")

# Convert to Credentials object (automatically decrypted)
creds = db_helpers.oauth_token_to_credentials(token)

# Use with Google API
youtube = build('youtube', 'v3', credentials=creds)
```

## 🚀 Testing Checklist

After migration:
1. [ ] Register new user
2. [ ] Login/logout
3. [ ] Connect YouTube OAuth
4. [ ] Connect TikTok OAuth  
5. [ ] Connect Instagram OAuth
6. [ ] Upload video with settings
7. [ ] Create second user
8. [ ] Verify data isolation (user 1 can't see user 2's data)
9. [ ] Test video queue per-user
10. [ ] Test settings per-user

## 📝 Notes

- All OAuth tokens are encrypted at rest using Fernet (cryptography library)
- ENCRYPTION_KEY must be set in production (see env.example)
- Sessions use Redis for fast access
- User data (videos, settings, OAuth) stored in PostgreSQL
- No backwards compatibility needed - clean migration

## 🎯 Priority Order

1. **High Priority** - Core functionality:
   - Video endpoints (upload, list, delete)
   - Settings endpoints (global, youtube, tiktok, instagram)
   - OAuth callback completion (save to DB)

2. **Medium Priority** - OAuth flows:
   - Complete YouTube/TikTok/Instagram callbacks
   - Disconnect endpoints
   - Account info endpoints

3. **Low Priority** - Nice to have:
   - Video reordering
   - Wordbank management
   - Upload progress tracking (can stay in Redis)

