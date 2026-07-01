# Task runner for pyverdex. `make help` lists targets.
# Adopted from the Project Keel standard (CONVENTIONS.md). The Python toolchain
# runs through `uv` (project interpreter, python3.11); the structural checker is
# pure-stdlib so it runs under any python3. The web app lives in web/ for now and
# migrates to src/frontend/react-vite in a later phase.
.DEFAULT_GOAL := help
PY ?= python3
UV ?= uv run

# Frontend apps = any dir with a package.json (web/ today, src/frontend/* later).
FE_APPS := $(dir $(wildcard web/package.json src/frontend/*/package.json))

.PHONY: help check verify test test-fe lint lint-py lint-fe fmt typecheck \
        typecheck-py typecheck-fe fe-install run serve site demo

help: ## List tasks
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

check: ## Validate structure + frontmatter + manifest (pure stdlib, 3.6-safe)
	$(PY) scripts/check_structure.py

verify: check lint typecheck test test-fe ## Run all gates (structure + lint + types + tests)

test: ## Run the Python test suite
	$(UV) pytest

test-fe: ## Run the frontend test suite (vitest)
	@for app in $(FE_APPS); do \
		if [ -d "$$app/node_modules" ]; then echo "vitest: $$app"; (cd $$app && npm run --silent test:run) || exit 1; \
		else echo "skip $$app (no node_modules - run 'make fe-install')"; fi; \
	done

lint: lint-py lint-fe ## Lint everything (Python + frontend)
lint-py: ## Lint Python (ruff)
	$(UV) ruff check src tests
lint-fe: ## Lint frontend apps
	@command -v npm >/dev/null 2>&1 || { echo "npm not found; skipping frontend lint"; exit 0; }
	@for app in $(FE_APPS); do \
		if [ -d "$$app/node_modules" ]; then echo "lint: $$app"; (cd $$app && npm run --silent lint 2>/dev/null || echo "  (no lint script)"); fi; \
	done

fmt: ## Format Python (ruff)
	$(UV) ruff format src tests

typecheck: typecheck-py typecheck-fe ## Type-check everything (Python + frontend)
typecheck-py: ## Type-check Python (mypy)
	$(UV) mypy src
typecheck-fe: ## Type-check frontend apps (tsc)
	@command -v npm >/dev/null 2>&1 || { echo "npm not found; skipping frontend typecheck"; exit 0; }
	@for app in $(FE_APPS); do \
		if [ -d "$$app/node_modules" ]; then echo "typecheck: $$app"; (cd $$app && npx tsc --noEmit) || exit 1; \
		else echo "skip $$app (no node_modules)"; fi; \
	done

fe-install: ## Install frontend deps for all FE apps
	@for app in $(FE_APPS); do echo "npm install: $$app"; (cd $$app && npm install) || exit 1; done

run: ## Run the pyverdex CLI (e.g. `make run ARGS="run ./demo/sample_app"`)
	$(UV) pyverdex $(ARGS)
serve: ## Serve the dashboard API (FastAPI on :8000)
	$(UV) pyverdex serve
site: ## Build the web frontend
	cd web && npm run build
demo: ## Run the demo
	bash demo/run_demo.sh
