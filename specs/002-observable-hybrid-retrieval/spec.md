# Observable Hybrid Retrieval — M2 Specification

**Status:** clarified; implementation-ready  
**Parent:** `specs/001-financial-evidence-lab/spec.md` v1.2  
**Scope:** T0201–T0210, T0214a, T0215. Embedding Atlas remains deferred.
**Contract gate:** issue #100 (v0.3.0 migration/OpenAPI freeze).

## Outcome

An authenticated analyst can ask a point-in-time question, inspect four independently ranked retrieval lanes, receive atomic verified claims, inspect every accepted/rejected candidate, replay the immutable trace, and provide evidence feedback.

## User stories

### P1 — Retrieve auditable evidence

Given a workspace, question, and cutoff, the system retrieves dense passages, lexical passages, structured facts, and table rows, filters all candidates by entity/document/period/publication time and optional corpus version, fuses them with RRF, and returns stable evidence identifiers.

Acceptance:

- Every candidate belongs to one selected `document_version_id` and satisfies `published_at <= effective_as_of`.
- Passage/table/fact evidence resolves to a hash-verifiable `source_span_id`.
- Identical index inputs produce identical item IDs and no duplicate rows.
- Dense and lexical p95 latency is below 1.5 seconds at the reference profile; first persisted SSE event is below 1 second.

### P1 — Inspect and replay retrieval

The user sees the typed plan, variants, lane results, filters, ranks/scores, deduplication, fusion, optional reranking, context acceptance/rejection, budgets, latency, and final citation edges.

Acceptance:

- The stored trace is append-only and can be streamed again byte-for-byte with `Last-Event-ID`.
- Replay reads the stored run; rerun creates a new run pinned to the original immutable inputs and records its parent.
- A run never exposes another organization’s question, trace, feedback, claim, or citation.

### P1 — Receive verified claims

The answer is decomposed into atomic claims. Citation edges use `entailed|partial|contradictory|irrelevant`; claims use `supported|partially_supported|contradicted|derived|unsupported`.

Acceptance:

- Only `supported` and `derived` claims render as unqualified conclusions.
- Every number is checked deterministically for value, unit, period, sign, and scale using decimal arithmetic.
- Missing evidence yields abstention; contradictory evidence is preserved and displayed.

### P2 — Control and evaluate retrieval

The user may toggle lanes, adjust bounded top-k/time filters, compare runs, and mark evidence relevant, irrelevant, duplicate, or temporally invalid.

## Functional requirements

- **M2-FR-001:** Build immutable `passage`, `table_row`, and `fact` retrieval items from published corpus versions. Chunk at section/paragraph/list/table-row boundaries, retaining heading path and canonical global offsets.
- **M2-FR-002:** Index-version ID is UUIDv5 over the pinned corpus/config/provider/model/dimension/distance tuple and is uniquely reused; item ID is UUIDv5 over `index_version_id|kind|source_anchor|content_sha256`. Identical rebuilds are idempotent; changed chunker/model/config creates a new artifact.
- **M2-FR-003:** Store 512-dimensional OpenAI `text-embedding-3-small` output in `halfvec(512)` and use cosine HNSW with `hnsw.iterative_scan=relaxed_order`. Exact search remains the evaluation oracle.
- **M2-FR-004:** Use generated English `tsvector`, GIN, `websearch_to_tsquery`, and `ts_rank_cd` for lexical search.
- **M2-FR-005:** Structured-fact lookup queries canonical `financial_facts`; table lookup queries indexed table-row items. Unanchored rows are rejected, never cited.
- **M2-FR-006:** The deterministic planner emits one typed plan and at most four total variants (original plus versioned finance-synonym expansions). Workspace entity and cutoff are authoritative unless an allowed request narrows them.
- **M2-FR-007:** Execute enabled lanes concurrently; default lane top-k=100, RRF `k=60`, fused top-k=100, context cap=16. Persist exact config.
- **M2-FR-008:** Ship a no-op `Reranker` interface. Enable a cross-encoder only if the checksum-frozen M2 smoke benchmark baseline Recall@10 is below 90%, reranking the top 100.
- **M2-FR-009:** Deduplicate on canonical evidence key (`source_span_id`, canonical fact ID, or table-row ID); retain all contributing lane ranks.
- **M2-FR-010:** Persist query, plan, run, ordered events, candidates, decisions, claims, citations, feedback, model/config versions, budgets, cost, and timings.
- **M2-FR-011:** Query/trace/claim/feedback records are tenant-scoped with RLS. Corpus/index artifacts are shared, public, immutable, SELECT-only for `fel_app` per ADR-0004.
- **M2-FR-012:** SSE events are persisted before emission, monotonically sequenced, heartbeated every 15–30 seconds, resumable by `Last-Event-ID`, and terminal within the 15-minute Railway cap.
- **M2-FR-013:** All API timestamps are RFC3339 with offsets; cutoff is inclusive. Hidden-by-cutoff evidence never appears in candidates, traces, counts, or errors.
- **M2-FR-014:** Compile PR #74’s 65-question seed into a checksum-pinned smoke manifest. Golden quotes must map uniquely to in-corpus evidence; every cited document's actual SEC acceptance/publication timestamp must be less than or equal to the record cutoff; provisional same-day midnight cutoffs, unresolved anchors, and ambiguous rows fail compilation. Negative cases declare the exact cutoff-visible corpus manifest searched.
- **M2-FR-015:** Stored replay re-emits persisted events; an unchanged rerun creates a child run pinned to the same immutable query. Changing lanes, top-k, forms, periods, or cutoff creates a new child query through query creation with `parent_query_id`; it is never represented as replay or an unchanged rerun.

## Non-goals

- Embedding Atlas, graph retrieval, time-series analogues, external web retrieval, autonomous query agents, new queue infrastructure, or a dedicated reranker unless the gate triggers.

## Exit gates

- Temporal-validity rate 100%; numeric tuple accuracy >=99%; citation entailment precision >=95%; citation completeness >=92%; Recall@10 >=90%.
- `make ci`, migration/RLS negative tests, exact-vs-HNSW recall tests, benchmark compiler/evaluator, SSE reconnect/replay, API/web browser flow, and scaled performance suite pass.
- Saved trace replay is byte-stable; rerun is separately identified and provenance-linked.
