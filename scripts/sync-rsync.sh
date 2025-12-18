#!/bin/bash
# Sync script - syncs to remote server via SSH
# No secrets or sensitive data in this script

set -e

# Change to project root directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Hardcoded remote server configuration
REMOTE_HOST="dbserver"
REMOTE_USER="root"
REMOTE_PATH="/mnt/y/Misc/_DevRemote/hopper_sync"

SYNC_DEST="${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"

echo "Syncing to remote server: $SYNC_DEST"
echo "Working directory: $(pwd)"

# Common rsync options
RSYNC_OPTS="-avz --delete"

# Sync
echo "Syncing backend..."
rsync $RSYNC_OPTS \
    --exclude '__pycache__' --exclude '*.pyc' --exclude 'uploads/' \
    --exclude 'sessions/' --exclude '.env' --exclude 'venv/' \
    ./backend/ "${SYNC_DEST}/backend/"

echo "Syncing frontend..."
rsync $RSYNC_OPTS \
    --exclude 'node_modules' --exclude 'build' --exclude '.env*' \
    ./frontend/ "${SYNC_DEST}/frontend/"

echo "Syncing root files..."
rsync -avz \
    docker-compose.dev.yml makefile \
    "${SYNC_DEST}/"

echo "Syncing nginx config..."
rsync -avz \
    nginx/dev-hopper.conf \
    "${SYNC_DEST}/nginx/"

echo "✅ Sync complete!"