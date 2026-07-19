.DEFAULT_GOAL := help
PY := .venv/bin

.PHONY: help install install-js install-py format format-check lint typecheck test test-js test-py security ci

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: install-js install-py ## Install all dev dependencies

install-js: ## Install the JS/TS workspace
	pnpm install

install-py: ## Create .venv and install the Python toolchain
	python3 -m venv .venv
	$(PY)/pip install --upgrade pip
	$(PY)/pip install -r requirements-dev.txt

format: ## Auto-format all sources
	pnpm run format
	$(PY)/black apps workers evals packages/providers packages/retrieval

format-check: ## Verify formatting without writing
	pnpm run format:check
	$(PY)/black --check apps workers evals packages/providers packages/retrieval

lint: ## Lint all sources
	pnpm run lint
	$(PY)/ruff check apps workers evals packages/providers packages/retrieval

typecheck: ## Run static type checks
	pnpm run typecheck
	$(PY)/mypy apps/api/app workers/src evals/graders packages/providers/fel_providers packages/retrieval/fel_retrieval

test: test-js test-py ## Run all unit tests

test-js: ## Run JS/TS unit tests
	pnpm run test

test-py: ## Run Python unit tests
	$(PY)/pytest

security: ## Run static + dependency security scans
	$(PY)/bandit -q -r apps workers evals packages/providers packages/retrieval -c pyproject.toml
	$(PY)/pip-audit -r requirements-dev.txt
	node scripts/audit-bulk.mjs

ci: format-check lint typecheck test security ## Run the full local quality gate
