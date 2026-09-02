# ADR-0013: Two-role database model (fel_app + fel_worker)

Status: Proposed
Date: 2026-09-01

Issues: #190 (worker service role), #197 (platform FK hygiene)
Migrations: `db/migrations/0008_worker_role.sql`,
`db/migrations/0009_platform_fk_hygiene.sql`

## Context

Migration `0001_platform_core.sql` created exactly one non-owner role,
`fel_app`, and its header says the quiet part out loud: "the service role
(workers/admin) bypasses RLS by design". There was no service role. The job
path — ingestion, corpus publication, the retrieval index build, extraction
persistence — connected as the migration/owner superuser, and so ran with:

- RLS bypassed on every tenant table,
- `DELETE` on immutable evidence (corpus documents, retrieval items,
  extraction proposals) that the data model spends hundreds of lines of
  triggers forbidding,
- DDL on the whole schema,
- ownership of every object, so no grant in `0002`–`0005` constrained it.

The API's blast radius is bounded by a role with a hand-derived grant list;
the worker's was the entire database. That asymmetry is not justified by
anything in the architecture — the worker runs untrusted INPUT (SEC bytes,
job payloads, model output), which is if anything the stronger argument for
least privilege.

`db/migrations/README.md` recorded the gap as a "Worker-role note" and
predicted part of the answer (`UPDATE ON retrieval_index_versions`). This ADR
replaces that note with the role itself.

## Decision

**Two runtime roles, and no runtime process connects as the owner.**

| Path | Role | Reaches the database via |
|---|---|---|
| Request path (API) | `fel_app` | RLS keyed on `request.jwt.claims` |
| Job path (workers) | `fel_worker` | grants + org-consistency policies |
| Migrations only | owner/superuser | `psql` in CI/deploy, never a service |

`fel_worker` (created in `0008`, `NOLOGIN`, granted to the deployment's login
role) has: no `DELETE` on any table, no DDL, no `BYPASSRLS`, no ownership.

### How the grants are derived

Empirically, from the SQL the worker actually executes — not from the schema
and not from what a worker "might need":

1. Enumerate every statement in `workers/src/fel_workers/**` and
   `packages/retrieval/fel_retrieval/{index_build,lanes}.py` (the index build
   is a worker path that happens to live in a package).
2. Group by table and by operation actually performed. Anything absent is not
   granted: the worker never inserts `organizations`, `workspaces`,
   `extraction_runs`, `queries`, `claims` or `citations`, so it cannot.
3. Add the privileges the *guards* need, not just the statements: a row lock
   (`FOR SHARE`/`FOR UPDATE`) requires `UPDATE` on the locked table for the
   role executing the statement. This is the 0005 bug class, and it is why
   `fel_worker` holds `UPDATE` on `retrieval_index_versions` (locked by
   `fel_guard_retrieval_item`/`fel_guard_retrieval_embedding`) and on
   `extraction_runs` (locked by `fel_assert_extraction_run_open`).
4. Choose the grant shape per table. TABLE-level `UPDATE` where the worker
   rewrites rows wholesale and the column set will keep growing (`jobs`,
   `extraction_run_steps`); a column list where the data model already pins
   which columns may move (`extraction_runs`, mirroring 0004's `fel_app`
   grant, with `fel_guard_extraction_run` as the backstop).

### RLS for a cross-tenant service

`fel_claim_org_id()` is NULL for a worker, so the existing policies would hide
every tenant row from it. RLS cannot express tenant isolation for the job
path: a worker legitimately runs work for every org, and the real tenant
boundary is the job -> run binding in `extraction/handler.py` plus 0004's
guards. So `0008`'s worker policies pin **org consistency** instead:

- `jobs`, `extraction_runs`, `workspaces`: permissive, and read/update-only
  (no INSERT or DELETE privilege to go with them).
- every child table: `org_id` must equal the org of the parent run
  (`extraction_run_steps`, `extraction_run_events`, `extraction_proposals`),
  parent proposal (`extraction_proposal_evidence`), parent workspace
  (`extraction_conflicts`), or parent conflict
  (`extraction_conflict_members`).

Corpus (`0002`) and shared retrieval artifacts (`0003`) carry no `org_id` and
no RLS; grants alone govern them, exactly as they do for `fel_app`.

### How the grants are tested

Two layers, because either alone is known to be insufficient:

1. `db/migrations/tests/0008_worker_role.test.sql` performs one representative
   write per granted table class under `SET LOCAL ROLE fel_worker` and asserts
   the boundaries raise `42501`: `DELETE` on `jobs`, on corpus tables and on
   extraction proposals; `ALTER TABLE`; `CREATE TABLE`; inserting
   organizations or workspaces.
2. The Python suites run against a real database with
   `FEL_WORKER_DB_ROLE=fel_worker`: `workers/tests/conftest.py` cleans its
   slate as the superuser and then adopts the role for the test body, so
   `workers/tests` exercises the ingestion, queue, consumer and extraction
   paths under the role rather than under the owner. A missing grant surfaces
   as a test failure, not as a production `42501` hours into a retry cycle.
   (Verified negatively: running the same suite with
   `FEL_WORKER_DB_ROLE=fel_app` fails, so the switch is demonstrably live.)

`packages/retrieval/tests` fixtures are owned by another workstream and still
connect as the owner, so the index-build grants are covered by layer 1 only.

### Rollout: `FEL_WORKER_DB_ROLE`

The switch is opt-in, and unset means today's behaviour byte for byte. When
set, every worker connection runs `SET ROLE <role>` immediately after connect:
the entrypoint's own connection (`fel_workers.__main__.run_main`) and the
lease-heartbeat connection factory (`consumer.py`) both route through
`fel_workers.storage.apply_worker_db_role`. The value is validated against
`^[a-z_][a-z0-9_]*$` because Postgres accepts no bind parameter in `SET ROLE`;
a value that is not a plain identifier exits 2 rather than being quoted and
hoped over.

This shape exists because a grant the derivation missed does not fail a
request — it fails a JOB, which retries, exhausts its attempts, and lands in
`jobs.error` where nobody is looking. Staged adoption (staging first, then
production, with the variable removable in one deploy) is worth more than the
elegance of a hard cutover.

## Consequences

- **Every new worker-written table extends `0008`'s grant set and its
  harness, in the same migration that creates the table.** A table created
  without a grant is invisible to the job path the moment the switch is on;
  a grant added without a harness case is unverified.
- The same applies to new columns on a table with a column-level grant
  (`extraction_runs`): either add the column to the list or convert that grant
  to TABLE-level with a note saying why.
- A future guard that row-locks a table must check both roles' `UPDATE`
  privileges, not just `fel_app`'s. The README's "Guard locks and role
  coverage" section now has two roles to reason about.
- `0009`'s foreign keys are part of the same hygiene: `audit_events.org_id`,
  `usage_events.org_id` and `jobs.org_id` now reference `organizations` with
  `ON DELETE RESTRICT`, so neither role can write billing, audit or queue rows
  for a tenant that does not exist. Tests that enqueued jobs for invented
  tenants now seed the organization first (`workers/tests/conftest.py`:
  `ensure_organization`).
- Deleting an organization now fails while audit/usage/job history references
  it. That is deliberate — those are the compliance and billing record — but
  it means tenant offboarding needs an explicit, ordered procedure rather than
  a `DELETE`.
- `sentry-sdk` remains OUT of every requirements file; the worker's Sentry
  init (issue #203) imports it lazily and logs a warning when a DSN is
  configured without the package installed.

## Alternatives considered

- **`BYPASSRLS` on `fel_worker`.** Simpler, and would need no worker policies
  — but it re-creates the property this ADR exists to remove: a job path that
  can read and write any row anywhere. The org-consistency policies cost a
  subquery per row and keep the parent/child org relationship enforced by the
  database rather than by the handler alone.
- **One role for both paths.** The request path's grants are deliberately
  narrower (no corpus writes, no index build); merging them would widen the
  API's reach to satisfy the worker, which is the wrong direction.
- **Row-level tenant isolation for the worker.** Not expressible: the worker
  has no tenant. Isolation lives in the job binding; RLS here pins
  consistency, and this ADR says so rather than implying a guarantee the
  mechanism cannot give.
