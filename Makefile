.DEFAULT_GOAL := help
PY := .venv/bin

.PHONY: help install install-js install-py format format-check lint typecheck test test-js test-py db-migrate db-check security ci

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
	$(PY)/black apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology scripts conftest.py

format-check: ## Verify formatting without writing
	pnpm run format:check
	$(PY)/black --check apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology scripts conftest.py

lint: ## Lint all sources
	pnpm run lint
	$(PY)/ruff check apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology scripts conftest.py

typecheck: ## Run static type checks
	pnpm run typecheck
	$(PY)/mypy apps/api/app workers/src evals/graders packages/providers/fel_providers packages/retrieval/fel_retrieval packages/retrieval-evals/fel_retrieval_evals packages/ontology/fel_ontology

test: test-js test-py ## Run all unit tests

test-js: ## Run JS/TS unit tests
	pnpm run test

test-py: ## Run Python unit tests
	$(PY)/pytest

db-migrate: ## Apply pending migrations to $$DATABASE_URL / $$TEST_DATABASE_URL
	$(PY)/python scripts/db/migrate.py

db-check: ## Fail if migrations are pending or an applied file changed
	$(PY)/python scripts/db/migrate.py --check

eval-retrieval-gate: ## Grade the benchmark seed through the retrieval pipeline (needs TEST_DATABASE_URL)
	PYTHONPATH=evals:packages/providers:packages/retrieval:packages/retrieval-evals \
		$(PY)/python -m harness.retrieval_gate --out evals/reports/retrieval-gate/latest.json

security: ## Run static + dependency security scans
	$(PY)/bandit -q -r apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology scripts -c pyproject.toml
	$(PY)/pip-audit -r requirements.txt
	$(PY)/pip-audit -r requirements-dev.txt
	node scripts/audit-bulk.mjs

ci: format-check lint typecheck test security ## Run the full local quality gate
