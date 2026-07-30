# Extraction worker operator runbook (M3-107)

## Job kind

Enqueue `extraction_run` jobs on the `extraction` queue. That queue name is
load-bearing, not a convention: the model binding is scoped to it, so a worker
started with `--queue ingestion` binds no model and fails closed on any
`extraction_run` that reaches it. Setting `FEL_ALLOW_MOCK_LLM` on a
non-extraction worker exits 2 at startup rather than binding a model that
worker has no legitimate use for.

Enqueue tenant-bound: `queue.enqueue(..., org_id=<tenant>)`. `jobs.org_id` is
nullable for platform jobs of other kinds, but an `extraction_run` with a NULL
job org is REFUSED on the durable path — otherwise the payload asserts its own
tenant, and `assert_workspace_ownership` only checks that the payload's org and
workspace agree with each other, never that the enqueuer was entitled to them.

## Payload

Required pins: `run_id`, `org_id`, `workspace_id`, `entity_id`, `modes`,
`as_of`, `input_hash` (or `input_manifest`), `provider`, `model`.

Inline `evidence` (or `spans` — exact synonyms, identical on every path) blocks
carry `source_span_id`, `document_version_id`, `text`, and optional `text_hash`.
They supply the run's text and nothing else. In particular they do NOT affect
where output is written: with a database connection, output always persists to
Postgres. (Inline evidence used to silently select in-memory stores, so a run
returned `waiting_review`, the job was marked `succeeded`, and not one row was
written to `extraction_runs`, `extraction_proposals`,
`extraction_proposal_evidence`, `extraction_conflicts`, `extraction_run_steps`
or `extraction_run_events`.)

Durable runs therefore need the `extraction_runs` row and the workspace seeded
first — the run row is created `queued` by the producer, and the worker
promotes it to `running`.

## Smoke runs without seeding

`FEL_EXTRACTION_MEMORY_STORES=1` sends extraction output to in-memory stores,
so the pipeline can be exercised end to end against inline evidence with no
`extraction_runs` row and no workspace. Everything it produces is DISCARDED
when the process exits while jobs still complete as `succeeded`, so it is a
non-production option only: it logs a warning at startup and names every job it
runs that way. It is the only way to select memory stores while a connection is
live — the choice belongs to the operator, not to whoever enqueued the job.

## Budgets

Default ADR-0007 caps: 10 calls, 100k input tokens, 20k output tokens,
USD 2.00, 600s wall. Hard stops raise typed `BudgetExceeded`.

## Review semantics

Every proposal is persisted as `needs_review`. There is no auto-approve path.
Zero-proposal abstention succeeds the run; provider refusal / schema / budget
failures mark the run `failed`.

## Telemetry

`fel_workers.extraction.telemetry` redacts prompts, messages, source text, and
secrets. Event payloads never include filing content.
