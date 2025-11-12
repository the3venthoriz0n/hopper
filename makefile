.PHONY: help dev prod clean-dev clean-prod logs shell down

help:
	@echo "Available commands:"
	@echo "  make dev          - Deploy to dev environment (uses .env.dev)"
	@echo "  make prod         - Deploy to prod environment (uses .env.prod)"
	@echo "  make clean-dev    - Fresh rebuild on dev (down, build --no-cache, up)"
	@echo "  make clean-prod   - Fresh rebuild on prod (down, build --no-cache, up)"
	@echo "  make logs         - View all container logs"
	@echo "  make logs-frontend - View frontend logs only"
	@echo "  make logs-backend  - View backend logs only"
	@echo "  make shell        - Shell into backend container"
	@echo "  make down         - Stop containers"
	@echo ""
	@echo "Note: Copy env.example to .env.dev and .env.prod and fill in your values"

dev:
	docker compose --env-file .env.dev up -d --build
	@echo "✅ Deployed to dev!"

prod:
	docker compose --env-file .env.prod up -d --build
	@echo "✅ Deployed to prod!"

clean-dev:
	docker compose --env-file .env.dev down
	docker compose --env-file .env.dev build --no-cache
	docker compose --env-file .env.dev up -d
	docker image prune -f
	@echo "✅ Fresh rebuild on dev complete!"

clean-prod:
	docker compose --env-file .env.prod down
	docker compose --env-file .env.prod build --no-cache
	docker compose --env-file .env.prod up -d
	docker image prune -f
	@echo "✅ Fresh rebuild on prod complete!"

logs:
	docker compose --env-file .env.dev logs -f

logs-frontend:
	docker compose --env-file .env.dev logs -f frontend

logs-backend:
	docker compose --env-file .env.dev logs -f backend

shell:
	docker compose --env-file .env.dev exec backend /bin/bash

down:
	docker compose --env-file .env.dev down


# # Create Docker context
# docker context create your-context-name --docker "host=ssh://root@YOUR_IP"
# docker context use your-context-name

# # Develop locally
# docker compose up -d --build
