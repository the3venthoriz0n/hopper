# Dev Deploy Migration Plan

## Current Setup vs. Proposed Setup

### How Dev Deploy Works Today

```
┌─────────────┐     rsync      ┌───────────────────────────────────────┐
│  Your Mac   │ ──────────────→│ Unraid (dbserver)                     │
│  (source)   │   sync-rsync.sh│                                       │
│             │                 │  /mnt/user/Misc/_DevRemote/hopper_sync│
└─────────────┘                 │       │                               │
                                │       ├── backend/  ← volume mount    │
                                │       ├── frontend/ ← volume mount    │
                                │       ├── nginx/    ← volume mount    │
                                │       └── docker-compose.dev.yml      │
                                │                                       │
                                │  Docker builds images locally on      │
                                │  Unraid from the synced source code   │
                                │                                       │
                                │  Hot reload via CHOKIDAR_USEPOLLING   │
                                └───────────────────────────────────────┘
```

**Flow:** `make up` (or `make sync` + `make up`)
1. `scripts/sync-rsync.sh` rsyncs `backend/`, `frontend/`, `nginx/`, `docker-compose.dev.yml`, `makefile` to Unraid at `/mnt/user/Misc/_DevRemote/hopper_sync`
2. Then you SSH to Unraid (or use docker context) and run `docker compose up -d --build`
3. Containers build from source on Unraid, mount the synced code for hot reload

**Pain points:**
- rsync is flaky (partial syncs, forgotten excludes, stale files)
- Building images on Unraid is slow (low-priority NAS hardware)
- Volume-mounted hot reload requires `CHOKIDAR_USEPOLLING=true` (CPU-hungry on NFS)
- Makefile assumes it's running on Unraid (paths like `/mnt/user/Misc/...`)
- Docker context switching is fragile and confusing
- Dev compose references Unraid-specific absolute paths (not portable)
- No way to test the exact same artifact that would go to prod

---

### Proposed Setup (CI-Deployed via GitHub Actions)

```
┌─────────────┐                  ┌──────────────────────────────────────────┐
│  Your Mac   │                  │ GitHub Actions                           │
│  (source)   │───git push───→  │                                          │
│             │                  │  1. Build backend + frontend images      │
└─────────────┘                  │  2. Push to GHCR with :dev-latest tag   │
                                 │  3. SSH to Unraid                        │
                                 │  4. scp compose + nginx conf             │
                                 │  5. docker compose pull && up -d         │
                                 └──────────────────┬───────────────────────┘
                                                    │
                                                    │ SSH + pull
                                                    ▼
                                 ┌──────────────────────────────────────────┐
                                 │ Unraid                                   │
                                 │                                          │
                                 │  /opt/hopper-dev/                        │
                                 │       ├── docker-compose.dev.yml (scp'd) │
                                 │       ├── .env.dev (scp'd once)          │
                                 │       ├── nginx/dev-hopper.conf (scp'd)  │
                                 │       └── deploy.sh (scp'd)              │
                                 │                                          │
                                 │  No source code. No git repo.            │
                                 │  Just Docker pulling pre-built images.   │
                                 └──────────────────────────────────────────┘
```

**Flow:** `git push origin main`
1. GitHub Actions triggers on push to `main`
2. Builds backend + frontend images, pushes to GHCR with `:dev-latest` tag
3. SSHs to Unraid, scp's compose file + nginx conf + deploy script
4. Runs `deploy.sh dev` on Unraid (same script already used for prod)
5. Containers pull new images and restart

**No manual steps. No Makefile deploy target. No rsync. No code on Unraid. Just `git push`.**

**What changes:**
| Aspect | Before | After |
|--------|--------|-------|
| Trigger | Manual (`make up`) | Automatic (`git push` to main) |
| Where images build | Unraid (slow) | GitHub Actions (free, fast) |
| Source code on Unraid | Yes (rsynced, volume-mounted) | No |
| Hot reload | Yes (polling-based, flaky) | No (push to deploy) |
| Deploy mechanism | rsync + docker build on Unraid | CI builds + SSH pull on Unraid |
| Unraid needs | Docker, build tools, source code | Docker only (just pulls images) |
| Dev/prod parity | Low (dev builds from source, prod from GHCR) | **Identical** (both CI-built, GHCR-hosted) |
| Rollback | Re-rsync old code + rebuild | Re-run previous workflow or pin tag |
| Deploy time | ~2-3 min (rsync + build) | ~3-4 min (CI build + deploy) |
| Manual steps | Multiple | Zero (push and forget) |

---

### What You Lose (and Mitigations)

**Hot reload is gone.** This is the main tradeoff.

- For backend: FastAPI reload is only useful during rapid iteration. For testing a feature end-to-end, the CI deploy cycle is fast enough.
- For frontend: React dev server hot reload was already polling-based over NFS (slow). Better alternative: run `npm start` locally on Mac pointed at the dev backend on Unraid.
- Mitigation: Add a `make dev-local` target that starts the frontend dev server locally and proxies API calls to `hopper-dev.dunkbox.net`.

**Deploy is no longer instant.** CI pipeline takes ~3-4 min. Acceptable for integration testing; use local dev for tight iteration loops.

**Can't deploy without pushing to main.** Mitigation: add `workflow_dispatch` for manual triggers, or support a `dev` branch trigger too.

---

## Implementation Plan

### Step 1: Update docker-compose.dev.yml for image-based deploys

Convert from local builds + volume mounts to GHCR image references:

```yaml
backend:
  image: ${GHCR_IMAGE_BACKEND:-ghcr.io/the3venthoriz0n/hopper/hopper-backend:dev-latest}
  pull_policy: always
  # REMOVE: build: context/dockerfile
  # REMOVE: volumes with /mnt/user/Misc/_DevRemote/...
  # KEEP: env_file, environment, depends_on, ports, networks

frontend:
  image: ${GHCR_IMAGE_FRONTEND:-ghcr.io/the3venthoriz0n/hopper/hopper-frontend:dev-latest}
  pull_policy: always
  # REMOVE: build: context/dockerfile/target/args
  # REMOVE: volumes with /mnt/user/Misc/_DevRemote/...
  # REMOVE: CHOKIDAR_USEPOLLING, WATCHPACK_POLLING
  # KEEP: environment, depends_on, networks

nginx:
  volumes:
    - ./nginx/dev-hopper.conf:/etc/nginx/conf.d/default.conf:ro
    # Relative path — works from /opt/hopper-dev/
```

Monitoring services: also switch to GHCR images (same as prod compose already does).

### Step 2: Update GitHub Actions workflow

Add dev deployment triggered on push to `main`:

```yaml
on:
  push:
    branches: [main]       # → Deploy to dev
  release:
    types: [created]       # → Deploy to prod (existing)
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        default: 'dev'
        type: choice
        options: [dev, prod]
```

In the `build-and-push` job, determine environment from trigger:
- `push` event → `env=dev`, tag images `:dev-latest`
- `release` event → `env=prod`, tag images `:vX.Y.Z` + `:prod-latest`
- `workflow_dispatch` → use selected environment

The deploy job already supports both environments via secrets (`DEV_HOST`, `DEV_SSH_KEY`, `DEV_USER`). The existing `deploy.sh` script handles both `dev` and `prod` arguments.

### Step 3: One-time Unraid setup

```bash
# Create app directory
ssh dbserver "mkdir -p /opt/hopper-dev/nginx /opt/hopper-dev/scripts"

# Authenticate to GHCR (one-time, needs PAT with read:packages)
ssh dbserver "docker login ghcr.io -u the3venthoriz0n"

# Copy .env.dev (one-time, contains secrets — not in CI)
scp .env.dev dbserver:/opt/hopper-dev/.env.dev
```

Everything else (compose file, nginx conf, deploy script) is scp'd by GitHub Actions on every deploy — same as prod already works.

### Step 4: Verify

1. Push a commit to `main`
2. Watch GitHub Actions build + deploy
3. Hit `hopper-dev.dunkbox.net` in browser
4. Confirm all services are up

### Step 5: Cleanup (after confirmed working)

- Delete `scripts/sync-rsync.sh`
- Remove `sync` target from Makefile
- Remove `make up`'s dependency on `sync`
- Clean up `/mnt/user/Misc/_DevRemote/hopper_sync` on Unraid
- Drop docker context configuration
- Remove `CHOKIDAR_USEPOLLING` / `WATCHPACK_POLLING` references

---

## GitHub Actions Changes (Detailed)

The existing workflow already handles:
- Building all images (backend, frontend, monitoring)
- Pushing to GHCR
- SSH deploy to target server
- Running `deploy.sh` with health checks

**What needs to change:**

1. **Trigger:** Add `push: branches: [main]`
2. **Environment detection:** `push` → dev, `release` → prod
3. **Tag strategy:** Dev uses `:dev-latest`, prod keeps `:vX.Y.Z` + `:prod-latest`
4. **Skip tests on dev push (optional):** For faster deploys, skip integration tests on push-to-main (unit tests still run)
5. **Frontend build args:** Dev deploy needs dev URLs baked into the frontend image

The deploy step is already generic — it reads `DEV_HOST`/`DEV_SSH_KEY`/`DEV_USER` secrets and targets `/opt/hopper-dev`.

---

## Optional: Manual Deploy Fallback

For cases where you need to deploy without pushing (debugging, hotfix testing):

```makefile
# Makefile — manual deploy (builds locally, bypasses CI)
deploy-dev-manual: build-dev push-dev
    ssh dbserver "cd /opt/hopper-dev && \
        docker compose -p dev-hopper -f docker-compose.dev.yml pull && \
        docker compose -p dev-hopper -f docker-compose.dev.yml up -d"

build-dev:
    docker build -t ghcr.io/the3venthoriz0n/hopper/hopper-backend:dev-latest ./backend
    docker build --target prod \
        --build-arg REACT_APP_BACKEND_URL=$$(grep BACKEND_URL .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_DOMAIN=$$(grep DOMAIN .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_FRONTEND_URL=$$(grep FRONTEND_URL .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_ENVIRONMENT=development \
        --build-arg REACT_APP_VERSION=dev \
        -t ghcr.io/the3venthoriz0n/hopper/hopper-frontend:dev-latest ./frontend

push-dev:
    docker push ghcr.io/the3venthoriz0n/hopper/hopper-backend:dev-latest
    docker push ghcr.io/the3venthoriz0n/hopper/hopper-frontend:dev-latest
```

This is a backup — the primary flow is `git push` → CI handles everything.

---

## Optional: Local Frontend Dev (fast iteration)

For tight frontend iteration without waiting for CI:

```makefile
dev-local:
    cd frontend && REACT_APP_BACKEND_URL=https://hopper-dev.dunkbox.net/api \
        REACT_APP_ENVIRONMENT=development npm start
```

Runs React dev server on localhost with hot reload, talking to the dev backend on Unraid.

---

## Decision Summary

| Question | Answer |
|----------|--------|
| Deploy trigger | `git push` to `main` (automatic) |
| Build where? | GitHub Actions (same as prod) |
| Registry | GHCR (already using it) |
| Tag strategy | `:dev-latest` for dev, `:vX.Y.Z` for prod |
| Code on Unraid? | No — just Docker, compose file, env, nginx conf |
| Git repo on Unraid? | No — everything delivered via CI scp |
| Hot reload? | No — use `make dev-local` for frontend iteration |
| Monitoring images | Also via GHCR (matches prod) |
| Rollback | Re-run previous workflow, or manual `deploy-dev-manual` |
| Manual fallback | `make deploy-dev-manual` builds locally + pushes |
