# BioPipeline2 developer entry points.
# Every target assumes ./.venv exists; run `make setup` first.

VENV := .venv
PY := $(VENV)/bin/python
export BP_DATABASE_URL ?= postgresql+psycopg://biopipeline:biopipeline@localhost:55432/biopipeline2

.PHONY: setup db-up db-down db-reset migrate seed task-image worker reaper scheduler revision test test-fast spike
.PHONY: lint typecheck consistency openapi api check clean
.PHONY: ui-setup ui ui-test ui-lint ui-typecheck ui-build ui-generate ui-check e2e

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

seed: ## Create the development accounts: BP_SEED_ADMIN_PASSWORD=... make seed
	$(PY) scripts/dev/seed.py

task-image: ## Build the task container image
	docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .

reaper: ## Run the reaper against the dev database
	BP_ARTIFACT_ROOT=$$(pwd)/.artifacts \
	$(PY) -m app.workers.reaper

scheduler: ## Run the scheduler against the dev database
	$(PY) -m app.workers.scheduler

worker: ## Run a worker against the dev database
	BP_TASK_DEFAULT_IMAGE=biopipeline2/task-base:dev \
	BP_WORKSPACE_ROOT=$$(pwd)/.workspaces \
	BP_ARTIFACT_ROOT=$$(pwd)/.artifacts \
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

openapi: ## Regenerate the committed API contract
	$(PY) scripts/dev/export_openapi.py

api: ## Run the API against the dev database
	# CORS and insecure cookies are for development only, where the frontend
	# runs on its own origin. The production settings validator refuses to boot
	# with either of them relaxed.
	BP_ARTIFACT_ROOT=$$(pwd)/.artifacts BP_WORKSPACE_ROOT=$$(pwd)/.workspaces \
	BP_CORS_ORIGINS='["http://localhost:3000"]' BP_SECURE_COOKIES=false \
	$(VENV)/bin/uvicorn --factory app.api.main:get_app --reload --port 8000 \
	  --app-dir backend

# --- frontend ---------------------------------------------------------------
#
# Separate targets rather than one `check` that needs Node: the backend must
# stay testable on a machine that has never installed npm.

ui-setup: ## Install the frontend dependencies
	cd frontend && npm install

ui: ## Run the frontend against a local API on :8000
	cd frontend && NEXT_PUBLIC_API_ORIGIN=http://localhost:8000 npm run dev

ui-generate: ## Regenerate the TypeScript client from the committed contract
	cd frontend && npm run generate

ui-lint:
	cd frontend && npm run lint && npm run format:check

ui-typecheck:
	cd frontend && npm run typecheck

ui-test:
	cd frontend && npm run test

ui-build:
	cd frontend && npm run build

ui-check: ui-lint ui-typecheck ui-test ## Everything CI runs for the frontend
	cd frontend && npm run generate:check

spike: ## Phase 0b: run a real-shaped pipeline end to end through containers
	BP_ARTIFACT_ROOT=$$(pwd)/.artifacts BP_WORKSPACE_ROOT=$$(pwd)/.workspaces \
	BP_TASK_DEFAULT_IMAGE=biopipeline2/task-base:dev \
	$(PY) scripts/dev/spike.py

e2e: ## Playwright against a running API and a seeded database
	cd frontend && npm run e2e

check: lint typecheck consistency test ## Everything CI runs for the backend
	$(PY) scripts/dev/export_openapi.py --check
	cd backend && ../$(PY) -m alembic check

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
