# Migration Progress Update

## ✅ Completed Endpoints (15/43 = 35%)

### Authentication (4/4) ✅
- POST `/api/auth/register` ✅
- POST `/api/auth/login` ✅
- POST `/api/auth/logout` ✅
- GET `/api/auth/me` ✅
- GET `/api/auth/csrf` ✅ NEW

### YouTube OAuth (4/5) ✅
- GET `/api/auth/youtube` ✅ Migrated
- GET `/api/auth/youtube/callback` ✅ Migrated (saves to DB encrypted)
- GET `/api/auth/youtube/account` ✅ Migrated (loads from DB)
- POST `/api/auth/youtube/disconnect` ✅ Migrated

### Destination Management (4/4) ✅
- GET `/api/destinations` ✅ Migrated
- POST `/api/destinations/youtube/toggle` ✅ Migrated
- POST `/api/destinations/tiktok/toggle` ✅ Migrated
- POST `/api/destinations/tiktok/toggle` ✅ Migrated

### Wordbank (3/3) ✅
- POST `/api/global/wordbank` ✅ Migrated
- DELETE `/api/global/wordbank/{word}` ✅ Migrated
- DELETE `/api/global/wordbank` ✅ Migrated

### TikTok OAuth (1/5) 🔄
- GET `/api/auth/tiktok` ✅ Migrated
- GET `/api/auth/tiktok/callback` ⚠️ TODO
- GET `/api/auth/tiktok/account` ⚠️ TODO  
- POST `/api/auth/tiktok/disconnect` ⚠️ TODO

## 🚧 Remaining Endpoints (28/43 = 65%)

### Settings Endpoints (8) ⚠️
- GET `/api/global/settings` - Use `db_helpers.get_user_settings(user_id, "global")`
- POST `/api/global/settings` - Use `db_helpers.set_user_setting(user_id, "global", key, value)`
- GET `/api/youtube/settings` - Use `db_helpers.get_user_settings(user_id, "youtube")`
- POST `/api/youtube/settings` - Use `db_helpers.set_user_setting(user_id, "youtube", key, value)`
- GET `/api/tiktok/settings` - Use `db_helpers.get_user_settings(user_id, "tiktok")`
- POST `/api/tiktok/settings` - Use `db_helpers.set_user_setting(user_id, "tiktok", key, value)`
- GET `/api/instagram/settings` - Use `db_helpers.get_user_settings(user_id, "instagram")`
- POST `/api/instagram/settings` - Use `db_helpers.set_user_setting(user_id, "instagram", key, value)`

### Video Endpoints (7) ⚠️
- POST `/api/videos` - Use `db_helpers.add_user_video()`
- GET `/api/videos` - Use `db_helpers.get_user_videos()`
- DELETE `/api/videos/{id}` - Use `db_helpers.delete_video()`
- PATCH `/api/videos/{id}` - Use `db_helpers.update_video()`
- POST `/api/videos/reorder` - Update order in DB
- POST `/api/videos/{id}/recompute-title` - Update in DB
- POST `/api/videos/cancel-scheduled` - Update status in DB

### TikTok OAuth (4) ⚠️
- GET `/api/auth/tiktok/callback` - Same pattern as YouTube callback
- GET `/api/auth/tiktok/account` - Same pattern as YouTube account
- POST `/api/auth/tiktok/disconnect` - Use `db_helpers.delete_oauth_token()`

### Instagram OAuth (5) ⚠️
- GET `/api/auth/instagram` - Same pattern as YouTube
- GET `/api/auth/instagram/callback` - Same pattern as YouTube callback
- POST `/api/auth/instagram/complete` - Custom endpoint, update similarly
- GET `/api/auth/instagram/account` - Same pattern as YouTube account
- POST `/api/auth/instagram/disconnect` - Use `db_helpers.delete_oauth_token()`

### Upload Endpoint (1) ⚠️
- POST `/api/upload` - **COMPLEX** - Needs to:
  - Get user's videos from DB
  - Get user's settings from DB
  - Get OAuth tokens from DB (decrypt)
  - Upload to platforms
  - Update video status in DB

### Other (1) ⚠️
- GET `/api/youtube/videos` - List user's YouTube videos (uses OAuth token)

## 🎯 Next Priority

1. **Settings Endpoints** (8 endpoints) - Simple, repetitive pattern
2. **Video Endpoints** (7 endpoints) - Core functionality
3. **TikTok OAuth Completion** (4 endpoints) - Follow YouTube pattern
4. **Instagram OAuth** (5 endpoints) - Follow YouTube pattern
5. **Upload Endpoint** (1 endpoint) - Most complex, do last

## 📋 Pattern Examples

### Settings Pattern
```python
@app.get("/api/global/settings")
def get_global_settings(user_id: int = Depends(require_auth)):
    return db_helpers.get_user_settings(user_id, "global")

@app.post("/api/global/settings")
def update_global_settings(key: str, value: str, user_id: int = Depends(require_csrf_new)):
    # Parse value if it's JSON
    try:
        parsed_value = json.loads(value)
    except:
        parsed_value = value
    
    db_helpers.set_user_setting(user_id, "global", key, parsed_value)
    return db_helpers.get_user_settings(user_id, "global")
```

### Video Pattern
```python
@app.get("/api/videos")
def get_videos(user_id: int = Depends(require_auth)):
    videos = db_helpers.get_user_videos(user_id)
    settings = db_helpers.get_user_settings(user_id, "global")
    
    # Convert SQLAlchemy objects to dicts with computed fields
    result = []
    for video in videos:
        video_dict = {
            "id": video.id,
            "filename": video.filename,
            "path": video.path,
            "status": video.status,
            "generated_title": video.generated_title,
            "custom_settings": video.custom_settings or {},
            "error": video.error,
            "created_at": video.created_at.isoformat() if video.created_at else None
        }
        result.append(video_dict)
    
    return result
```

## 💪 You're Doing Great!

- Foundation: 100% ✅
- Auth System: 100% ✅  
- OAuth Infrastructure: 100% ✅
- Endpoints: 35% ✅

**Remaining work is systematic and repetitive!**

