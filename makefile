.PHONY: help sync up down rebuild logs shell clean test test-security rebuild-grafana clear-grafana-cache setup-stripe

# Default environment (can be overridden: make up ENV=prod)
ENV ?= dev

# Get git version (latest release tag, e.g., v5.0.5)
GIT_VERSION := $(shell git tag --sort=-version:refname | head -1 2>/dev/null || echo "dev")

# Export GIT_VERSION so docker-compose can use it
export GIT_VERSION

# Compose command builder
COMPOSE = docker compose -p $(ENV)-hopper -f docker-compose.$(ENV).yml --env-file .env.$(ENV)

# Service filter (optional: make logs SERVICE=backend)
SERVICE ?=

help:
	@echo "Usage: make <target> [ENV=dev|prod] [SERVICE=frontend|backend]"
	@echo ""
	@echo "Targets:"
	@echo "  test          Run unit tests"
	@echo "  test-security Run security tests (requires API to be running)"
	@echo "  sync          Sync local code to remote server"
	@echo "  up            Start services (with build, runs tests first)"
	@echo "  down          Stop services"
	@echo "  rebuild       Stop, rebuild from scratch, and start (runs tests first)"
	@echo "  rebuild-grafana Rebuild Grafana service (clears cache and restarts)"
	@echo "  clear-grafana-cache Clear Grafana database volume (forces dashboard reload)"
	@echo "  setup-stripe  Run Stripe product/price/webhook setup (ENV=dev|prod)"
	@echo "  logs          Follow logs (add LINES=N for tail)"
	@echo "  shell         Open backend shell"
	@echo "  clean         Remove stopped containers and unused images"
	@echo ""
	@echo "Examples:"
	@echo "  make up                      Start dev environment (Unraid, hot reload)"
	@echo "  make up ENV=prod             Start prod environment (DigitalOcean, GHCR images)"
	@echo "  make logs SERVICE=backend    Follow backend logs"
	@echo "  make logs LINES=100          View last 100 lines"
	@echo "  make rebuild ENV=prod        Fresh prod rebuild"
	@echo ""
	@echo "Environments:"
	@echo "  dev:   hopper-dev.dunkbox.net (Unraid, local builds, hot reload)"
	@echo "  prod:  hopper.dunkbox.net     (DigitalOcean, GHCR images)"

sync:
	@bash scripts/sync-rsync.sh

test:
	@echo "🧪 Building backend image (to ensure pytest is installed)..."
	@$(COMPOSE) build backend
	@echo "🧪 Running unit tests..."
	@$(COMPOSE) run --rm backend python -m pytest /app/test_main.py -v
	@echo "✅ All tests passed!"

test-security: 
	@echo "🔒 Running security tests (requires API to be running)..."
	@echo "⚠️  Make sure backend is running: make up ENV=$(ENV)"
	@$(COMPOSE) run --rm -e TEST_BASE_URL=http://backend:8000 backend python -m pytest /app/test_security.py -v
	@echo "✅ Security tests passed!"

up: test sync
	@echo "🚀 Starting $(ENV) environment..."
	@$(COMPOSE) up -d --build $(SERVICE)
	@echo "✅ $(ENV) is running!"

down:
	@echo "🛑 Stopping $(ENV) environment..."
	@$(COMPOSE) down $(SERVICE)

rebuild: down sync test
	@echo "🔨 Rebuilding $(ENV) from scratch..."
	@$(COMPOSE) build --no-cache $(SERVICE)
	@$(COMPOSE) up -d $(SERVICE)
	@docker image prune -f
	@echo "✅ $(ENV) rebuild complete!"

rebuild-grafana: sync
	@echo "🔄 Rebuilding Grafana for $(ENV) environment..."
	@echo "🗑️  Clearing Grafana cache to ensure fresh load..."
	@$(COMPOSE) stop grafana || true
	@$(COMPOSE) rm -f grafana || true
	@docker volume rm $(ENV)-hopper_grafana_data 2>/dev/null || echo "⚠️  Volume doesn't exist (ok)"
	@echo "🔨 Building Grafana image with updated dashboards..."
	@$(COMPOSE) build --no-cache grafana
	@echo "🚀 Starting Grafana..."
	@$(COMPOSE) up -d grafana
	@echo "✅ Grafana rebuild complete! Dashboard should appear within 10-30 seconds."
	@echo "💡 Check Grafana logs if dashboard doesn't appear: make logs SERVICE=grafana"

clear-grafana-cache:
	@echo "🗑️  Clearing Grafana cache for $(ENV) environment..."
	@$(COMPOSE) stop grafana || true
	@$(COMPOSE) rm -f grafana || true
	@docker volume rm $(ENV)-hopper_grafana_data 2>/dev/null || echo "⚠️  Volume $(ENV)-hopper_grafana_data doesn't exist (already cleared)"
	@$(COMPOSE) up -d grafana
	@echo "✅ Grafana cache cleared! Dashboard will reload from provisioned files."

logs:
ifdef LINES
	@$(COMPOSE) logs --tail=$(LINES) $(SERVICE)
else
	@$(COMPOSE) logs -f $(SERVICE)
endif

shell:
	@$(COMPOSE) exec backend /bin/bash

clean:
	@docker container prune -f
	@docker image prune -f
	@docker volume prune -f
	@echo "✅ Cleanup complete!"

setup-stripe:
	@echo "⚙️  Running Stripe setup locally for ENV=$(ENV) ..."
	@if [ ! -d "backend/venv" ]; then \
		echo "❌ Virtual environment not found. Run: cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"; \
		exit 1; \
	fi
	@cd backend && ./venv/bin/python setup_stripe.py --env-file $(ENV)
	@echo "🔄 Syncing to remote..."
	@$(MAKE) sync
	@echo "✅ Stripe setup completed and synced."