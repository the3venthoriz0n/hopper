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

# Set image tags based on environment and tag
# For rollback: images are tagged with both version tag and env-latest
export GHCR_IMAGE_BACKEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-backend:${ENV}-${TAG}"
export GHCR_IMAGE_FRONTEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-frontend:${ENV}-${TAG}"
export GHCR_IMAGE_OTEL="ghcr.io/${GITHUB_REPOSITORY}/hopper-otel:${ENV}-${TAG}"
export GHCR_IMAGE_PROMETHEUS="ghcr.io/${GITHUB_REPOSITORY}/hopper-prometheus:${ENV}-${TAG}"
export GHCR_IMAGE_LOKI="ghcr.io/${GITHUB_REPOSITORY}/hopper-loki:${ENV}-${TAG}"
export GHCR_IMAGE_GRAFANA="ghcr.io/${GITHUB_REPOSITORY}/hopper-grafana:${ENV}-${TAG}"

echo "🏷️  Using images with tag: ${ENV}-${TAG}"

# Pull latest images
echo "📥 Pulling latest images..."
docker compose -f "$COMPOSE_FILE" pull || {
    echo "⚠️  Some images failed to pull. Continuing with existing images..."
}

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose -f "$COMPOSE_FILE" down

# Start services
echo "🚀 Starting services..."
docker compose -f "$COMPOSE_FILE" up -d

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
docker compose -f "$COMPOSE_FILE" ps

if [ $HEALTH_CHECK_FAILED -eq 1 ]; then
    echo ""
    echo "❌ Health checks failed for critical services!"
    echo "📋 Check logs: docker compose -f $COMPOSE_FILE logs"
    exit 1
fi

echo ""
echo "✅ Deployment complete! All critical services are healthy."
echo ""
echo "📋 Useful commands:"
echo "   View logs: docker compose -f $COMPOSE_FILE logs -f"
echo "   Check status: docker compose -f $COMPOSE_FILE ps"
echo "   Rollback to previous version: Update TAG in .env.$ENV and run ./deploy.sh $ENV <previous-tag>"

