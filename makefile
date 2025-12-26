.PHONY: help sync up down rebuild logs shell clean test test-security rebuild-grafana clear-grafana-cache setup-stripe backup-db restore-db list-backups

# Default environment (can be overridden: make up ENV=prod)
ENV ?= dev

# Get git version (latest release tag, e.g., v5.0.5)
# On prod server (no git repo), default to "dev" or read from .env file if available
GIT_VERSION := $(shell git tag --sort=-version:refname | head -1 2>/dev/null || echo "dev")

# Export GIT_VERSION so docker-compose can use it
export GIT_VERSION

# Compose command builder
COMPOSE = docker compose -p $(ENV)-hopper -f docker-compose.$(ENV).yml --env-file .env.$(ENV)
TEST_CMD = python -m pytest /app/tests/ -v --tb=short

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
	@echo "  backup-db     Backup PostgreSQL database (keeps last 7 days)"
	@echo "  restore-db    Restore PostgreSQL database (requires BACKUP_FILE)"
	@echo "  list-backups  List available database backups"
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
	@if [ "$(ENV)" = "prod" ]; then \
		echo "⏭️  Skipping sync for prod (code is deployed via GitHub Actions)"; \
	else \
		bash scripts/sync-rsync.sh; \
	fi

test:
	@if [ "$(ENV)" = "prod" ]; then \
		echo "⏭️  Skipping tests for prod environment (use deploy.sh for production deployments)"; \
	else \
		echo "🧪 Running comprehensive test suite..."; \
		$(COMPOSE) run --rm backend $(TEST_CMD); \
	fi

test-security:
	@echo "🔒 Running security integration tests for $(ENV) environment..."; \
	echo "⚠️  Note: These tests require a running backend server"; \
	$(COMPOSE) run --rm -e RUN_INTEGRATION_TESTS=true -e ENV=$(ENV) backend python -m pytest /app/tests/test_security.py -v --tb=short;

up: sync
	@if [ "$(ENV)" != "prod" ]; then \
		$(MAKE) test ENV=$(ENV); \
	fi
	@echo "🚀 Starting $(ENV) environment..."
	@if [ "$(ENV)" = "prod" ]; then \
		$(COMPOSE) up -d $(SERVICE); \
	else \
		$(COMPOSE) up -d --build $(SERVICE); \
	fi
	@echo "✅ $(ENV) is running!"

down:
	@echo "🛑 Stopping $(ENV) environment..."
	@$(COMPOSE) down $(SERVICE)

rebuild: down sync
	@if [ "$(ENV)" != "prod" ] && [ -z "$(SKIP_TESTS)" ]; then \
		$(MAKE) test ENV=$(ENV); \
	fi
	@echo "🔨 Rebuilding $(ENV) from scratch..."
	@if [ "$(ENV)" = "prod" ]; then \
		echo "⚠️  Prod rebuild: pulling latest images instead of building..."; \
		$(COMPOSE) pull $(SERVICE); \
		$(COMPOSE) up -d $(SERVICE); \
	else \
		$(COMPOSE) build --no-cache $(SERVICE); \
		$(COMPOSE) up -d $(SERVICE); \
	fi
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
	@cd backend && ./venv/bin/python ../scripts/setup_stripe.py --env-file $(ENV)
	@echo "🔄 Syncing to remote..."
	@$(MAKE) sync
	@echo "✅ Stripe setup completed and synced."

backup-db:
	@bash scripts/backup-db.sh

restore-db:
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "❌ Usage: make restore-db BACKUP_FILE=/opt/hopper-prod/backups/db_YYYYMMDD_HHMMSS.sql.gz"; \
		echo "Available backups:"; \
		if [ "$(ENV)" = "prod" ]; then \
			ls -lh /opt/hopper-prod/backups/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found)"; \
		else \
			ls -lh /opt/hopper-dev/backups/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found)"; \
		fi; \
		exit 1; \
	fi
	@bash scripts/restore-db.sh $(BACKUP_FILE)

list-backups:
	@echo "📦 Available database backups:"
	@if [ "$(ENV)" = "prod" ]; then \
		ls -lh /opt/hopper-prod/backups/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found in /opt/hopper-prod/backups)"; \
	else \
		ls -lh /opt/hopper-dev/backups/db_*.sql.gz 2>/dev/null | tail -20 || echo "  (no backups found in /opt/hopper-dev/backups)"; \
	fi