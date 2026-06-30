.PHONY: help dev prod build migrate test logs down clean secrets

help:
	@echo "BrokerAI — available commands:"
	@echo "  make dev          Start dev environment (hot reload)"
	@echo "  make prod         Start production environment"
	@echo "  make build        Build production Docker image"
	@echo "  make migrate      Run Alembic migrations (dev)"
	@echo "  make makemigration msg='description'  Auto-generate migration"
	@echo "  make test         Run test suite"
	@echo "  make logs         Tail all container logs"
	@echo "  make down         Stop all containers"
	@echo "  make clean        Remove containers, volumes, images"
	@echo "  make secrets      Generate all secret values"

# ── Development ───────────────────────────────────────────────────────────────

dev:
	docker compose up --build

dev-bg:
	docker compose up -d --build

migrate:
	docker compose run --rm api alembic upgrade head

makemigration:
	docker compose run --rm api alembic revision --autogenerate -m "$(msg)"

test:
	docker compose run --rm api python -m pytest tests/ -q

logs:
	docker compose logs -f

down:
	docker compose down

# ── Production ────────────────────────────────────────────────────────────────

prod:
	docker compose -f docker-compose.prod.yml up -d

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f

prod-down:
	docker compose -f docker-compose.prod.yml down

build:
	docker build -t brokerai:latest .

deploy:
	./scripts/deploy.sh

# ── Utilities ─────────────────────────────────────────────────────────────────

clean:
	docker compose down -v --rmi local
	docker compose -f docker-compose.prod.yml down -v --rmi local 2>/dev/null || true

secrets:
	@./scripts/generate_secrets.sh
