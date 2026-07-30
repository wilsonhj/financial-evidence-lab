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
"""
