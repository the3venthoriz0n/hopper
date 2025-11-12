.PHONY: help dev deploy logs shell down rebuild

help:
	@echo "Available commands:"
	@echo "  make dev          - Run locally (uses .env.dev)"
	@echo "  make deploy       - Deploy to Unraid (uses .env.prod)"
	@echo "  make logs         - View Unraid logs"
	@echo "  make shell        - SSH into Unraid container"
	@echo "  make down         - Stop Unraid containers"
	@echo "  make rebuild      - Full rebuild on Unraid (uses .env.prod)"
	@echo ""
	@echo "Note: Copy env.example to .env.dev and .env.prod and fill in your values"

dev:
	docker context use default
	docker compose --env-file .env.dev up -d --build

deploy:
	docker context use unraid
	docker compose --env-file .env.prod up -d --build
	docker context use default
	@echo "✅ Deployed to Unraid!"

logs:
	docker context use unraid
	docker compose logs -f

shell:
	docker context use unraid
	docker compose exec backend /bin/bash

down:
	docker context use unraid
	docker compose down
	docker context use default

rebuild:
	docker context use unraid
	docker compose --env-file .env.prod down
	docker compose --env-file .env.prod build --no-cache
	docker compose --env-file .env.prod up -d
	docker context use default


# # Create Docker context
# docker context create unraid --docker "host=ssh://root@YOUR_IP"

# # Develop locally
# docker compose up -d --build

# # Deploy to Unraid when ready
# make deploy-unraid

# # Check logs on Unraid
# make logs-unraid