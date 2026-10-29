"""Operator notes for extraction workers.

Queue: ``extraction``. The name is enforced, not advisory — the model binding is
scoped to this queue, so an ``ingestion`` worker binds no model and fails closed
on any ``extraction_run`` that reaches it, and ``FEL_ALLOW_MOCK_LLM`` on a
non-extraction worker exits 2 at startup.

Job kind: ``extraction_run``, enqueued tenant-bound
(``queue.enqueue(..., org_id=<tenant>)``); a NULL job org is refused on the
durable path. Payload carries the run pin fields plus optional inline
``evidence``/``spans`` blocks (exact synonyms). Inline blocks supply text only:
with a connection, output always persists to Postgres. In-memory stores are
selected exclusively by ``FEL_EXTRACTION_MEMORY_STORES=1``, which DISCARDS all
output — smoke runs only. See ``docs/runbooks/extraction-worker.md``.

Budgets default to ADR-0007 caps. Telemetry is redacted — never logs prompts or
filing text. All proposals enter ``needs_review``; there is no auto-approve path.

A job whose ``extraction_runs`` row is already ``succeeded``/``failed``/
``cancelled`` is never retried: 0004 makes a terminal run unreopenable. On the
durable path the consumer reads the run status before dispatch, and again when
the store raises ``RunAlreadyTerminal`` or the handler fails after landing the
row, then parks the job to MATCH the run (``consumer._park_terminal_run_job``):
a ``succeeded`` run completes the job (its worker lost the lease after the run
write), a ``cancelled`` run cancels it, and only a ``failed`` run dead-letters
it. Re-enqueue against a NEW run row if the work is still wanted.

Hosted extraction is intentionally not deployed. The Railway worker service
(``infra/railway/worker.json``) starts ``python -m fel_workers run`` without
``--queue``, so it serves the default ``ingestion`` queue, while the API
enqueues every ``extraction_run`` on ``extraction``. The only model a worker
can bind is the deterministic mock behind ``FEL_ALLOW_MOCK_LLM`` until a live
model is bound (#62), and no ``extraction`` worker service exists yet (#362).
Until both land, hosted runs stay ``queued``.

Stage output is durable in ``extraction_run_steps.output`` with ``output_hash``
over it (migration 0006, ADR-0011), written in one INSERT. A resume re-hashes
what it read back and re-runs the stage on any mismatch, recording a
``step_failed`` event with ``error.code = checkpoint_rejected`` and a ``reason``
of ``checkpoint_hash_mismatch`` (investigate) or ``checkpoint_output_missing``
(a pre-0006 row; expected and harmless). Event payloads carry NO stage output
and no filing text — the ``stage_output`` carve-out is gone.

``record_confidence`` is NULL until a calibrator exists (#62); it is not 0. Sort
review queues on ``review_priority``, which is ``high`` for a proposal with any
validator blocker or conflict membership and ``normal`` otherwise.

See ``docs/runbooks/extraction-worker.md`` for the queries.
"""
