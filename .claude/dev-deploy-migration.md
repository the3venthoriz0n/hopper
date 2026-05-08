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

### Proposed Setup (Image-Based via GHCR)

```
┌─────────────┐   docker build   ┌────────┐   docker push   ┌──────────────────┐
│  Your Mac   │ ────────────────→│  GHCR  │←────────────────│ GitHub Actions   │
│  (source)   │   :dev tag       │        │  :prod tag       │ (on release)     │
└─────────────┘                   └────┬───┘                  └──────────────────┘
       │                               │
       │ ssh: pull + up                 │ pull
       ▼                               ▼
┌───────────────────────────────────────────────────────────────┐
│ Unraid                                                        │
│                                                               │
│  /opt/hopper-dev/                                             │
│       ├── docker-compose.dev.yml  (uses image: tags)          │
│       ├── .env.dev                                            │
│       └── (no source code on Unraid at all)                   │
│                                                               │
│  Containers run pre-built images from GHCR                    │
│  Identical mechanism to prod (different tag + env)            │
└───────────────────────────────────────────────────────────────┘
```

**Flow:** `make deploy-dev`
1. Build backend + frontend images locally on Mac (fast, Apple Silicon)
2. Push to GHCR with `:dev` tag
3. SSH to Unraid: `docker compose pull && docker compose up -d`

**What changes:**
| Aspect | Before | After |
|--------|--------|-------|
| Where images build | Unraid (slow) | Your Mac (fast) |
| Source code on Unraid | Yes (rsynced, volume-mounted) | No |
| Hot reload | Yes (polling-based, flaky) | No (rebuild + push for changes) |
| Deploy mechanism | rsync + docker build on Unraid | docker push + docker pull on Unraid |
| Unraid needs | Docker, build tools, source code | Docker only (just pulls images) |
| Dev/prod parity | Low (dev builds from source, prod from GHCR) | High (both pull from GHCR) |
| Rollback | Re-rsync old code + rebuild | `docker compose pull` with previous tag |
| Deploy time | ~2-3 min (rsync + build) | ~1-2 min (build + push + pull) |
| Compose file | Hardcoded Unraid paths | Portable (just image refs + env) |

---

### What You Lose (and Mitigations)

**Hot reload is gone.** This is the main tradeoff.

- For backend: FastAPI reload is only useful during rapid iteration. For testing a feature end-to-end, rebuilding the image is fine (incremental Docker builds are fast — only the `COPY app/` layer changes).
- For frontend: React dev server hot reload was already polling-based over NFS (slow). Alternative: run `npm start` locally on Mac for frontend dev, pointed at the dev backend on Unraid. Deploy the built image when ready to test in the full stack.
- Mitigation: Add a `make dev-local` target that starts the frontend dev server locally and proxies API calls to `hopper-dev.dunkbox.net`.

**Two-step for small changes.** Previously, rsync + volume mount meant changes appeared instantly. Now it's `make deploy-dev` (~1-2 min). Acceptable for integration testing; use local dev for tight iteration loops.

---

## Migration Steps

### Step 1: Update docker-compose.dev.yml

Convert from local builds + volume mounts to GHCR image references:

```yaml
# Key changes:
backend:
  image: ${GHCR_IMAGE_BACKEND:-ghcr.io/the3venthoriz0n/hopper/hopper-backend:dev}
  pull_policy: always
  # REMOVE: build: context/dockerfile
  # REMOVE: volumes with /mnt/user/Misc/_DevRemote/...
  # KEEP: env_file, environment, depends_on, ports, networks

frontend:
  image: ${GHCR_IMAGE_FRONTEND:-ghcr.io/the3venthoriz0n/hopper/hopper-frontend:dev}
  pull_policy: always
  # REMOVE: build: context/dockerfile/target/args
  # REMOVE: volumes with /mnt/user/Misc/_DevRemote/...
  # REMOVE: CHOKIDAR_USEPOLLING, WATCHPACK_POLLING
  # KEEP: environment, depends_on, networks

nginx:
  # REMOVE: volume mount of /mnt/user/Misc/_DevRemote/hopper_sync/nginx/...
  # CHANGE: bake nginx conf into frontend image, or mount from /opt/hopper-dev/nginx/
```

Monitoring services stay as-is (they already build from `./monitoring/` context — can stay local builds on Unraid for now, or also push to GHCR to match prod).

### Step 2: Add Makefile targets for dev deploy

```makefile
# --- Dev Deploy (image-based) ---
GHCR_PREFIX := ghcr.io/the3venthoriz0n/hopper
UNRAID_HOST := dbserver
UNRAID_APP_DIR := /opt/hopper-dev

build-dev:
    docker build -t $(GHCR_PREFIX)/hopper-backend:dev ./backend
    docker build --target prod \
        --build-arg REACT_APP_BACKEND_URL=$$(grep BACKEND_URL .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_DOMAIN=$$(grep DOMAIN .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_FRONTEND_URL=$$(grep FRONTEND_URL .env.dev | cut -d= -f2) \
        --build-arg REACT_APP_ENVIRONMENT=development \
        --build-arg REACT_APP_VERSION=dev \
        -t $(GHCR_PREFIX)/hopper-frontend:dev ./frontend

push-dev:
    docker push $(GHCR_PREFIX)/hopper-backend:dev
    docker push $(GHCR_PREFIX)/hopper-frontend:dev

deploy-dev: build-dev push-dev
    ssh $(UNRAID_HOST) "cd $(UNRAID_APP_DIR) && \
        docker compose -p dev-hopper -f docker-compose.dev.yml pull backend frontend && \
        docker compose -p dev-hopper -f docker-compose.dev.yml up -d"
    @echo "✅ Dev deployed!"
```

### Step 3: One-time Unraid setup

On Unraid:
```bash
# Create app directory
mkdir -p /opt/hopper-dev/nginx

# Authenticate to GHCR (one-time)
docker login ghcr.io -u <github-username>

# Copy compose file and env (done once, then maintained via scp in deploy)
scp docker-compose.dev.yml dbserver:/opt/hopper-dev/
scp .env.dev dbserver:/opt/hopper-dev/
scp nginx/dev-hopper.conf dbserver:/opt/hopper-dev/nginx/
```

### Step 4: Remove old rsync infrastructure

Once confirmed working:
- Delete `scripts/sync-rsync.sh`
- Remove `sync` target from Makefile (or repurpose as config-only sync)
- Remove `make up`'s dependency on `sync`
- Remove Unraid paths (`/mnt/user/Misc/_DevRemote/hopper_sync`) — clean up that directory
- Drop docker context configuration

### Step 5 (Optional): CI builds dev images too

Extend `.github/workflows/deploy.yml` to also build `:dev` images on push to `main` (not just on release). Then dev always has the latest main branch without manual intervention.

```yaml
on:
  push:
    branches: [main]  # Build dev images on every push to main
  release:
    types: [created]  # Build prod images on release
```

---

## Optional: Local Frontend Dev (fast iteration)

For tight frontend iteration without rebuilding:

```makefile
dev-local:
    cd frontend && REACT_APP_BACKEND_URL=https://hopper-dev.dunkbox.net/api \
        REACT_APP_ENVIRONMENT=development npm start
```

This runs React dev server on localhost with hot reload, talking to the dev backend on Unraid. Best of both worlds: fast iteration locally, full-stack testing via `make deploy-dev`.

---

## Decision Summary

| Question | Answer |
|----------|--------|
| Build where? | Mac (fast, Apple Silicon) |
| Registry | GHCR (already using it for prod) |
| Tag strategy | `:dev` for dev, `:vX.Y.Z` for prod releases |
| Hot reload? | No — use local dev server for iteration, deploy-dev for integration |
| Monitoring images | Keep building on Unraid for now (low change frequency) |
| Rollback | Push previous commit's image with `:dev` tag, or pin a SHA tag |
