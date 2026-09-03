"""Observable hybrid retrieval API (M2-015 / T0206, ADR-0006).

This package wires the frozen retrieval contract (openapi v0.3.0) to the pinned
pipeline in ``fel_retrieval``: it captures an immutable query plan, executes the
lanes -> fusion pipeline once, and persists the whole run as an ordered,
replayable trace (events, per-lane candidate contributions, run timings and
budget usage) inside a single tenant transaction.

Persistence honours ``db/migrations/0003_retrieval_core.sql`` exactly:

* All tenant writes go through ``tenant_connection`` (``fel_app`` + org claims)
  so row-level security is active — a caller only ever sees its own org's
  queries/runs/events/candidates, and a cross-org id is a natural 404.
* Events carry a monotonic ``seq`` per run and are **committed before** any SSE
  emission (emission happens in a separate GET request, after the create
  transaction has committed), so a stream never shows an uncommitted event.
* The run status walks the ADR-0006 machine
  (``queued -> planning -> retrieving -> fusing -> generating -> verifying ->
  succeeded``); the terminal transition is emitted as ``run_completed`` first so
  the ``fel_guard_retrieval_run`` terminal-event check passes, and only the
  column-scoped fields the migration grants (status, budget_usage, cost_usd,
  timings_ms, finished_at, error) are ever updated.

Lane reads run over the public corpus tables (``documents``/``retrieval_*`` carry
no org_id and no RLS by design — see ``0002``/``0003``) on a dedicated read
connection with a tuple row factory, because the lane SQL in ``fel_retrieval``
consumes positional rows. Org isolation is unaffected: every org-scoped write
stays on the RLS-bound tenant connection.

Generation (M2-020) decomposes the selected context into atomic claims via the
pinned structured provider; verification (M2-021) re-derives every citation edge
from the evidence and persists claims with their edges before the run goes
terminal. When no claim is supported (e.g. the provider refused), the run
abstains — ``verifying -> abstained`` with a terminal ``run_abstained`` event —
otherwise it succeeds (a contradicted claim is preserved and displayed, M2-022).

Layout (#196). The endpoints, the pipeline and the persistence contract used to
share one 1300-line module; they are now one concern per file:

* ``routes`` — the six endpoints and their request models.
* ``pipeline`` — lanes -> fusion -> generation -> verification for one run.
* ``persistence`` — the 0003-scoped writes and the reads that feed generation.
* ``providers`` — pinned identities and fail-closed provider resolution.
* ``idempotency`` — ``Idempotency-Key`` replay and storage.
* ``sse`` — the text/event-stream replay of a persisted trace.
* ``serializers`` — row -> contract-shape formatting for the trace.

This module re-exports the names the rest of the app and the tests import, so
``app.retrieval`` remains the single public entry point it has always been.
"""

from __future__ import annotations

from app.retrieval.persistence import _numeric_from_fact_row
from app.retrieval.pipeline import _LANE_FUNCS
from app.retrieval.providers import (
    MOCK_GENERATION_PIN,
    PLANNER_VERSION,
    UnsupportedEmbeddingProvider,
    UnsupportedGenerationProvider,
    _resolve_embedding_provider,
    _resolve_generation_provider,
    generation_pin,
)
from app.retrieval.routes import router
from app.retrieval.serializers import EVENT_SCHEMA_VERSION

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "MOCK_GENERATION_PIN",
    "PLANNER_VERSION",
    "UnsupportedEmbeddingProvider",
    "UnsupportedGenerationProvider",
    "_LANE_FUNCS",
    "_numeric_from_fact_row",
    "_resolve_embedding_provider",
    "_resolve_generation_provider",
    "generation_pin",
    "router",
]
