# ADR-0014: Checksummed migration ledger and single applier

Status: Proposed
Date: 2026-09-02
Occasioned by: issue #199 (`contract-change`), part of the 2026-09-01
architecture review (#188).
Touches shared paths: `.github/workflows/ci.yml`, `infra/**`, `Makefile`,
`db/migrations/README.md`.

## Context

Migrations are hand-written SQL files under `db/migrations/NNNN_*.sql` with
behavioural harnesses under `db/migrations/tests/`. Until this decision they
were applied by three independent shell loops of the form
`for f in db/migrations/*.sql; do psql -f "$f"; done` in CI, in the
backup-restore smoke script, and in the local development guide. Nothing
recorded which files had been applied, so:

- the loop could only ever run against an empty database; re-running it
  against a live database failed on the first `CREATE TABLE`;
- neither Railway service definition applied migrations at all, so a deploy
  that needed a schema change had no sanctioned path;
- an edit to an already-applied migration file was invisible, which
  defeats the "migrations are frozen contracts" rule in ADR-0001;
- the CI harness loop reported success when it ran zero harnesses.

The repository deliberately avoids an ORM and a migration framework. The
harnesses assert exact guard behaviour and role privileges, and the migration
text is reviewed as a contract artefact. Adopting Alembic or Sqitch would add a
second source of truth for the same SQL.

## Decision

1. A ledger table `schema_migrations(version text primary key, checksum text
   not null, applied_at timestamptz not null default now())` records every
   applied file. `version` is the `NNNN_name` stem; `checksum` is the SHA-256
   of the file bytes.
2. One applier, `scripts/db/migrate.py`, depending only on the standard
   library and `psycopg` (already a runtime dependency). It creates the ledger
   if missing, takes a session advisory lock so two appliers cannot race,
   verifies the checksum of every applied file and fails closed on drift,
   applies pending files in filename order each in its own transaction, and
   records the ledger row in that same transaction. `--check` exits non-zero
   when anything is pending or drifted; `--dry-run` prints the plan;
   `--baseline` records existing files as applied without running them, for
   databases that were migrated by the old loop.
3. The applier is the only sanctioned way to apply migrations: CI, the smoke
   script, the local guide and the Railway API service all call it. The
   worker service runs `--check` at start and refuses to run against a stale
   schema. The API service is the single writer of schema changes at deploy.
4. The CI harness step fails unless at least one harness ran.
5. The backup-restore smoke test dumps and restores roles
   (`pg_dumpall --roles-only`) before the database, so grants survive a
   fresh-cluster restore.

## Consequences

- Editing an applied migration is a build failure, which is the intended
  enforcement of ADR-0001. Corrections ship as new numbered migrations, as
  `0005` already did for `0003`.
- Migration numbering must stay unique and monotonic; two concurrent packages
  that both add a migration must have their numbers reserved at dispatch, as
  this review did (`0006` #157, `0007` #189, `0008` #190, `0009` #197).
- `schema_migrations` is owner-only: neither `fel_app` nor `fel_worker`
  receives grants on it.
- The harnesses are still applied by `psql`, never by the applier, and never
  recorded in the ledger.

## Alternatives rejected

- **Alembic or Sqitch.** A second toolchain and a second place where SQL
  lives; the harness style depends on plain files.
- **Keep the shell loop and add `IF NOT EXISTS` everywhere.** Hides drift and
  makes partial failures unrecoverable.
- **Railway `preDeployCommand` only, no ledger.** Solves deploy but not drift
  detection or idempotency.

## Revisit triggers

- A migration needs an out-of-transaction statement (`CREATE INDEX
  CONCURRENTLY`); the applier then needs a per-file `-- migrate: no-transaction`
  directive.
- More than one deploy target writes schema; the single-writer rule then needs
  a lock outside the database.

## Verification

- Applying twice is a no-op on the second run.
- Modifying an applied file fails `--check` and the CI job.
- CI fails when the harness glob matches nothing.
- The smoke test restores into an empty cluster and every harness passes on
  the restored database.
