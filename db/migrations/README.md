# Database migrations

Plain SQL migrations applied in lexical filename order:
`NNNN_short_description.sql`, starting at `0001_`.

Rules (see ADR-0002 and the constitution):

- Migrations are append-only; never edit or delete an applied migration —
  correct forward with a new one.
- `db/migrations/**` is a shared path owned by the integration lead; changes
  require the `contract-change` process once contracts are frozen.
- Every migration must apply cleanly to an empty database. CI's `database`
  job applies all migrations to a disposable Postgres 17 container and runs
  the backup-restore smoke test (`infra/scripts/backup_restore_smoke.sh`).
- Tenant-scoped tables must ship with their row-level-security policies in
  the same migration that creates them.

The first real migration lands with `M0-CONTRACTS`/`M0-PLATFORM`; the
directory is intentionally empty until then.
