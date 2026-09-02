#!/usr/bin/env bash
# Backup-restore smoke test (SPEC section 16.2 / M0 exit gate).
#
# Runs against the connection described by the standard PG* environment
# variables. Expects the schema to be migrated already — apply it with
#
#     python scripts/db/migrate.py --database-url "$URL"
#
# which records every file in the `schema_migrations` ledger. This script then
# writes a marker row, dumps cluster roles and the database, wipes the
# database, restores roles first and the database second, and verifies that
# the marker, the migration ledger, and the `fel_app` grants all survived.
#
# Roles are cluster-level, so a same-cluster restore finds them already
# present and the role restore is a no-op; the step exists so that a restore
# into a *fresh* cluster recreates `fel_app` before the dump's GRANT
# statements reference it. Role errors are therefore reported, not fatal.
set -euo pipefail

DUMP_FILE="$(mktemp -t fel-smoke-XXXXXX.dump)"
ROLES_FILE="$(mktemp -t fel-smoke-roles-XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE" "$ROLES_FILE"' EXIT

echo "==> Verifying the database is migrated"
ledger="$(psql --tuples-only --no-align \
  --command "SELECT count(*) FROM schema_migrations;" 2>/dev/null || true)"
if [ -z "$ledger" ] || [ "$ledger" = "0" ]; then
  echo "FAIL: no schema_migrations ledger rows in ${PGDATABASE}." >&2
  echo "      Apply migrations first: python scripts/db/migrate.py" >&2
  exit 1
fi
echo "    ${ledger} migration(s) recorded in schema_migrations"

echo "==> Writing smoke marker"
psql --set ON_ERROR_STOP=1 --quiet <<'SQL'
CREATE TABLE IF NOT EXISTS _ci_smoke (
    id integer PRIMARY KEY,
    marker text NOT NULL
);
INSERT INTO _ci_smoke (id, marker) VALUES (1, 'backup-restore-smoke')
ON CONFLICT (id) DO UPDATE SET marker = EXCLUDED.marker;
SQL

echo "==> Dumping cluster roles"
pg_dumpall --roles-only --file "$ROLES_FILE"

echo "==> Dumping database"
pg_dump --format=custom --file "$DUMP_FILE"

echo "==> Dropping and recreating database ${PGDATABASE}"
# Restore must target a genuinely empty database, not just a fresh public
# schema — migrations may create other schemas or extensions whose leftovers
# would mask missing restore behavior.
psql --dbname postgres --set ON_ERROR_STOP=1 --quiet \
  --command "DROP DATABASE \"${PGDATABASE}\" WITH (FORCE);"
psql --dbname postgres --set ON_ERROR_STOP=1 --quiet \
  --command "CREATE DATABASE \"${PGDATABASE}\";"

echo "==> Restoring roles (before the database, so GRANTs resolve)"
# Roles survive a same-cluster DROP DATABASE, so "role already exists" is the
# expected outcome here and must not fail the run; on a fresh cluster the
# same file is what recreates fel_app.
psql --dbname postgres --quiet --file "$ROLES_FILE" >/dev/null 2>&1 ||
  echo "    (some role statements were skipped)"
echo "    roles applied; existing roles left as they are"

echo "==> Restoring dump into the fresh database"
pg_restore --exit-on-error --dbname "$PGDATABASE" "$DUMP_FILE"

echo "==> Verifying marker survived restore"
marker="$(psql --tuples-only --no-align \
  --command "SELECT marker FROM _ci_smoke WHERE id = 1;")"
if [ "$marker" != "backup-restore-smoke" ]; then
  echo "FAIL: marker not found after restore (got: '$marker')" >&2
  exit 1
fi

echo "==> Verifying the migration ledger survived restore"
restored_ledger="$(psql --tuples-only --no-align \
  --command "SELECT count(*) FROM schema_migrations;")"
if [ "$restored_ledger" != "$ledger" ]; then
  echo "FAIL: schema_migrations has ${restored_ledger} row(s), expected ${ledger}" >&2
  exit 1
fi

echo "==> Verifying fel_app grants survived restore"
granted="$(psql --tuples-only --no-align \
  --command "SELECT has_table_privilege('fel_app', 'organizations', 'SELECT');")"
if [ "$granted" != "t" ]; then
  echo "FAIL: fel_app lost SELECT on organizations after restore (got: '$granted')" >&2
  exit 1
fi

echo "OK: roles, schema, ledger, grants, and data survived backup and restore"
