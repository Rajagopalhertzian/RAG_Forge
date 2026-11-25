# ContextForge Makefile
# Usage: make <target>

.PHONY: help install dev-install test lint typecheck format check clean migrate upgrade db-shell docker-build docker-up docker-down docker-logs deploy-staging deploy-prod docs-serve

# Default target
help:
	@echo "ContextForge - Available targets:"
	@echo ""
	@echo "Setup:"
	@echo "  install        Install production dependencies"
	@echo "  dev-install    Install all dependencies (dev, lint, docs, eval)"
	@echo "  pre-commit     Install pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  run            Run the API server (dev mode)"
	@echo "  worker         Run Celery worker"
	@echo "  run-all        Run API + worker (requires tmux)"
	@echo "  shell          Open Python shell with app context"
	@echo ""
	@echo "Database:"
	@echo "  migrate        Run Alembic migrations"
	@echo "  migrate-create Create new migration (usage: make migrate-create MSG='message')"
	@echo "  db-shell       Open PostgreSQL shell"
	@echo "  db-reset       Drop and recreate database (DESTRUCTIVE)"
	@echo ""
	@echo "Testing:"
	@echo "  test           Run all tests"
	@echo "  test-unit      Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-eval      Run evaluation tests (slow)"
	@echo "  test-cov       Run tests with coverage"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint           Run ruff linter"
	@echo "  lint-fix       Run ruff with auto-fix"
	@echo "  typecheck      Run mypy type checker"
	@echo "  format         Format code with ruff"
	@echo "  check          Run lint + typecheck"
	@echo ""
	@echo "Docker:"
	@echo "  docker-build   Build all Docker images"
	@echo "  docker-up      Start all services"
	@echo "  docker-down    Stop all services"
	@echo "  docker-logs    View service logs"
	@echo "  docker-shell   Open shell in API container"
	@echo ""
	@echo "Utilities:"
	@echo "  clean          Remove build artifacts"
	@echo "  ingest         Run ingestion CLI (usage: make ingest FILE=path/to/file.pdf)"

# =============================================================================
# Setup
# =============================================================================
install:
	uv sync --frozen

dev-install:
	uv sync --frozen --all-extras

pre-commit:
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

# =============================================================================
# Development
# =============================================================================
run:
	uv run uvicorn contextforge.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	uv run celery -A contextforge.workers.celery_app worker --loglevel=info --concurrency=4

run-all:
	@echo "Starting API server and Celery worker in tmux..."
	tmux new-session -d -s contextforge-api 'make run'
	tmux new-session -d -s contextforge-worker 'make worker'
	tmux attach-session -t contextforge-api

shell:
	uv run python -c "from contextforge.main import app; import asyncio; print('App loaded. Use app.state for access.')"

# =============================================================================
# Database
# =============================================================================
migrate:
	uv run alembic upgrade head

migrate-create:
	@if [ -z "$(MSG)" ]; then echo "Usage: make migrate-create MSG='your message'"; exit 1; fi
	uv run alembic revision --autogenerate -m "$(MSG)"

db-shell:
	psql $(DATABASE_URL)

db-reset:
	@echo "WARNING: This will destroy all data!"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ]
	uv run alembic downgrade base
	uv run alembic upgrade head

# =============================================================================
# Testing
# =============================================================================
test:
	uv run pytest

test-unit:
	uv run pytest -m "unit"

test-integration:
	uv run pytest -m "integration"

test-eval:
	uv run pytest -m "eval"

test-cov:
	uv run pytest --cov=contextforge --cov-report=term-missing --cov-report=html

# =============================================================================
# Code Quality
# =============================================================================
lint:
	uv run ruff check src tests

lint-fix:
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src

format:
	uv run ruff format src tests

check: lint typecheck

# =============================================================================
# Docker
# =============================================================================
docker-build:
	docker compose -f docker/docker-compose.yml build

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

docker-shell:
	docker compose -f docker/docker-compose.yml exec api bash

dev: docker-up
	@echo "Development environment started!"
	@echo "  API:      http://localhost:8000"
	@echo "  MCP:      http://localhost:8001"
	@echo "  Langfuse: http://localhost:3001"
	@echo "  Grafana:  http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"

# =============================================================================
# Utilities
# =============================================================================
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

ingest:
	@if [ -z "$(FILE)" ]; then echo "Usage: make ingest FILE=path/to/file.pdf"; exit 1; fi
	uv run python scripts/ingest_corpus.py $(FILE)

# =============================================================================
# CI Simulation
# =============================================================================
ci: check test
	@echo "CI pipeline completed successfully!"

# =============================================================================
# Deployment
# =============================================================================
deploy-staging:
	@echo "Deploying to staging..."
	gh workflow run cd-staging.yml

deploy-prod:
	@echo "Deploying to production..."
	@read -p "Version tag (e.g., v1.2.3): " version; \
	gh workflow run cd-prod.yml -f version=$$version

deploy-prod-emergency:
	@echo "EMERGENCY production deployment (skips approval)!"
	@read -p "Version tag: " version; \
	gh workflow run cd-prod.yml -f version=$$version -f skip_approval=true

# =============================================================================
# Documentation
# =============================================================================
docs-serve:
	@echo "Starting docs server at http://localhost:8080..."
	cd docs && python -m http.server 8080

docs-build:
	@echo "Building documentation..."
	# Add Sphinx/MkDocs build commands here if needed
	@echo "Docs are plain Markdown — serving directly"