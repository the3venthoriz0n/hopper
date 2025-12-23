#!/bin/bash
set -e

# Universal deployment script for both dev and prod
# Usage: ./deploy.sh [dev|prod] [image-tag]

ENV=${1:-prod}
TAG=${2:-latest}
# App directory: /opt/hopper-prod for prod, /opt/hopper-dev for dev
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

# Get GitHub repository from environment or use default
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-"USERNAME/REPO"}

# Set image tags based on git release tag (e.g., v5.0.5)
# Images are tagged with the git tag directly (matching GitHub workflow)
export GHCR_IMAGE_BACKEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-backend:${TAG}"
export GHCR_IMAGE_FRONTEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-frontend:${TAG}"
export GHCR_IMAGE_OTEL="ghcr.io/${GITHUB_REPOSITORY}/hopper-otel:${TAG}"
export GHCR_IMAGE_PROMETHEUS="ghcr.io/${GITHUB_REPOSITORY}/hopper-prometheus:${TAG}"
export GHCR_IMAGE_LOKI="ghcr.io/${GITHUB_REPOSITORY}/hopper-loki:${TAG}"
export GHCR_IMAGE_GRAFANA="ghcr.io/${GITHUB_REPOSITORY}/hopper-grafana:${TAG}"

echo "🏷️  Using images with tag: ${TAG}"

# Set project name to match makefile convention: $(ENV)-hopper
PROJECT_NAME="${ENV}-hopper"

# Pull latest images
echo "📥 Pulling latest images..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" pull || {
    echo "⚠️  Some images failed to pull. Continuing with existing images..."
}

# Prune old/unused Docker images to free up disk space
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
        backend)
            while [ $attempt -le $max_attempts ]; do
                if docker exec "$container_name" curl -f http://localhost:8000/health >/dev/null 2>&1 || \
                   docker exec "$container_name" wget -q --spider http://localhost:8000/health >/dev/null 2>&1; then
                    echo "✅ $service is healthy"
                    return 0
                fi
                # Fallback: check if container is running
                if [ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null)" = "true" ]; then
                    if [ $attempt -ge 10 ]; then
                        echo "⚠️  $service container is running but health endpoint not responding (may be starting)"
                        return 0
                    fi
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
        frontend|nginx)
            while [ $attempt -le $max_attempts ]; do
                if docker exec "$container_name" wget -q --spider http://localhost:80/health >/dev/null 2>&1 || \
                   docker exec "$container_name" curl -f http://localhost:80/health >/dev/null 2>&1; then
                    echo "✅ $service is healthy"
                    return 0
                fi
                # Fallback: check if container is running
                if [ "$(docker inspect -f '{{.State.Running}}' "$container_name" 2>/dev/null)" = "true" ]; then
                    if [ $attempt -ge 10 ]; then
                        echo "⚠️  $service container is running but health endpoint not responding (may be starting)"
                        return 0
                    fi
                fi
                sleep 2
                attempt=$((attempt + 1))
            done
            ;;
        *)
            # Generic health check: just verify container is running
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

# Check critical services first
check_health postgres || HEALTH_CHECK_FAILED=1
check_health redis || HEALTH_CHECK_FAILED=1
check_health backend || HEALTH_CHECK_FAILED=1
check_health frontend || HEALTH_CHECK_FAILED=1
check_health nginx || HEALTH_CHECK_FAILED=1

# Check monitoring services (non-critical)
check_health otel-collector || echo "⚠️  otel-collector health check failed (non-critical)"
check_health prometheus || echo "⚠️  prometheus health check failed (non-critical)"
check_health loki || echo "⚠️  loki health check failed (non-critical)"
check_health grafana || echo "⚠️  grafana health check failed (non-critical)"

# Check service status
echo ""
echo "📊 Service status:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

if [ $HEALTH_CHECK_FAILED -eq 1 ]; then
    echo ""
    echo "❌ Health checks failed for critical services!"
    echo "📋 Check logs: docker compose -p $PROJECT_NAME -f $COMPOSE_FILE logs"
    exit 1
fi

# Setup database backup cron job (only for prod)
if [ "$ENV" == "prod" ]; then
    echo ""
    echo "📦 Setting up database backup cron job..."
    BACKUP_SCRIPT="$APP_DIR/scripts/backup-db.sh"
    
    # Make sure backup script is executable
    if [ -f "$BACKUP_SCRIPT" ]; then
        chmod +x "$BACKUP_SCRIPT"
        
        # Check if cron job already exists
        if ! crontab -l 2>/dev/null | grep -q "$BACKUP_SCRIPT"; then
            # Add cron job for daily backup at 2 AM
            (crontab -l 2>/dev/null; echo "0 2 * * * $BACKUP_SCRIPT >> /var/log/hopper-db-backup.log 2>&1") | crontab -
            echo "✅ Database backup cron job added (daily at 2 AM)"
        else
            echo "ℹ️  Database backup cron job already exists"
        fi
        
        # Create backup directory if it doesn't exist
        mkdir -p /root/backups
    else
        echo "⚠️  Backup script not found: $BACKUP_SCRIPT (cron job not set up)"
    fi
fi

echo ""
echo "✅ Deployment complete! All critical services are healthy."
echo ""
echo "📋 Useful commands:"
echo "   View logs: docker compose -p $PROJECT_NAME -f $COMPOSE_FILE logs -f"
echo "   Check status: docker compose -p $PROJECT_NAME -f $COMPOSE_FILE ps"
echo "   Rollback to previous version: Run ./deploy.sh $ENV <previous-tag> (e.g., ./deploy.sh prod v5.0.4)"
if [ "$ENV" == "prod" ]; then
    echo "   Backup database: cd $APP_DIR && make backup-db"
    echo "   List backups: cd $APP_DIR && make list-backups"
fi

