# Retrieval (`packages/retrieval`)

<details>
<summary>Relevant source files</summary>

- [fel_retrieval/\_\_init\_\_.py](fel_retrieval/__init__.py) — public exports
- [fel_retrieval/planner.py](fel_retrieval/planner.py) — `plan_query` → `query-plan/v1`
- [fel_retrieval/lanes.py](fel_retrieval/lanes.py) — dense, lexical, fact and table lanes
- [fel_retrieval/fusion.py](fel_retrieval/fusion.py) — provenance dedupe and RRF fusion
- [fel_retrieval/generation.py](fel_retrieval/generation.py) — structured claim generation and `CLAIM_JSON_SCHEMA`
- [fel_retrieval/verification.py](fel_retrieval/verification.py) — citation entailment, numeric checks and integrity
- [fel_retrieval/index_build.py](fel_retrieval/index_build.py) — versioned index build and publish
- [pyproject.toml](pyproject.toml) — package metadata
- [tests/](tests/) — unit and database-backed suites

</details>

Source references verified against commit `f4b1197`.

Versioned hybrid retrieval backend (M2, #57). Deterministic, mock-first
retrieval core behind the v0.3.0 retrieval API: item building, versioned index
build/publish, cutoff-safe lanes, typed planning, RRF fusion, structured claim
generation and citation verification, consumed by `apps/api/app/retrieval.py`
and `apps/api/app/retrieval_pipeline.py`.

## Module map

| Module | Slice | Responsibility |
|---|---|---|
| `item_builder.py`, `chunker.py`, `ids.py`, `hashing.py` | M2-010 | Canonical passage/table-row/fact items: UUIDv5 ids over `(index_version_id, kind, source_anchor, content_sha256)`, sha256 re-verification over canonical bytes, fail-closed rejection diagnostics (`UNANCHORED_TABLE_ROW`, `UNANCHORED_FACT`, `HASH_MISMATCH`, `OFFSET_MISMATCH`) |
| `index_version.py`, `index_build.py`, `embeddings.py`, `oracle.py` | M2-011 | Deterministic index-version ids (UUIDv5 of the corpus/config/provider/model/dims/distance tuple per `0003`), draft→building→ready lifecycle with atomic single-active publish, 512d mock embeddings, exact-cosine oracle for HNSW recall gating |
| `lanes.py` | M2-012 | Dense (halfvec cosine HNSW), lexical (FTS/GIN), fact, and table lanes; every lane pins `index_version_id` and enforces `documents.published_at <= as_of` plus entity/document/form/period filters in parameterized SQL |
| `planner.py` | M2-013 | Pure deterministic `plan_query` → `query-plan/v1`: rule-based intent, curated synonym expansion (≤4 variants), fail-closed filter validation, budget derivation |
| `fusion.py` | M2-014 | Provenance dedupe (recorded decisions), RRF k=60 with Decimal-quantized order-independent scoring, no-op reranker hook over the fused top-100, typed fusion result mapped to the trace contract |
| `generation.py` | M2-020 | `StructuredClaimGenerator`: builds a schema-constrained request from the question and selected context items, sends it through the `fel_providers` `StructuredLLMProvider` protocol, and strictly validates the reply against `claims-output/v1` (mirrored as `CLAIM_JSON_SCHEMA`); fabricated item ids or quotes raise `GenerationContractError` |
| `verification.py` | M2-021 | `MockCitationVerifier` entailment, `validate_numeric` (value, unit, period, sign, scale as exact `Decimal` checks), `assert_citation_integrity`, and closed-set claim classification and abstention |
| `config.py` | M2-011 | `CHUNKER_VERSION` and `config_hash`, the canonical-JSON `sha256:` identity inputs for index-version pinning |
| `models.py` | M2-010 | Frozen `RetrievalItemDraft` and `Rejection` dataclasses used by the item builder |

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
  apart silently. `generation.py` keeps its own copy of `claims-output/v1`
  (`packages/contracts/schemas/claims-output.schema.json`) as
  `CLAIM_JSON_SCHEMA` so the package imports without the contracts workspace;
  the two must change together.
- **Stdlib-only runtime.** `fel_retrieval` imports no third-party packages;
  its only first-party import is `fel_providers.interfaces` (in
  `generation.py`). DB access is injected through a `DBConnection` protocol (psycopg lives in
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

See [ACCEPTANCE.md](ACCEPTANCE.md) for the #57 acceptance-criteria evidence map.
