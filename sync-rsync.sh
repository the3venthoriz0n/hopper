#!/bin/bash
# Sync script - hardcoded to sync to local Windows path
# No secrets or sensitive data in this script

set -e

# Hardcoded sync destination (Windows path via WSL)
SYNC_DEST="/mnt/y/Misc/_DevRemote/hopper_sync"

echo "Syncing to: $SYNC_DEST"

# Create destination directory if it doesn't exist
mkdir -p "${SYNC_DEST}/backend"
mkdir -p "${SYNC_DEST}/frontend"

# Common rsync options
RSYNC_OPTS="-avz --delete"

# Sync
echo "Syncing backend..."
rsync $RSYNC_OPTS \
    --exclude '__pycache__' --exclude '*.pyc' --exclude 'uploads/' \
    --exclude 'sessions/' --exclude '.env' \
    ./backend/ "${SYNC_DEST}/backend/"

echo "Syncing frontend..."
rsync $RSYNC_OPTS \
    --exclude 'node_modules' --exclude 'build' --exclude '.env*' \
    ./frontend/ "${SYNC_DEST}/frontend/"

echo "Syncing root files..."
rsync -avz \
    docker-compose.dev.yml makefile \
    "${SYNC_DEST}/"

echo "✅ Sync complete!"