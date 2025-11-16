.PHONY: help dev prod clean-dev clean-prod logs shell down logs-prod shell-prod down-prod

help:
	@echo "Available commands:"
	@echo "  make dev          - Deploy to dev environment (uses .env.dev, ports 3000/8000)"
	@echo "  make prod         - Deploy to prod environment (uses .env.prod, ports 3001/8001)"
	@echo "  make clean-dev    - Fresh rebuild on dev"
	@echo "  make clean-prod   - Fresh rebuild on prod"
	@echo "  make logs         - View dev container logs"
	@echo "  make logs-prod    - View prod container logs"
	@echo "  make logs-frontend - View dev frontend logs only"
	@echo "  make logs-backend  - View dev backend logs only"
	@echo "  make logs-frontend-prod - View prod frontend logs only"
	@echo "  make logs-backend-prod  - View prod backend logs only"
	@echo "  make shell        - Shell into dev backend container"
	@echo "  make shell-prod    - Shell into prod backend container"
	@echo "  make down         - Stop dev containers"
	@echo "  make down-prod    - Stop prod containers"
	@echo ""
	@echo "Note: Copy env.example to .env.dev and .env.prod and fill in your values"
	@echo "      Dev: hopper-dev.dunkbox.net (ports 3000/8000)"
	@echo "      Prod: hopper.dunkbox.net (ports 3001/8001)"

dev:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev up -d --build
	@echo "✅ Deployed to dev! (ports 3000/8000)"

prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod up -d --build
	@echo "✅ Deployed to prod! (ports 3001/8001)"

clean-dev:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev down
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev build --no-cache
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev up -d
	docker image prune -f
	@echo "✅ Fresh rebuild on dev complete!"

clean-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod down
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod build --no-cache
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod up -d
	docker image prune -f
	@echo "✅ Fresh rebuild on prod complete!"

logs:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev logs -f

logs-frontend:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev logs -f frontend

logs-backend:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev logs -f backend

logs-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod logs -f

logs-frontend-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod logs -f frontend

logs-backend-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod logs -f backend

shell:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev exec backend /bin/bash

shell-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod exec backend /bin/bash

down:
	docker compose -p hopper-dev -f docker-compose.dev.yml --env-file .env.dev down

down-prod:
	docker compose -p hopper-prod -f docker-compose.prod.yml --env-file .env.prod down


# # Create Docker context
# docker context create your-context-name --docker "host=ssh://root@YOUR_IP"
# docker context use your-context-name

# # Develop locally
# docker compose up -d --build
