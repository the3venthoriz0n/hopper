.PHONY: help dev prod clean-dev clean-prod logs logs-frontend logs-backend shell down sync

# Variables
DEV_COMPOSE := docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev
PROD_COMPOSE := docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod

help:
	@echo "Available commands:"
	@echo "  make sync         - Sync local code to remote server (for hot reload)"
	@echo "  make dev          - Deploy to dev environment (uses .env.dev, ports 3000/8000)"
	@echo "  make prod         - Deploy to prod environment (uses .env.prod, ports 3001/8001)"
	@echo "  make clean-dev    - Fresh rebuild on dev"
	@echo "  make clean-prod   - Fresh rebuild on prod"
	@echo "  make logs [ENV=dev|prod] [SERVICE=frontend|backend]"
	@echo "  make shell [ENV=dev|prod]"
	@echo "  make down [ENV=dev|prod]"
	@echo ""
	@echo "Examples:"
	@echo "  make logs                    - View all dev logs"
	@echo "  make logs ENV=prod           - View all prod logs"
	@echo "  make logs SERVICE=frontend   - View dev frontend logs"
	@echo "  make logs ENV=prod SERVICE=backend - View prod backend logs"
	@echo ""
	@echo "Note: Copy env.example to .env.dev and .env.prod and fill in your values"
	@echo "      Dev: hopper-dev.dunkbox.net (ports 3000/8000)"
	@echo "      Prod: hopper.dunkbox.net (ports 3001/8001)"
	@echo "      Code syncs to: /mnt/y/Misc/_DevRemote/hopper (hardcoded in sync-rsync.sh)"

sync:
	@bash sync-rsync.sh

dev: sync
	$(DEV_COMPOSE) build --no-cache
	$(DEV_COMPOSE) up -d
	@echo "✅ Deployed to dev! (ports 3000/8000)"

prod:
	$(PROD_COMPOSE) up -d --build
	@echo "✅ Deployed to prod! (ports 3001/8001)"

clean-dev: down dev
	docker image prune -f
	@echo "✅ Fresh rebuild on dev complete!"

clean-prod: down prod
	@$(MAKE) down ENV=prod
	docker image prune -f
	@echo "✅ Fresh rebuild on prod complete!"

# Unified logs command with optional ENV and SERVICE parameters
logs:
	@if [ "$(ENV)" = "prod" ]; then \
		if [ -n "$(SERVICE)" ]; then \
			$(PROD_COMPOSE) logs -f $(SERVICE); \
		else \
			$(PROD_COMPOSE) logs -f; \
		fi \
	else \
		if [ -n "$(SERVICE)" ]; then \
			$(DEV_COMPOSE) logs -f $(SERVICE); \
		else \
			$(DEV_COMPOSE) logs -f; \
		fi \
	fi

# Unified shell command
shell:
	@if [ "$(ENV)" = "prod" ]; then \
		$(PROD_COMPOSE) exec backend /bin/bash; \
	else \
		$(DEV_COMPOSE) exec backend /bin/bash; \
	fi

# Unified down command
down:
	@if [ "$(ENV)" = "prod" ]; then \
		$(PROD_COMPOSE) down; \
	else \
		$(DEV_COMPOSE) down; \
	fi

# Legacy aliases for backward compatibility (optional - remove if not needed)
logs-prod:
	@$(MAKE) logs ENV=prod

logs-frontend:
	@$(MAKE) logs SERVICE=frontend

logs-backend:
	@$(MAKE) logs SERVICE=backend

logs-frontend-prod:
	@$(MAKE) logs ENV=prod SERVICE=frontend

logs-backend-prod:
	@$(MAKE) logs ENV=prod SERVICE=backend

shell-prod:
	@$(MAKE) shell ENV=prod

down-prod:
	@$(MAKE) down ENV=prod