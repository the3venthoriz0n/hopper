#!/bin/bash
set -e

# Determine environment and set backup directory
if docker ps --format '{{.Names}}' | grep -q "prod-hopper-postgres"; then
    CONTAINER_NAME="prod-hopper-postgres"
    APP_DIR="/opt/hopper-prod"
    BACKUP_DIR="${APP_DIR}/backups"
elif docker ps --format '{{.Names}}' | grep -q "dev-hopper-postgres"; then
    CONTAINER_NAME="dev-hopper-postgres"
    APP_DIR="/opt/hopper-dev"
    BACKUP_DIR="${APP_DIR}/backups"
else
    echo "❌ Could not find postgres container"
    exit 1
fi

mkdir -p "${BACKUP_DIR}"

# Get password from .env.prod
ENV_FILE="${APP_DIR}/.env.prod"
if [ ! -f "${ENV_FILE}" ]; then
    # Fallback: try current directory
    ENV_FILE=".env.prod"
fi

if [ ! -f "${ENV_FILE}" ]; then
    echo "❌ Could not find .env.prod file"
    exit 1
fi

POSTGRES_PASSWORD=$(grep POSTGRES_PASSWORD "${ENV_FILE}" | cut -d '=' -f2)

# Create backup with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/db_${TIMESTAMP}.sql.gz"

echo "📦 Backing up database from ${CONTAINER_NAME}..."
docker exec "${CONTAINER_NAME}" pg_dump -U hopper hopper | gzip > "${BACKUP_FILE}"

# Delete backups older than 7 days
find "${BACKUP_DIR}" -name "db_*.sql.gz" -mtime +7 -delete

echo "✅ Backup saved: ${BACKUP_FILE}"
echo "📊 Size: $(du -h "${BACKUP_FILE}" | cut -f1)"

