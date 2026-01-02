#!/bin/bash
set -e

# Universal deployment script for both dev and prod
# Usage: ./deploy.sh [dev|prod] [image-tag]

ENV=${1:-prod}
TAG=${2:-latest}

# App directory configuration
if [ "$ENV" == "prod" ]; then
    APP_DIR="/opt/hopper-prod"
else
    APP_DIR="/opt/hopper-dev"
fi

if [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; then
    echo "❌ Invalid environment: $ENV. Use 'dev' or 'prod'"
    exit 1
fi

echo "🚀 Deploying $ENV environment with tag: $TAG"
echo "📁 App directory: $APP_DIR"

# Check if app directory exists
if [ ! -d "$APP_DIR" ]; then
    echo "❌ App directory not found: $APP_DIR"
    exit 1
fi

cd "$APP_DIR"

# Source environment variables from .env file
ENV_FILE=".env.${ENV}"
if [ -f "$ENV_FILE" ]; then
    echo "📋 Sourcing environment variables from $ENV_FILE"
    set -a  # Automatically export all variables
    source "$ENV_FILE"
    set +a
else
    echo "❌ Environment file not found: $ENV_FILE"
    exit 1
fi

# Determine compose file
COMPOSE_FILE="docker-compose.${ENV}.yml"
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "❌ Compose file not found: $COMPOSE_FILE"
    exit 1
fi

# Set Defaults (Only if not already set by .env file)
export GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-"the3venthoriz0n/hopper"}
export TAG=${TAG:-"latest"}

# Set image tags using shell parameter expansion (assign if null or unset)
# This ensures .env values from GitHub Actions take priority
: "${GHCR_IMAGE_BACKEND:=ghcr.io/${GITHUB_REPOSITORY}/hopper-backend:${TAG}}"
: "${GHCR_IMAGE_FRONTEND:=ghcr.io/${GITHUB_REPOSITORY}/hopper-frontend:${TAG}}"
: "${GHCR_IMAGE_OTEL:=ghcr.io/${GITHUB_REPOSITORY}/hopper-otel:${TAG}}"
: "${GHCR_IMAGE_PROMETHEUS:=ghcr.io/${GITHUB_REPOSITORY}/hopper-prometheus:${TAG}}"
: "${GHCR_IMAGE_LOKI:=ghcr.io/${GITHUB_REPOSITORY}/hopper-loki:${TAG}}"
: "${GHCR_IMAGE_GRAFANA:=ghcr.io/${GITHUB_REPOSITORY}/hopper-grafana:${TAG}}"

# Export for Docker Compose use
export GHCR_IMAGE_BACKEND GHCR_IMAGE_FRONTEND GHCR_IMAGE_OTEL GHCR_IMAGE_PROMETHEUS GHCR_IMAGE_LOKI GHCR_IMAGE_GRAFANA

echo "🏷️  Using images with tag: ${TAG}"

# Set project name
PROJECT_NAME="${ENV}-hopper"

# Pull latest images
echo "📥 Pulling latest images..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" pull || {
    echo "⚠️  Some images failed to pull. Continuing with existing images..."
}

# Prune old/unused Docker images
echo "🧹 Pruning old Docker images..."
docker image prune -af --filter "until=168h" || {
    echo "⚠️  Image pruning failed, continuing..."
}
echo "✅ Image pruning complete"

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down

# Start services
echo "🚀 Starting services..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d

# Wait for services to start
echo "⏳ Waiting for services to start..."
sleep 5

# Health check function
check_health() {
    local service=$1
    local container_name="${ENV}-hopper-${service}"
    local max_attempts=30
    local attempt=1
    
    echo "🏥 Checking health of $service..."
    
    case $service in
        postgres)
            while [ $attempt -le $max_attempts ]; do
                if docker exec "$container_name" pg_isready -U hopper >/dev/null 2>&1; then
                    echo "✅ $service is healthy"
                    return 0
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
        redis)
            while [ $attempt -le $max_attempts ]; do
                if docker exec "$container_name" redis-cli ping >/dev/null 2>&1; then
                    echo "✅ $service is healthy"
                    return 0
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
        backend|frontend|nginx)
            local port=8000
            [ "$service" != "backend" ] && port=80
            
            while [ $attempt -le $max_attempts ]; do
                # Check for curl
                if docker exec "$container_name" which curl >/dev/null 2>&1; then
                    if docker exec "$container_name" curl -f http://localhost:$port/health >/dev/null 2>&1; then
                        echo "✅ $service is healthy"
                        return 0
                    fi
                # Check for wget
                elif docker exec "$container_name" which wget >/dev/null 2>&1; then
                    if docker exec "$container_name" wget -q --spider http://localhost:$port/health >/dev/null 2>&1; then
                        echo "✅ $service is healthy"
                        return 0
                    fi
                # Fallback: Is container running?
                else
                    if [ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null)" = "true" ]; then
                        echo "⚠️  $service: No curl/wget, but container is running"
                        return 0
                    fi
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
        *)
            while [ $attempt -le $max_attempts ]; do
                if [ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null)" = "true" ]; then
                    echo "✅ $service is running"
                    return 0
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
    esac
    
    echo "❌ $service health check failed after $max_attempts attempts"
    return 1
}

# Perform health checks
echo ""
echo "🏥 Performing health checks..."
HEALTH_CHECK_FAILED=0

check_health postgres || HEALTH_CHECK_FAILED=1
check_health redis || HEALTH_CHECK_FAILED=1
check_health backend || HEALTH_CHECK_FAILED=1
check_health frontend || HEALTH_CHECK_FAILED=1
check_health nginx || HEALTH_CHECK_FAILED=1

# Check monitoring (non-critical)
check_health otel-collector || echo "⚠️  otel-collector check failed"
check_health prometheus || echo "⚠️  prometheus check failed"
check_health loki || echo "⚠️  loki check failed"
check_health grafana || echo "⚠️  grafana check failed"

echo ""
echo "📊 Service status:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

if [ $HEALTH_CHECK_FAILED -eq 1 ]; then
    echo "❌ Critical services failed health checks!"
    exit 1
fi

# Setup cron (Prod only)
if [ "$ENV" == "prod" ]; then
    BACKUP_SCRIPT="$APP_DIR/scripts/backup-db.sh"
    if [ -f "$BACKUP_SCRIPT" ]; then
        chmod +x "$BACKUP_SCRIPT"
        if ! crontab -l 2>/dev/null | grep -q "$BACKUP_SCRIPT"; then
            (crontab -l 2>/dev/null; echo "0 2 * * * $BACKUP_SCRIPT >> /var/log/hopper-db-backup.log 2>&1") | crontab -
            echo "✅ Backup cron job added"
        fi
        mkdir -p "$APP_DIR/backups"
    fi
fi

echo "✅ Deployment complete!"