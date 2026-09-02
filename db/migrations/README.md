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
- Apply them with `python scripts/db/migrate.py` (`make db-migrate`), never a
  `for f in *.sql; do psql -f "$f"; done` loop. The applier records every file
  and its sha256 in a `schema_migrations` ledger, so re-running is a no-op and
  editing an applied file is caught as checksum drift rather than silently
  diverging from the deployed schema. `--check` (`make db-check`) is the
  read-only gate; `--baseline` adopts a database an older shell loop migrated.
  Files in `tests/` are harnesses, not migrations: the applier only reads
  `NNNN_*.sql` directly in this directory and never descends into `tests/`.
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

## 0007 jobs hardening (#189)

Additive changes to 0001's `jobs` table, for the three queue gaps in #189:

- `available_at timestamptz NOT NULL DEFAULT now()` — retry scheduling.
  `queue.claim_one` filters on `available_at <= now()`, and `queue.fail`
  pushes it forward by an exponential, jittered backoff (base 5s, factor 2,
  cap 15 min) instead of requeueing a failed attempt for an immediate
  re-claim. `started_at` records the most recent claim;
  `cancel_requested_at` carries a cooperative cancellation request.
- `jobs_heartbeat_running_idx` on `(heartbeat_at) WHERE status = 'running'`
  — the reaper predicate had no supporting index.
- `jobs_claim_available_idx` — 0001's claim key on
  `(queue, priority, created_at)` partial to `status = 'queued'`, plus
  `INCLUDE (available_at)`, so the new claim filter is evaluated from the
  index rather than a heap fetch per scheduled retry.
  0001's `jobs_claim_idx` is left in place (migrations are append-only) and
  the key order is deliberately unchanged: `claim_one` still needs
  `(priority, created_at)` order, so moving `available_at` into the key
  would buy a range scan at the price of a sort in the common case where
  nothing is backed off.

Cancellation is the only `fel_app` write added, and it takes **both** a
column-level grant and a policy — neither is sufficient alone:

- `GRANT UPDATE (cancel_requested_at) ON jobs TO fel_app` keeps every other
  column read-only to the request role (`status`, `attempts`, `lease`,
  `payload`, `error`), so a tenant can ask for a stop but cannot forge a
  terminal state. The harness pins this: writing `status` or `attempts` as
  `fel_app` must raise `42501`.
- `jobs_cancel_own_org`, a `RESTRICTIVE ... FOR UPDATE TO fel_app` policy
  requiring `org_id = fel_claim_org_id()`. 0001's permissive `jobs_tenant`
  policy also admits `org_id IS NULL` (tenantless platform jobs); that is
  right for reading but would let any tenant cancel a platform job, so this
  ANDs an own-org-only rule onto `UPDATE` alone and leaves `SELECT`/`INSERT`
  as they were. It is scoped `TO fel_app` so the future worker service role
  does not inherit a rule written for request paths.

Cancellation never changes `status` by itself: the worker polls
`queue.is_cancel_requested` at a stage boundary and winds the run down, so a
partially written run reaches a consistent terminal state rather than being
torn out from under a live worker.

Reaping is no longer unconditional. `queue.reap_stale` requeues a stale
claim only while `attempts < max_attempts` and otherwise parks it as
`failed` with a `REAPED_EXHAUSTED` error envelope — before this, a job that
reliably killed its worker was reaped, re-claimed and killed again forever.

## 0006 — `extraction_run_steps.output` (ADR-0011)

Adds `output jsonb` (nullable) to `extraction_run_steps`, so a stage's result is
durable on the step row instead of riding in the `step_completed` event payload.
That is what makes the published "event payloads are metadata-only" guarantee
true; the redaction carve-out the old arrangement required is deleted rather
than narrowed. `0004` is untouched — append-only, corrected forward, as `0005`
did for `0003`.

Three things a reader of this migration should not have to rediscover:

- **The pair CHECK is `NOT VALID`, permanently.**
  `CHECK ((output IS NULL) = (output_hash IS NULL))` enforces the invariant on
  every INSERT and UPDATE from 0006 onward, but declines to re-litigate history.
  It has to: rows written before 0006 carry `output_hash` with no `output`, and
  they cannot be repaired. Every UPDATE on `extraction_run_steps` runs
  `fel_assert_extraction_run_open`, which raises for terminal runs, and DELETE is
  refused outright. Do not run `VALIDATE CONSTRAINT` while such rows exist.
  Backfill is impossible by construction, not merely inconvenient, which is why
  the worker keeps a resume-side guard (`workflow._is_recoverable`) that re-runs
  a stage whose checkpoint cannot hand back what it claims.
- **No grant, RLS or trigger change was needed.** `0004`'s
  `GRANT SELECT, INSERT, UPDATE ON extraction_run_steps TO fel_app` is at TABLE
  level, so the new column is covered automatically; 0006 restates it as a no-op
  for the reader. Do not generalise from that: `extraction_runs`' UPDATE grant is
  COLUMN-scoped, so a new column there would need an explicit grant.
  `extraction_run_steps_isolation` is column-agnostic, and
  `fel_guard_extraction_run_child` enumerates its immutable pins explicitly —
  `output` is not among them, so a step may advance it within an open run, which
  is what `0004`'s own comment already said.
- **`record_confidence` loses its `NOT NULL`** (issue #194). The extraction
  pipeline has no calibrator yet (#62) and was persisting `0`, a legitimate value
  on the column's 0-1 scale that reads as "certainly wrong". NULL is the only
  spelling of "not scored". The range CHECK is untouched and still binds every
  non-NULL value.

Harness: `tests/0006_extraction_step_output.test.sql`. It exercises, as
`fel_app` with `request.jwt.claims` set, an INSERT carrying `output`, both halves
of the pair CHECK, an `output` UPDATE on an open run, an identity-pin UPDATE
still being refused, a cross-org read returning nothing, and NULL confidence
persisting; then, as the superuser, that the terminal-run guard still rejects a
late INSERT, a late `output` rewrite and a DELETE.

`tests/0004_extraction_core.test.sql` gained one line: its `fel_app` step
advances `output` alongside `output_hash`, because the pair CHECK now forbids the
hash on its own. The `0004` migration itself is byte-unchanged.
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
