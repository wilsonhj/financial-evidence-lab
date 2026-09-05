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

Worker-role note: no service role exists yet. The index build path
(`retrieval_items` / `retrieval_embeddings` inserts and index version
status transitions) assumes one; when it is introduced it will need
`UPDATE ON retrieval_index_versions` (for the status transitions and the
guards' `FOR SHARE` locks) in addition to `INSERT` on the artifact tables.

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
