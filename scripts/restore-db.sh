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

BACKUP_FILE="${1}"

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lh "${BACKUP_DIR}"/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found in ${BACKUP_DIR})"
    exit 1
fi

echo "🔄 Restoring database to ${CONTAINER_NAME} from: ${BACKUP_FILE}"
read -p "⚠️  This will overwrite the database. Continue? (yes/no): " confirm

if [ "${confirm}" != "yes" ]; then
    echo "❌ Restore cancelled"
    exit 1
fi

echo "📦 Restoring..."
gunzip -c "${BACKUP_FILE}" | docker exec -i "${CONTAINER_NAME}" psql -U hopper -d hopper

echo "✅ Database restored!"

