# ============================================================
# NovaSRE — Developer Makefile
# ============================================================

export DOCKER_HOST ?= unix:///Users/padmajagutti/.docker/run/docker.sock

COMPOSE := docker compose -f docker-compose.dev.yml
BACKEND  := $(COMPOSE) exec backend
FRONTEND := $(COMPOSE) exec frontend

.PHONY: up down restart dev test test-tools test-agents test-api test-correlation \
        lint format type-check migrate seed \
        logs-backend logs-frontend logs-mcp logs-postgres logs-redis \
        shell-backend shell-db shell-redis \
        health install install-backend install-frontend \
        build-prod push-prod clean prune

# -------------------------------------------------------------------
# Stack lifecycle
# -------------------------------------------------------------------
up:                         ## Start full dev stack (build if needed)
	$(COMPOSE) up --build

up-detach:                  ## Start stack in background
	$(COMPOSE) up --build -d

down:                       ## Stop stack and remove containers
	$(COMPOSE) down

down-volumes:               ## Stop stack and DELETE all volumes (destructive!)
	$(COMPOSE) down -v

restart:                    ## Restart all services
	$(COMPOSE) restart

restart-backend:            ## Restart only the backend
	$(COMPOSE) restart backend

# -------------------------------------------------------------------
# Database
# -------------------------------------------------------------------
migrate:                    ## Apply all pending Alembic migrations
	$(BACKEND) alembic upgrade head

migrate-down:               ## Rollback last migration
	$(BACKEND) alembic downgrade -1

migrate-status:             ## Show current migration status
	$(BACKEND) alembic current

migrate-history:            ## Show full migration history
	$(BACKEND) alembic history --verbose

migrate-generate:           ## Auto-generate a new migration (requires MSG=)
	$(BACKEND) alembic revision --autogenerate -m "$(MSG)"

# -------------------------------------------------------------------
# Seeding
# -------------------------------------------------------------------
seed:                       ## Seed DB with sample incidents, alerts, services
	$(BACKEND) python scripts/seed_data.py

seed-fresh:                 ## Drop + recreate DB, apply migrations, seed
	$(COMPOSE) exec postgres psql -U novasre -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) migrate
	$(MAKE) seed

# -------------------------------------------------------------------
# Testing
# -------------------------------------------------------------------
test:                       ## Run all tests
	$(BACKEND) pytest tests/ -v --tb=short

test-tools:                 ## Run tool-layer tests
	$(BACKEND) pytest tests/test_tools/ -v --tb=short

test-agents:                ## Run multi-agent system tests
	$(BACKEND) pytest tests/test_agents/ -v --tb=short

test-api:                   ## Run API endpoint tests
	$(BACKEND) pytest tests/test_api/ -v --tb=short

test-correlation:           ## Run alert correlation tests
	$(BACKEND) pytest tests/test_correlation/ -v --tb=short

test-cov:                   ## Run tests with coverage report
	$(BACKEND) pytest tests/ --cov=app --cov-report=html --cov-report=term-missing

test-watch:                 ## Run tests in watch mode
	$(BACKEND) pytest tests/ -v --tb=short -f

# -------------------------------------------------------------------
# Code quality
# -------------------------------------------------------------------
lint:                       ## Lint backend (ruff) and frontend (eslint)
	$(BACKEND) python -m ruff check app/ tests/
	cd frontend && npm run lint

format:                     ## Format backend (ruff + isort) and frontend (prettier)
	$(BACKEND) python -m ruff format app/ tests/
	$(BACKEND) python -m isort app/ tests/
	cd frontend && npm run format

type-check:                 ## Run mypy strict type checking
	$(BACKEND) python -m mypy app/ --strict

check: lint type-check      ## Run all checks (lint + types)

# -------------------------------------------------------------------
# Logs
# -------------------------------------------------------------------
logs-backend:               ## Follow backend logs
	$(COMPOSE) logs -f backend

logs-frontend:              ## Follow frontend logs
	$(COMPOSE) logs -f frontend

logs-mcp:                   ## Follow MCP server logs
	$(COMPOSE) logs -f mcp-server

logs-postgres:              ## Follow postgres logs
	$(COMPOSE) logs -f postgres

logs-redis:                 ## Follow redis logs
	$(COMPOSE) logs -f redis

logs:                       ## Follow all service logs
	$(COMPOSE) logs -f

# -------------------------------------------------------------------
# Shells
# -------------------------------------------------------------------
shell-backend:              ## Open Python REPL in backend container
	$(BACKEND) python

shell-db:                   ## Open psql in postgres container
	$(COMPOSE) exec postgres psql -U novasre -d novasre

shell-redis:                ## Open redis-cli
	$(COMPOSE) exec redis redis-cli

bash-backend:               ## Open bash shell in backend container
	$(BACKEND) bash

# -------------------------------------------------------------------
# Health checks
# -------------------------------------------------------------------
health:                     ## Check backend health endpoint
	@curl -s http://localhost:8000/health | python3 -m json.tool

health-ready:               ## Check backend readiness endpoint
	@curl -s http://localhost:8000/health/ready | python3 -m json.tool

ps:                         ## Show running containers
	$(COMPOSE) ps

# -------------------------------------------------------------------
# Installation (local dev, outside Docker)
# -------------------------------------------------------------------
install-backend:            ## Install backend Python deps locally
	cd backend && pip install -e ".[dev]"

install-frontend:           ## Install frontend npm deps
	cd frontend && npm install

install: install-backend install-frontend  ## Install all deps

# -------------------------------------------------------------------
# Production build
# -------------------------------------------------------------------
build-prod:                 ## Build production Docker images
	docker compose build

push-prod:                  ## Push production images (requires IMAGE_TAG)
	docker compose push

# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
clean:                      ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null; true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null; true

prune:                      ## Prune Docker system (images, containers, networks)
	docker system prune -f

# -------------------------------------------------------------------
# Help
# -------------------------------------------------------------------
help:                       ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
