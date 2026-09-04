.DEFAULT_GOAL := help
PY := .venv/bin

.PHONY: help install install-js install-py format format-check lint typecheck test test-js test-py security ci

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: install-js install-py ## Install all dev dependencies

install-js: ## Install the JS/TS workspace
	pnpm install

install-py: ## Create .venv and install the Python toolchain (interpreter from .python-version)
	@if [ ! -r .python-version ]; then \
		echo "make install-py: .python-version is missing or unreadable; cannot" >&2; \
		echo "  determine which interpreter CI builds against." >&2; \
		exit 1; \
	fi; \
	pin=$$(tr -d '[:space:]' < .python-version); \
	if [ -z "$$pin" ]; then \
		echo "make install-py: .python-version is empty. Refusing to guess: an" >&2; \
		echo "  empty pin would make the check below look for a command named" >&2; \
		echo "  plain 'python', which on many machines exists and is some other" >&2; \
		echo "  interpreter entirely." >&2; \
		exit 1; \
	fi; \
	if command -v python$$pin >/dev/null 2>&1; then \
		py=python$$pin; \
	elif command -v python3 >/dev/null 2>&1 && \
	     [ "$$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" = "$$pin" ]; then \
		py=python3; \
	else \
		found=$$(command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' || echo none); \
		echo "make install-py: .python-version pins Python $$pin, but python$$pin is not on PATH" >&2; \
		echo "  and python3 is $$found. CI builds against $$pin (.github/workflows/ci.yml uses" >&2; \
		echo "  python-version-file: .python-version), so a venv on another interpreter would" >&2; \
		echo "  not be testing what CI tests. Install Python $$pin and retry." >&2; \
		exit 1; \
	fi; \
	echo "Creating .venv with $$py ($$($$py -V 2>&1))"; \
	$$py -m venv .venv
	$(PY)/pip install --upgrade pip
	$(PY)/pip install -r requirements-dev.txt

format: ## Auto-format all sources
	pnpm run format
	$(PY)/black apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology packages/calculation-engine

format-check: ## Verify formatting without writing
	pnpm run format:check
	$(PY)/black --check apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology packages/calculation-engine

lint: ## Lint all sources
	pnpm run lint
	$(PY)/ruff check apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology packages/calculation-engine

typecheck: ## Run static type checks
	pnpm run typecheck
	$(PY)/mypy apps/api/app workers/src evals/graders packages/providers/fel_providers packages/retrieval/fel_retrieval packages/retrieval-evals/fel_retrieval_evals packages/ontology/fel_ontology packages/calculation-engine/fel_calculation_engine

test: test-js test-py ## Run all unit tests

test-js: ## Run JS/TS unit tests
	pnpm run test

test-py: ## Run Python unit tests
	$(PY)/pytest

security: ## Run static + dependency security scans
	$(PY)/bandit -q -r apps workers evals packages/providers packages/retrieval packages/retrieval-evals packages/ontology packages/calculation-engine -c pyproject.toml
	$(PY)/pip-audit -r requirements-dev.txt
	node scripts/audit-bulk.mjs

ci: format-check lint typecheck test security ## Run the full local quality gate
