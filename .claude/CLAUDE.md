# Hopper

Multi-platform video publishing tool (YouTube, TikTok, Instagram). Upload, schedule, and manage video content from a single interface.

## Tech Stack

- **Backend:** Python 3, FastAPI, SQLAlchemy 2.0, PostgreSQL 16, Redis 7, Alembic
- **Frontend:** React 18, react-router-dom 6, axios, plain JavaScript (no TypeScript)
- **Storage:** Cloudflare R2 (S3-compatible) for video files
- **Auth:** JWT + bcrypt, OAuth2 for platform connections (Google, TikTok, Instagram)
- **Payments:** Stripe (subscriptions + token-based usage)
- **Monitoring:** OpenTelemetry → Prometheus + Loki + Grafana
- **Deploy:** Docker Compose on VPS, GitHub Actions CI, rsync-based deploy

## Architecture

### Backend (`backend/`)
- `app/api/` — FastAPI routers (auth, oauth, videos, subscriptions, admin, websocket)
- `app/services/` — Business logic layer (video orchestration, platform uploaders, stripe, email)
- `app/services/video/platforms/` — Per-platform upload implementations (YouTube, TikTok, Instagram)
- `app/models/` — SQLAlchemy models
- `app/db/` — Session management, Redis helpers, task queue
- `app/tasks/` — Background workers (upload worker, scheduler, cleanup, status checker)
- `app/core/` — Config, middleware, security, logging, OTEL setup

### Frontend (`frontend/`)
- `src/hooks/` — Custom hooks (useVideos, useAuth, useWebSocket, usePlatforms, useSettings, useSubscription)
- `src/components/home/` — Main app UI (destinations, video queue, modals, upload)
- `src/services/` — API client layer
- `src/utils/` — Shared utilities

### Infrastructure
- `docker-compose.dev.yml` / `docker-compose.prod.yml` — Service definitions
- `monitoring/` — Dockerfiles + configs for OTEL, Prometheus, Loki, Grafana
- `nginx/` — Reverse proxy configs (dev/prod)
- `scripts/` — Deploy, SSL, backup scripts

## Development

- Backend tests: `cd backend && pytest`
- Frontend tests: `cd frontend && npm test`
- Dev environment: `docker-compose -f docker-compose.dev.yml up`
- Migrations: `cd backend && alembic upgrade head`

## Conventions

- Backend follows service-layer pattern: routers → services → db helpers
- Frontend state managed via custom hooks, no external state library
- Real-time updates via WebSocket (Redis pub/sub → WebSocket manager → client)
- Video uploads go client → R2 (presigned URLs), then backend orchestrates platform distribution
- Token-based usage metering (tokens deducted per upload based on file size)

## Architecture Improvement Plan

See `architecture-plan.md` in this directory for the phased improvement roadmap.
