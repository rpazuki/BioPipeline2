# BioPipeline2 developer entry points.
# Every target assumes ./.venv exists; run `make setup` first.

VENV := .venv
PY := $(VENV)/bin/python
export BP_DATABASE_URL ?= postgresql+psycopg://biopipeline:biopipeline@localhost:55432/biopipeline2

.PHONY: setup db-up db-down db-reset migrate task-image worker revision test test-fast lint typecheck consistency check clean

setup: ## Create the venv and install the backend in editable mode
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "backend[dev]"

db-up: ## Start PostgreSQL
	./scripts/dev/db.sh up

db-down: ## Stop PostgreSQL
	./scripts/dev/db.sh down

db-reset: ## Drop the schema and migrate to head
	./scripts/dev/db.sh reset

migrate: ## Migrate to head
	./scripts/dev/db.sh migrate

task-image: ## Build the task container image
	docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .

worker: ## Run a worker against the dev database
	BP_TASK_DEFAULT_IMAGE=biopipeline2/task-base:dev \
	BP_WORKSPACE_ROOT=$$(pwd)/.workspaces \
	$(PY) -m app.workers.worker

revision: ## Autogenerate a migration: make revision m="add widgets"
	cd backend && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

test: ## Run every test, including those needing PostgreSQL
	$(PY) -m pytest backend/tests

test-fast: ## Domain tests only; no database required
	$(PY) -m pytest backend/tests -m "not db"

lint:
	$(PY) -m ruff check backend
	$(PY) -m ruff format --check backend

typecheck:
	$(PY) -m mypy backend/app

consistency: ## Plan, ADRs, code and READMEs must describe one system
	$(PY) scripts/dev/check_consistency.py

check: lint typecheck consistency test ## Everything CI runs
	cd backend && ../$(PY) -m alembic check

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
