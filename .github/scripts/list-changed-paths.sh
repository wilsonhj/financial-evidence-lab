#!/usr/bin/env bash
set -euo pipefail

# --no-renames lists a moved file's source path too, so moving a
# shared file out of a shared directory still counts as touching it.
# -z stops Git from C-quoting non-ASCII paths ("docs/decisions/caf\303\251.md"),
# which the anchored patterns in the workflow would never match. A path that
# itself contains a newline still splits; that case is out of scope.
git diff --no-renames --name-only -z "$1" "$2" | tr '\0' '\n'
