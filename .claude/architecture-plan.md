# Architecture Improvement Plan

Phased roadmap for modernizing Hopper's architecture. Goal: proactive quality pass with multi-node readiness, starting from infrastructure/deployment.

---

## Phase A: Infrastructure & Deployment Consolidation

**Priority: HIGH — addresses deployment pain and unblocks multi-node**

### A1. Unify dev/prod monitoring configs
- Replace 6 monitoring Dockerfiles (`Dockerfile.otel.dev`, `Dockerfile.otel.prod`, etc.) with single Dockerfiles using build args
- Consolidate duplicated YAML configs (loki, otel, prometheus) into templates with env var substitution
- Merge dev/prod Grafana datasource YAMLs (differ only by hostname)
- **Result:** ~50% fewer config files, single source of truth per service

### A2. Add health checks to all services
- Add `healthcheck` directives to docker-compose for postgres, redis, backend, frontend, nginx
- Use `depends_on.condition: service_healthy` instead of bare `depends_on`
- Add `/health` endpoint to backend (already has `/api/monitoring` but needs a lightweight liveness probe)
- **Result:** Reliable startup ordering, self-healing restarts

### A3. Replace nginx + certbot scripts with auto-TLS proxy
- Replace `nginx/` configs + `scripts/setup-ssl.sh` + `scripts/setup-ssl-renewal.sh` + `scripts/deploy-ssl-certs.sh` with Traefik or Caddy
- Automatic Let's Encrypt cert provisioning and renewal
- Simpler routing config (labels on containers vs nginx conf files)
- **Result:** Delete 5+ scripts/configs, zero-touch SSL

### A4. Atomic deploys with rollback
- Replace rsync-based `scripts/deploy.sh` with image-pull + compose up pattern
- Tag images with git SHA, keep last N images for instant rollback
- Add a simple deploy script: pull → health check new containers → swap → drain old
- **Result:** Zero-downtime deploys, easy rollback

### A5. Docker Swarm preparation (multi-node path)
- Structure compose files to be Swarm-compatible (add `deploy:` blocks with replicas, resources, restart_policy)
- Move secrets from `.env.prod` to Docker secrets
- Ensure all services are stateless (they already are — state lives in Postgres/Redis/R2)
- **Result:** `docker stack deploy` becomes a viable upgrade path without new tooling

---

## Phase B: Backend Worker Separation & Resilience

**Priority: MEDIUM — required for multi-node, improves reliability**

### B1. Separate worker process from API
- Create `worker.py` entry point that runs: upload_worker, scheduler, status_checker, cleanup
- API process only handles HTTP requests + WebSocket connections
- Both share the same codebase, different CMD in Dockerfile
- **Result:** Scale API and workers independently, worker crash doesn't kill API

### B2. Move cancellation flags to Redis
- Replace `_cancellation_flags: Dict[int, bool] = {}` with Redis keys
- Pattern: `upload:cancel:{video_id}` with short TTL
- Check Redis before each platform upload (already done for R2 — extend to destinations)
- **Result:** Cancellation works across multiple worker instances

### B3. Deduplicate orchestrator logic
- Extract shared `_execute_upload_to_platforms(video_id, user_id, platforms, db)` core
- Both `_upload_single_video_to_destinations` and `retry_failed_upload` call it
- Parameterize: which platforms to target, whether to check tokens, whether to reset status
- **Result:** Orchestrator drops from 809 → ~500 lines, single place to fix upload bugs

### B4. Unify async platform interface
- Make `BasePlatformUploader.upload()` async
- Convert YouTube and TikTok uploaders to async (wrap sync HTTP calls in httpx.AsyncClient)
- Remove special-casing in orchestrator (`if dest_name == "instagram": await`)
- **Result:** Consistent interface, simpler orchestrator, easier to add new platforms

### B5. Split db/helpers.py
- `db/settings.py` — get/set user settings, cache logic
- `db/videos.py` — video CRUD, query helpers
- `db/oauth.py` — token storage, refresh, encryption
- Keep `db/helpers.py` as a thin re-export layer for backward compat during migration
- **Result:** Focused modules, easier to test, clearer ownership

---

## Phase C: Frontend Modernization

**Priority: LOW-MEDIUM — quality of life, developer experience**

### C1. Migrate CRA → Vite
- Replace `react-scripts` with Vite (actively maintained, 10-50x faster builds)
- Update build scripts in package.json
- Migrate jest config to vitest (same API, works with Vite)
- **Result:** Faster dev server, faster CI builds, maintained toolchain

### C2. Split useVideos hook
- `useVideoUpload` — R2 upload logic, progress tracking, multipart handling
- `useVideoQueue` — CRUD operations, reorder, state management
- `useVideoActions` — upload-to-destinations, retry, cancel, scheduling
- `useVideos` becomes a thin orchestrator that composes the three
- **Result:** Each hook is <300 lines, testable in isolation

### C3. Add TypeScript incrementally
- Start with `src/services/` (API client layer) — define response types
- Then `src/hooks/` — type the hook parameters and return values
- Then components (can be gradual, .js and .tsx coexist)
- **Result:** Catch API contract drift at build time, better IDE support

### C4. Fix performance anti-patterns
- Replace `JSON.stringify` equality check in `loadVideos` with shallow comparison or remove it (React handles this)
- Memoize `build_video_response` results on the backend to reduce payload processing
- Consider `useSyncExternalStore` for WebSocket state instead of manual setState
- **Result:** Smoother UI with large video queues

---

## Execution Order

```
A1 (configs) → A2 (health checks) → A3 (auto-TLS) → A4 (deploys) → A5 (swarm prep)
                                                                          ↓
B1 (workers) → B2 (cancel flags) → B3 (dedup orchestrator) → B4 (async) → B5 (split helpers)
                                                                          ↓
C1 (vite) → C2 (split hooks) → C3 (typescript) → C4 (perf)
```

Each step is independently shippable. No step requires completing the full phase before providing value.

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-08 | Keep full monitoring stack | User actively uses dashboards, values self-hosted observability |
| 2026-05-08 | Target multi-node (Docker Swarm path) | Want horizontal scaling without new tooling |
| 2026-05-08 | Start with infrastructure | User-identified pain area, prerequisite for B-phase |
