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

## Guard locks and role coverage

Row locks (`FOR SHARE` / `FOR UPDATE`) inside trigger guards require the
`UPDATE` privilege on the locked table **for the role executing the
statement** — triggers are not `SECURITY DEFINER`, so a guard that locks a
table the API role cannot lock fails with `42501` in production while
passing any harness that runs as the migration superuser. That is exactly
how the 0005 bug shipped: 0003's `fel_guard_query()` took `FOR SHARE` on
`retrieval_index_versions`, which is deliberately `SELECT`-only to
`fel_app`.

Load-bearing locks — do **not** copy the 0005 removal recipe to these:

- `fel_guard_retrieval_item` (0003) locks `retrieval_index_versions`
  `FOR SHARE` to serialize item inserts against the `building -> ready`
  publish transition.
- `fel_guard_retrieval_embedding` (0003) does the same for embedding
  inserts.

Both run only in worker (service-role) paths that build indexes, so the
`SELECT`-only grant to `fel_app` is not violated. They are correct because
the concurrency they guard against (publishing an index while rows are
still being added) is real; 0005's lock was removable only because
published index versions are immutable.

Incidental grant coupling — these guards row-lock a tenant table and are
legal for `fel_app` **only** because of a column-level `GRANT UPDATE`:

- `fel_assert_run_open` (`FOR SHARE`) and `fel_guard_retrieval_event`
  (`FOR UPDATE`) lock `retrieval_runs`; they depend on
  `GRANT UPDATE (status, budget_usage, cost_usd, timings_ms, finished_at,
error) ON retrieval_runs` (0003). Every `fel_app` insert into
  `retrieval_events`, `retrieval_candidates`, `claims`, and `citations`
  goes through one of them.
- `fel_assert_extraction_run_open` (`FOR SHARE`) locks `extraction_runs`;
  it depends on `GRANT UPDATE (status, ...) ON extraction_runs` (0004).
  Every `fel_app` insert/update on `extraction_run_steps`,
  `extraction_run_events`, `extraction_proposals`, and
  `extraction_proposal_evidence` goes through it.

Narrowing or revoking either `GRANT UPDATE` silently breaks those insert
paths. The harnesses pin this: revoking the grant makes the as-`fel_app`
sections of `tests/0003`/`tests/0004` fail with `42501`.

Harness convention: every DML path granted to `fel_app` must be exercised
under `SET LOCAL ROLE fel_app` (with `request.jwt.claims` set) in the
migration's harness, not only as the superuser — superuser-only coverage
cannot catch privilege/lock bugs of this class. Shared helper:
`tests/_helpers.sql` (included via `\ir`; it does not match `*.test.sql`,
so CI never runs it directly).

Both roles are subject to this: `0008` gives `fel_worker` `UPDATE ON
retrieval_index_versions` and column-level `UPDATE ON extraction_runs` for
exactly the same lock reason, and a new guard that row-locks a table must be
checked against **both** roles' privileges, not just `fel_app`'s.

## 0008 — worker service role (`fel_worker`)

The job path now has its own least-privilege role (issue #190, ADR-0013):
`NOLOGIN`, no `DELETE` anywhere, no DDL, no `BYPASSRLS`, no ownership. Before
`0008` the worker connected as the migration/owner superuser, which bypassed
RLS, every grant and every DDL restriction.

- Grants are derived EMPIRICALLY from the SQL the worker executes
  (`workers/src/fel_workers/**` plus `fel_retrieval/{index_build,lanes}.py`),
  including the privileges the guards' row locks need. TABLE-level `UPDATE`
  on `jobs` and `extraction_run_steps` so later columns are covered; a column
  list on `extraction_runs`, mirroring the `fel_app` grant.
- Corpus and shared retrieval artifacts have no RLS — grants alone govern
  them. The tenant tables get worker policies that pin ORG CONSISTENCY (a
  child row's `org_id` must match its parent run/proposal/conflict/workspace);
  they are not tenant isolation, which RLS cannot express for a cross-tenant
  service. See ADR-0013.
- Adoption is opt-in per deployment via `FEL_WORKER_DB_ROLE` (unset = previous
  behaviour; set = `SET ROLE` on every worker connection).

**Every new worker-written table must extend the `0008` grant set and
`tests/0008_worker_role.test.sql` in the same migration that creates it.** The
harness performs one representative write per granted table class as
`fel_worker` and asserts `DELETE`/`ALTER TABLE`/`CREATE TABLE` raise `42501`.
`workers/tests` additionally runs green under
`FEL_WORKER_DB_ROLE=fel_worker`, which is the check that catches a grant the
derivation missed.

## 0009 — platform FK hygiene

`audit_events.org_id`, `usage_events.org_id` and `jobs.org_id` were bare uuid
columns; they now reference `organizations(id) ON DELETE RESTRICT`, added
`NOT VALID` and then `VALIDATE`d so the lock is brief. `jobs.org_id` stays
nullable (platform jobs carry no tenant) — a foreign key permits NULL.
`RESTRICT`, never `CASCADE`: audit and usage rows are the compliance and
billing record, so an organization carrying them is deliberately not
deletable. `workspaces.active_scenario_id` gets a COMMENT marking it reserved
for M4; the migration that creates `scenarios` must add the
`(active_scenario_id, org_id)` composite FK.
