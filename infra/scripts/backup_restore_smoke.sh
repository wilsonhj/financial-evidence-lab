#!/usr/bin/env bash
# Migration + backup-restore smoke test (SPEC section 16.2 / M0 exit gate).
#
# Runs against the connection described by the standard PG* environment
# variables. Applies every db/migrations/*.sql in lexical order, writes a
# marker row, takes a pg_dump, wipes the schema, restores the dump, and
# verifies the marker survived. Requires only a disposable database — no
# hosted credentials.
#
# MIGRATIONS_DIR overrides the migrations location; CI copies this script
# into the postgres service container (so pg_dump matches the server
# version) and points MIGRATIONS_DIR at the copied directory.
set -euo pipefail

MIGRATIONS_DIR="${MIGRATIONS_DIR:-$(dirname "$0")/../../db/migrations}"
DUMP_FILE="$(mktemp -t fel-smoke-XXXXXX.dump)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo "==> Applying migrations from ${MIGRATIONS_DIR}"
shopt -s nullglob
migrations=("${MIGRATIONS_DIR}"/*.sql)
if [ "${#migrations[@]}" -eq 0 ]; then
  echo "    (no migrations yet — smoke test will still verify dump/restore)"
else
  for f in "${migrations[@]}"; do
    echo "    applying $(basename "$f")"
    psql --set ON_ERROR_STOP=1 --quiet --file "$f"
  done
fi

echo "==> Writing smoke marker"
psql --set ON_ERROR_STOP=1 --quiet <<'SQL'
CREATE TABLE IF NOT EXISTS _ci_smoke (
    id integer PRIMARY KEY,
    marker text NOT NULL
);
INSERT INTO _ci_smoke (id, marker) VALUES (1, 'backup-restore-smoke')
ON CONFLICT (id) DO UPDATE SET marker = EXCLUDED.marker;
SQL

echo "==> Dumping database"
pg_dump --format=custom --file "$DUMP_FILE"

echo "==> Dropping and recreating public schema"
psql --set ON_ERROR_STOP=1 --quiet \
  --command "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "==> Restoring dump"
pg_restore --exit-on-error --dbname "$PGDATABASE" "$DUMP_FILE"

echo "==> Verifying marker survived restore"
marker="$(psql --tuples-only --no-align \
  --command "SELECT marker FROM _ci_smoke WHERE id = 1;")"
if [ "$marker" != "backup-restore-smoke" ]; then
  echo "FAIL: marker not found after restore (got: '$marker')" >&2
  exit 1
fi

echo "OK: migrations applied; backup and restore verified"
