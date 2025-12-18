#!/bin/bash
set -e

# Universal deployment script for both dev and prod
# Usage: ./deploy.sh [dev|prod] [image-tag]

ENV=${1:-prod}
TAG=${2:-latest}
APP_DIR="/opt/hopper${ENV:+-$ENV}"

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

# Determine compose file
COMPOSE_FILE="docker-compose.${ENV}.yml"
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "❌ Compose file not found: $COMPOSE_FILE"
    exit 1
fi

# Environment variables are passed directly from GitHub Actions (GitHub Secrets)
# No .env file needed - all variables come from the workflow
echo "📋 Using environment variables from GitHub Secrets (passed directly from workflow)"

# Automatically export all variables so Docker Compose can use them
# set -a exports all variables automatically
set -a

# Get GitHub repository from environment or use default
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-"USERNAME/REPO"}

# Set image tags based on environment
export GHCR_IMAGE_BACKEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-backend:${ENV}-${TAG}"
export GHCR_IMAGE_FRONTEND="ghcr.io/${GITHUB_REPOSITORY}/hopper-frontend:${ENV}-${TAG}"
export GHCR_IMAGE_OTEL="ghcr.io/${GITHUB_REPOSITORY}/hopper-otel:${ENV}-${TAG}"
export GHCR_IMAGE_PROMETHEUS="ghcr.io/${GITHUB_REPOSITORY}/hopper-prometheus:${ENV}-${TAG}"
export GHCR_IMAGE_LOKI="ghcr.io/${GITHUB_REPOSITORY}/hopper-loki:${ENV}-${TAG}"
export GHCR_IMAGE_GRAFANA="ghcr.io/${GITHUB_REPOSITORY}/hopper-grafana:${ENV}-${TAG}"

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

# Wait for services to be healthy
echo "⏳ Waiting for services to start..."
sleep 10

# Check service status
echo "📊 Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "✅ Deployment complete!"
echo ""
echo "To view logs: docker compose -f $COMPOSE_FILE logs -f"
echo "To check status: docker compose -f $COMPOSE_FILE ps"

