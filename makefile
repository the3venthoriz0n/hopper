.PHONY: help sync up down rebuild logs shell clean

# Default environment (can be overridden: make up ENV=prod)
ENV ?= dev

# Get git version (tag or short commit hash)
GIT_VERSION := $(shell git describe --tags --always 2>/dev/null || echo "dev")

# Export GIT_VERSION so docker-compose can use it
export GIT_VERSION

# Compose command builder
COMPOSE = docker compose -p hopper-$(ENV) -f docker-compose.$(ENV).yml --env-file .env.$(ENV)

# Service filter (optional: make logs SERVICE=backend)
SERVICE ?=

help:
	@echo "Usage: make <target> [ENV=dev|prod] [SERVICE=frontend|backend]"
	@echo ""
	@echo "Targets:"
	@echo "  sync          Sync local code to remote server"
	@echo "  up            Start services (with build)"
	@echo "  down          Stop services"
	@echo "  rebuild       Stop, rebuild from scratch, and start"
	@echo "  logs          Follow logs (add LINES=N for tail)"
	@echo "  shell         Open backend shell"
	@echo "  clean         Remove stopped containers and unused images"
	@echo ""
	@echo "Examples:"
	@echo "  make up                      Start dev environment"
	@echo "  make up ENV=prod             Start prod environment"
	@echo "  make logs SERVICE=backend    Follow backend logs"
	@echo "  make logs LINES=100          View last 100 lines"
	@echo "  make rebuild ENV=prod        Fresh prod rebuild"
	@echo ""
	@echo "Environments:"
	@echo "  dev:  hopper-dev.dunkbox.net  (ports 3000/8000)"
	@echo "  prod: hopper.dunkbox.net      (ports 3001/8001)"

sync:
	@bash sync-rsync.sh

up: sync
	@echo "🚀 Starting $(ENV) environment..."
	@$(COMPOSE) up -d --build $(SERVICE)
	@echo "✅ $(ENV) is running!"

down:
	@echo "🛑 Stopping $(ENV) environment..."
	@$(COMPOSE) down $(SERVICE)

rebuild: down sync
	@echo "🔨 Rebuilding $(ENV) from scratch..."
	@$(COMPOSE) build --no-cache $(SERVICE)
	@$(COMPOSE) up -d $(SERVICE)
	@docker image prune -f
	@echo "✅ $(ENV) rebuild complete!"

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
	@echo "✅ Cleanup complete!"