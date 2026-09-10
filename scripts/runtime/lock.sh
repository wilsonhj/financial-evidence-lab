#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# Include package metadata: requirements.txt alone is not the deployed closure.
runtime_inputs=(requirements.txt apps/api/pyproject.toml workers/pyproject.toml
  packages/providers/pyproject.toml packages/retrieval/pyproject.toml
  packages/ontology/pyproject.toml)
uv pip compile "${runtime_inputs[@]}" --python-version 3.11 --universal \
  --generate-hashes --output-file requirements.lock
uv pip compile "${runtime_inputs[@]}" requirements-dev.txt --python-version 3.11 \
  --universal --generate-hashes --constraint requirements.lock \
  --output-file requirements-dev.lock
uv pip compile scripts/runtime/build.in --python-version 3.11 --universal \
  --generate-hashes --output-file scripts/runtime/build.lock
