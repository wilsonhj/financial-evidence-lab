#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
runtime_python="${1:-python}"
runtime_builder=$(mktemp -d)
trap 'rm -rf "$runtime_builder"' EXIT

"$runtime_python" -m pip install --require-hashes -r requirements.lock
"$runtime_python" -m venv "$runtime_builder/venv"
"$runtime_builder/venv/bin/python" -m pip install --require-hashes \
  -r scripts/runtime/build.lock
# First-party wheels come from this checkout. Build isolation and dependency
# resolution are disabled so this step cannot fetch an unpinned dependency.
"$runtime_builder/venv/bin/python" -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir "$runtime_builder/wheels" ./packages/providers \
  ./packages/ontology ./packages/retrieval ./workers ./apps/api
"$runtime_python" -m pip install --no-deps "$runtime_builder"/wheels/*.whl
"$runtime_python" -m pip check
"$runtime_python" -I scripts/runtime/verify.py
