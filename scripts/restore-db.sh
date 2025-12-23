#!/bin/bash
set -e

BACKUP_FILE="${1}"

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo ""
    echo "Available backups:"
    ls -lh /root/backups/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found)"
    exit 1
fi

# Determine container name based on environment
if docker ps --format '{{.Names}}' | grep -q "prod-hopper-postgres"; then
    CONTAINER_NAME="prod-hopper-postgres"
elif docker ps --format '{{.Names}}' | grep -q "dev-hopper-postgres"; then
    CONTAINER_NAME="dev-hopper-postgres"
else
    echo "❌ Could not find postgres container"
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

