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

## Terminal runs are final: the job is dead-lettered

A run that has reached `succeeded`, `failed` or `cancelled` can never be
reopened. Migration 0004 enforces it in three places: the run row cannot leave a
terminal status, `fel_assert_extraction_run_open` rejects every INSERT and
UPDATE on that run's steps, events, proposals and evidence, and DELETE is
refused outright.

So a job for a terminal run cannot be made to succeed by retrying it. The
handler now checks the run's status before it marks the run running and before
any resume is dispatched, and raises `queue.PermanentFailure`; the consumer
parks the job as `failed` immediately (`queue.dead_letter`) instead of
requeueing it until `max_attempts` is exhausted.

What you will see: a `jobs` row with `status = 'failed'` and
`error.code = 'JOB_PERMANENT_FAILURE'`, whose message names the run id and the
status it is already in. Nothing is written to any extraction table by the
refused attempt, and no model budget is spent.

What to do: nothing, if the run genuinely finished — the job was a duplicate or
a late redelivery. If the work still needs doing, create a NEW run row (runs are
immutable and permanent by design) and enqueue against that. Do not attempt to
hand-edit the run's status; the guard will refuse, and it is refusing correctly.

## Stage output and checkpoint verification

Each succeeded step stores its stage result in `extraction_run_steps.output`
(`jsonb`) alongside `output_hash`, the sha256 of that value's canonical JSON.
Both are written in a single INSERT, inside the same transaction as the step's
`step_completed` event, and migration 0006 carries
`CHECK ((output IS NULL) = (output_hash IS NULL))` so a hash without its value
is not a representable state.

On resume the worker recomputes the hash from what it read back and compares.
A mismatch — or an `output_hash` with no `output`, which is how rows written
before migration 0006 look — is NOT trusted: the stage is re-executed. That is
always safe, since a stage is idempotent and keyed on its `input_hash`.

The rejection is recorded as a `step_failed` event whose payload carries
`error.code = "checkpoint_rejected"`, `action = "stage_re_executed"` and a
`reason` of either:

- `checkpoint_hash_mismatch` — the stored output does not hash to its
  `output_hash`. Investigate: a durable row changed under a hash that still
  describes the original. Restores from an inconsistent backup and hand-edits
  are the realistic causes.
- `checkpoint_output_missing` — a legacy row (written before 0006) on a run that
  has since gone terminal. Expected, unrepairable by design, and harmless: the
  stage simply re-runs. There is no backfill and there cannot be one.

The event type is `step_failed` rather than a new one because the event
vocabulary is a frozen contract (0004's `event_type` CHECK and
`extraction-event.schema.json`); the reason travels in the payload.

To find them:

```sql
SELECT run_id, payload->>'step_name', payload->>'reason', created_at
  FROM extraction_run_events
 WHERE event_type = 'step_failed'
   AND payload->'error'->>'code' = 'checkpoint_rejected'
 ORDER BY created_at DESC;
```

A steady trickle of `checkpoint_output_missing` on old runs is normal. Any
`checkpoint_hash_mismatch` is not, and should be treated as a data-integrity
incident rather than a retry.

## Where the code lives

- `extraction/workflow.py` — the FSM control loop and nothing else: stage
  fencing (`_boundary`, `_commit_fence`), the content-addressed checkpoint
  lookup and commit (`_run_stage`, `_commit_stage`, `_is_recoverable`),
  stage-failure recording, dispatch, and terminal handling.
- `extraction/stages/` — the twelve stage bodies, one module per stage or
  family: `request.py`, `evidence.py`, `model.py` (all five model-backed
  stages), `normalize.py`, `validate.py`, `citations.py`, `conflicts.py`,
  `persist.py`.
- `extraction/stages/io.py` — what each stage contributes to its `input_hash`,
  and how a checkpointed output is restored into state on resume. Editing this
  file moves checkpoint keys; `workers/tests/extraction/test_checkpoint_hash_golden.py`
  pins them for a fixture run and fails if they move.
- `extraction/context.py` — the store protocols, `WorkflowDeps`, and the
  per-run execution context shared by the loop and the stages.

## Review semantics

Every proposal is persisted as `needs_review`. There is no auto-approve path.
Zero-proposal abstention succeeds the run; provider refusal / schema / budget
failures mark the run `failed`.

### Confidence is NULL until a calibrator exists

`extraction_proposals.record_confidence` is NULL for every proposal the current
pipeline writes, and that is deliberate. There is no calibrator yet (issue #62);
the column previously stored `0`, which is a legitimate value on its own 0-1
scale and reads — to a human and to any queue sorted by it — as "the extractor
is certain this is wrong". NULL is the only spelling of "not scored". Migration
0006 drops the `NOT NULL` that forced the lie; the range CHECK still binds every
value that is supplied.

Do not sort or filter a review queue on `record_confidence` yet. Use
`review_priority`.

### Review priority is derived, not constant

`review_priority` is `high` when the validator recorded any blocker for the
proposal, or when the proposal is a member of a conflict group; `normal`
otherwise. It is computed deterministically from the validation summary, so a
run rebuilt from its checkpoint sorts identically to the run that produced it.
It was previously `high` for everything, which made the column carry no
information: a queue in which everything is urgent has no ordering.

`review_priority` is a triage signal, not a quality score, and it is not a
substitute for the confidence a calibrator will eventually supply.

## Telemetry

`fel_workers.extraction.telemetry` redacts prompts, messages, source text, and
secrets. Event payloads never include filing content.

Since ADR-0011 that last sentence is true without exception. `step_completed`
used to carry the whole stage output — pinned filing text included — under a
`stage_output` key, because frozen migration 0004 had no `steps.output` column
and the event payload was the only durable carrier a resume could read back.
Migration 0006 gives it the column, so the carve-out in
`extraction/events.py::redact_event_payload` is deleted rather than narrowed and
the event sink now has exactly one mode. An operator or consumer granted the
event stream on the strength of its metadata-only label receives metadata.
