# M2-RETRIEVAL-BACKEND (#57) — acceptance report

Package delivered as six reviewed slices on `agent/m2-retrieval-backend`
(M2-010 merged via PR #114; M2-011…015 + final-review fixes on this branch).
Every slice was verified before push: full gates (pytest incl. Docker-pgvector
integration, black, ruff, mypy strict, bandit) plus red-green perturbation
evidence for load-bearing assertions. A three-lane independent final review
(cross-slice integration, acceptance mapping, API security/SSE) ran at head
and its findings were fixed in-branch before this report.

## Acceptance criteria — evidence map

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Identical builds → identical IDs/counts; changed chunker/model/config → new index | ✅ | `test_index_version.py` (id determinism, per-pin flips), `test_item_builder.py::test_idempotent_rebuild`, `test_index_build_integration.py` (row reuse; config change mints new id) |
| 2 | Eligible items re-verify offsets/hash/span; unanchored rows rejected | ✅ | `test_item_builder.py` (`UNANCHORED_TABLE_ROW`, `UNANCHORED_FACT`, `HASH_MISMATCH` cascade); hash re-verification over canonical bytes subsumes offset drift |
| 3 | Candidates satisfy entity/document/period/corpus/index/cutoff filters; cross-version fails closed | ✅ | `test_lanes_integration.py` (pin+cutoff, cutoff widening, cross-index leakage negatives — driven RED by predicate removal during review), `test_lanes_unit.py` (SQL predicates); period validated at plan time; DB `fel_guard_candidate` re-enforces index/cutoff on insert |
| 4 | Exact-vs-HNSW recall, per-lane, RRF, RLS, SSE reconnect/replay, idempotency, provider failure, API integration, p95 | ✅ | recall ≥0.9 gate (observed 1.0); four lane suites; hand-computed RRF k=60; cross-org RLS→404; SSE Last-Event-ID resume (red-green: boundary off-by-one fails); idempotent create (single run row); provider/lane failure → persisted `failed` run + `run_failed` event; 9-test API integration suite; p95 smoke gate |
| 5 | Stored replay byte-stable; rerun parent-linked new run | ✅ | two trace reads byte-identical (fixed-precision string scores end-to-end); rerun test: new run, `parent_run_id` set, parent frozen |
| 6 | `make ci`, telemetry, docs, acceptance report | ✅ | branch CI green (fresh-DB run incl. all three migration harnesses); telemetry via request middleware (`duration_ms` structured logs) + the persisted domain trace (events/decisions/budget_usage/timings) itself; docs: `README.md` (this package); report: this file |

## Required-outcome line

Immutable corpus-pinned index with atomic publish ✅ · hash-anchored
passage/table-row/fact items ✅ · 512d halfvec cosine HNSW + GIN FTS ✅ ·
cutoff-safe dense/lexical/fact/table lanes ✅ · typed deterministic planner ✅ ·
RRF k=60 ✅ · no-op reranker hook (traceable top-100) ✅ · provenance dedupe
(recorded decisions) ✅ · persisted trace ✅ · query/read/SSE/rerun/feedback
API ✅.

## Defects found and fixed during the package

- `0003` `fel_guard_query` used `SELECT … FOR SHARE` on a SELECT-only table —
  every app-role query insert failed. Fixed by additive migration `0005`
  (own PR #118) + an as-`fel_app` harness regression closing the superuser
  blind spot.
- Query embedder was hardcoded to the mock, bypassing the pinned
  provider/model; pipeline failures left no persisted run. Both fixed in the
  final-review pass (pin-resolved embedder refusing unknown providers;
  durable `failed` run + `run_failed` event path, tested).
- Feedback guard rejections surfaced as 500; now typed 422.

## Known deferrals (tracked, non-blocking)

- **SSE periodic heartbeat loop** — runs are synchronous-terminal in M2, so
  streams replay committed events and close; the 15–30s heartbeat loop
  becomes load-bearing only with async runs (M3 work).
- **Multi-variant retrieval** — planner emits ≤4 variants; retrieval executes
  variant 0 (single-variant fusion documented in the trace).
- **Live embedding provider** — mock-only by design; the pin-resolver refuses
  non-mock providers until a credentialed provider is separately authorized.
- Exact-vs-HNSW p95/latency characterization beyond the smoke gate, and
  reranker beyond no-op, remain M2-follow-up/M3 surface.
