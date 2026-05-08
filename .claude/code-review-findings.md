# Code Review Findings

Comprehensive review of the hopper codebase. Findings organized by severity and area.

---

## High Priority (Bugs, Performance, Dead Code)

### N+1 Query / Performance

| File | Line | Issue |
|------|------|-------|
| `backend/app/services/token_service.py` | 188-197 | `check_tokens_available` with `include_queued_videos=True` iterates all user videos in Python instead of using the DB aggregate already implemented in `get_queue_token_count` (lines 122-148) |
| `frontend/src/hooks/useVideos.js` | 92 | `JSON.stringify(prevVideos) === JSON.stringify(uniqueData)` — O(n) serialization on every load/WebSocket update |

### Dead Code

| File | Line | Issue |
|------|------|-------|
| `backend/app/db/helpers.py` | 347-353 | `get_oauth_token` checks Redis cache but never uses the result — falls through with `pass` |
| `backend/app/db/helpers.py` | 611-617 | TikTok branch in `check_token_expiration` is unreachable (already handled at line 521) |
| `backend/app/db/redis.py` | 82-91 | Rate limit dev/prod conditional sets identical values in both branches |
| `backend/app/db/redis.py` | 414-415, 356-358 | `if env != "test": pass` blocks do nothing |
| `backend/app/services/video/helpers.py` | 9-10 | Duplicate imports inside `TYPE_CHECKING` guard (also imported unconditionally at lines 19-20) |
| `backend/app/tasks/status_checker.py` | 18 | `flag_modified` imported but never used |
| `backend/app/tasks/status_checker.py` | 185 | `publish_video_updated` re-imported inline (already at top-level line 12) |
| `backend/app/tasks/cleanup.py` | 8 | `get_all_scheduled_videos` imported but never called |
| `frontend/src/hooks/useSubscription.js` | 13 | `availablePlans` parameter is never used |
| `frontend/src/services/videoService.js` | 97-103 | `cancelR2Upload` kept for "backward compatibility" but may be dead |

### Silent Error Suppression

| File | Line | Issue |
|------|------|-------|
| `backend/app/core/security.py` | 59 | Bare `except: pass` suppresses all exceptions from reading form data |
| `backend/app/db/helpers.py` | 405-410 | Unconditional `db.rollback()` in try/except at start of `save_oauth_token` masks issues |

---

## Medium Priority (Duplication, Complexity)

### Massive Functions (>100 lines)

| File | Function | Lines | Recommendation |
|------|----------|-------|----------------|
| `backend/app/tasks/scheduler.py` | `scheduler_task` | ~350 | Extract retry/session-recovery into a context manager |
| `backend/app/services/video/helpers.py` | `build_video_response` | 175 | Drive YouTube/TikTok/Instagram blocks from a config dict |
| `backend/app/services/token_service.py` | `ensure_tokens_synced_for_subscription` | 220 | Extract `_make_aware(dt)` helper for 4 duplicated tz blocks |
| `backend/app/services/video/file_handler.py` | `delete_video_files` | 90 | Split into guard/cancel/delete/publish phases |
| `frontend/src/components/home/Home.js` | `handleWebSocketMessage` | 145 | Extract per-event-type handlers |

### Copy-Paste Duplication

| Location | Pattern | Fix |
|----------|---------|-----|
| `db/helpers.py` (15+ functions) | `should_close = False; if db is None: db = SessionLocal()...` | Extract `@with_session` decorator or context manager |
| `db/helpers.py:62-76` + `208-220` | `global_defaults` dict duplicated | Module-level `GLOBAL_DEFAULTS` constant |
| `db/helpers.py:78-91` + `222-235` | Wordbank override + boolean normalization duplicated | Extract into shared helper |
| `token_service.py:217-374` + `377-476` | `deduct_tokens` / `add_tokens` share ~40 lines of boilerplate | Extract `_modify_balance(user_id, amount, ...)` |
| `token_service.py:885-953` | Timezone coercion block copy-pasted 4x | `_make_aware(dt)` helper |
| `video/helpers.py:85-89` + `543-548` | `enabled_destinations` loop duplicated | Extract to utility |
| `video/helpers.py:167-248` | Title truncation `[:100]` pattern repeated 3x | `truncate(s, n)` one-liner |
| `file_handler.py:396-472` | Presigned + multipart upload share identical validation prefix | Extract `_validate_and_generate_key(...)` |
| `scheduler.py` (8 locations) | `try: ... except: db.close(); db = SessionLocal()` retry pattern | `with fresh_session() as db` helper |
| `status_checker.py:122-129` + `405-412` | `enabled_destinations` builder duplicated from scheduler | Shared helper (same as helpers.py fix) |
| `status_checker.py:430-447` + `136-154` | Token deduction + update_video duplicated for TikTok/Instagram | Extract `_deduct_and_record(...)` |
| `frontend/src/services/videoService.js` (10+ functions) | CSRF + axios call boilerplate repeated | `withCsrf(payload)` helper |
| `frontend/src/services/videoService.js:512-678` | Cancellation check pattern repeated 4x in `uploadToR2Multipart` | `checkAndThrowIfCancelled(videoId, listener)` |
| `frontend/src/hooks/useSettings.js:10-64` | Default settings objects duplicated between useState and loader | `DEFAULT_GLOBAL_SETTINGS` constant |

### Inconsistent Patterns

| File | Issue |
|------|-------|
| `backend/app/services/video/file_handler.py` | ~15 deferred imports scattered inside function bodies instead of top-level |
| `backend/app/core/config.py:119-131` | Module-level constant aliases (`ENVIRONMENT`, `TIKTOK_AUTH_URL`, etc.) duplicate `settings.*` with no benefit |
| `backend/app/services/stripe_service.py` | Emoji in log strings (✓, ⚠, 🔍, ❌) — inconsistent with rest of codebase, can break log aggregators |
| `frontend/src/hooks/usePlatforms.js` | `loadPlatformAccount` abstraction exists but `loadTiktokAccount` re-implements it inline |
| `frontend/src/hooks/useSubscription.js` | Error handling mixes `setMessage` and `setNotification` with no consistent rule |

---

## Low Priority (Style, Minor Cleanup)

### Frontend Render Performance

| File | Line | Issue |
|------|------|-------|
| `frontend/src/hooks/useAuth.js` | 14, 33 | `const API = getApiUrl()` recomputed every render, listed as useCallback dep — causes infinite recreation |
| `frontend/src/hooks/usePlatforms.js` | 207-209 | `toggleYoutube/Tiktok/Instagram` capture platform state in closure, never stable across renders |
| `frontend/src/components/home/Home.js` | 404-421 | `displayMessage` uses useState + useEffect to sync — should be a single `useMemo` |
| `frontend/src/components/home/Home.js` | 529-532 | `videos.some(...)` + `videos.filter(...).length` traverses array twice |
| `frontend/src/components/home/Home.js` | 563-564 | Raw `axios` instance + `API` passed as props to component |

### Backend Minor

| File | Line | Issue |
|------|------|-------|
| `backend/app/db/redis.py:607-674` | `get_active_user_ids` is subset of `get_active_users_with_timestamps` — should delegate |
| `backend/app/db/redis.py:599, 604, 656` | `from datetime import datetime, timezone` imported locally in multiple spots — should be top-level |
| `backend/app/core/middleware.py:48` | `get_allowed_origins()` recomputed from scratch on every request |
| `backend/app/services/stripe_service.py:843` | `handle_subscription_updated` stub delegates entirely to `handle_subscription_created` — add comment or merge |
| `backend/app/tasks/scheduler.py:190, 309` | Emoji in log strings |

---

## Recommended Cleanup Order

**Phase 1: Quick wins (dead code, unused imports, dead branches)**
- Delete dead imports in status_checker, cleanup, helpers
- Remove the no-op Redis rate limit conditional
- Remove the no-op `if env != "test": pass` blocks
- Fix the `get_oauth_token` cache check that does nothing

**Phase 2: Extract shared patterns (biggest maintainability improvement)**
- `@with_session` decorator for db/helpers.py (eliminates ~60 lines of boilerplate)
- `GLOBAL_DEFAULTS` constant (eliminates 2 copies)
- `_validate_and_generate_key()` in file_handler.py
- `_make_aware(dt)` in token_service.py
- `enabled_destinations` builder as a shared utility

**Phase 3: Break up large functions**
- `scheduler_task` → extract retry/session-recovery helper
- `build_video_response` → config-driven platform property builder
- `handleWebSocketMessage` → per-event-type handlers

**Phase 4: Frontend stabilization**
- Fix `useAuth` API reference causing callback churn
- Remove `JSON.stringify` equality check in `useVideos`
- Extract `displayMessage` as `useMemo`
- Remove dead `availablePlans` parameter from `useSubscription`
