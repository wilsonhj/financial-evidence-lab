# packages/retrieval — versioned hybrid retrieval backend (M2, #57)

Deterministic, mock-first retrieval core behind the v0.3.0 retrieval API:
item building, versioned index build/publish, cutoff-safe lanes, typed
planning, RRF fusion, and the persisted-trace query pipeline consumed by
`apps/api/app/retrieval.py`.

## Module map

| Module | Slice | Responsibility |
|---|---|---|
| `item_builder.py`, `chunker.py`, `ids.py`, `hashing.py` | M2-010 | Canonical passage/table-row/fact items: UUIDv5 ids over `(index_version_id, kind, source_anchor, content_sha256)`, sha256 re-verification over canonical bytes, fail-closed rejection diagnostics (`UNANCHORED_TABLE_ROW`, `UNANCHORED_FACT`, `HASH_MISMATCH`, `OFFSET_MISMATCH`) |
| `index_version.py`, `index_build.py`, `embeddings.py`, `oracle.py` | M2-011 | Deterministic index-version ids (UUIDv5 of the corpus/config/provider/model/dims/distance tuple per `0003`), draft→building→ready lifecycle with atomic single-active publish, 512d mock embeddings, exact-cosine oracle for HNSW recall gating |
| `lanes.py` | M2-012 | Dense (halfvec cosine HNSW), lexical (FTS/GIN), fact, and table lanes; every lane pins `index_version_id` and enforces `documents.published_at <= as_of` plus entity/document/form/period filters in parameterized SQL |
| `planner.py` | M2-013 | Pure deterministic `plan_query` → `query-plan/v1`: rule-based intent, curated synonym expansion (≤4 variants), fail-closed filter validation, budget derivation |
| `fusion.py` | M2-014 | Provenance dedupe (recorded decisions), RRF k=60 with Decimal-quantized order-independent scoring, no-op reranker hook over the fused top-100, typed fusion result mapped to the trace contract |

## Design invariants

- **Determinism end-to-end.** Identical inputs yield byte-identical outputs at
  every layer: sorted item/rejection ordering, canonical JSON (`sort_keys`,
  fixed separators), Decimal-quantized RRF summation, stable tie-breaks
  (score, then id). Scores travel as fixed-precision strings end-to-end so no
  float round-trip can perturb a stored trace.
- **Fail closed.** Missing spans, hash mismatches, unknown providers, invalid
  filters, and lane failures raise typed errors; nothing silently degrades to
  fixtures or partial results.
- **Frozen-contract fidelity.** Shapes match `@fel/contracts` v0.3.0
  (`query-plan/v1`, `retrieval-event/v1`, `retrieval-trace/v1`) and the `0003`
  DDL (kind-anchor exclusivity, `sha256:` formats, composite-FK pinning).
  The DB guards re-enforce the same rules (cutoff, index agreement, seq
  ordering, terminal-event coupling), so application and schema cannot drift
  apart silently.
- **Stdlib-only runtime.** `fel_retrieval` imports no third-party packages;
  DB access is injected through a `DBConnection` protocol (psycopg lives in
  tests and `apps/api` only). Mock embeddings are pure functions of
  (content, model, dimensions).

## Testing

- Unit suites run DB-less (recording fake connections; pure logic).
- Integration suites require `TEST_DATABASE_URL` pointing at a migrated
  pgvector database (CI provisions `pgvector/pgvector:0.8.5-pg17`; local:
  any container with migrations `0001`–`0005` applied) and cover build/publish
  lifecycle, single-active enforcement, exact-vs-HNSW recall, lane
  pin/cutoff/leakage negatives, and full pipeline determinism.
- The API surface (create/read/SSE/rerun/feedback, RLS negatives, byte-stable
  replay, idempotency, provider/lane failure persistence, p95 smoke) is
  tested in `apps/api/tests/test_retrieval_api.py`.

See `ACCEPTANCE.md` for the #57 acceptance-criteria evidence map.
