# Implementation status

Last updated: 2026-07-20

## Repository

- Default and implementation base: `main`.
- Current main tip: `c546ec2` (PR #119 M2-RETRIEVAL-BACKEND merge; prior notable tips PR #118 query-guard fix @ `be2af18`, PR #116 @ `407f34f`).
- Canonical product spec: `specs/001-financial-evidence-lab/spec.md` v1.2.
- M2 implementation design: `specs/002-observable-hybrid-retrieval/` plus ADR-0006 (live on main).
- M3 implementation design: `specs/003-agentic-extraction/` plus ADR-0007 (live on main).

## Completed

- M0 platform/contracts/CI foundations.
- M1 ingestion, evidence UI, corpus QA, companyfacts follow-up, and worker deployment.
- Reader contract/global offsets plus production API and HTTP web runtime:
  - PR #92 / issue #89 — contract
  - PR #91 / issue #90 — global offsets
  - PR #98 / issue #94 — reader API
  - PR #99 / issue #95 — HTTP reader runtime
- READER-CROSS-STACK mock-first + CI stack path: PR #105 / package issue #96 (criteria 1–10).
- M2-CONTRACT OpenAPI v0.3.0 + migration `0003_retrieval_core.sql` + pgvector CI image: PR #106 / issue #100 (closed).
- M3-CONTRACT OpenAPI v0.4.0 + migration `0004_extraction_core.sql` + `StructuredLLMProvider` mocks: PR #112 / issue #101 (closed); review fixes included typed records, conflict identity pin, terminal-run proposal freeze, step success-demotion guard.
- M2-RETRIEVAL-BACKEND full package: PRs #114 + #119 / issue #57 (closed) — item builder, versioned index publish + exact-vs-HNSW oracle, cutoff-safe lanes, deterministic planner, RRF k=60 fusion, query/trace/SSE/rerun/feedback API with persisted byte-stable replay; acceptance report at `packages/retrieval/ACCEPTANCE.md`.
- Migration `0005` query-guard role fix (fel_guard_query FOR SHARE vs SELECT-only fel_app): PR #118, with as-fel_app harness regression.
- Retrieval integration suites isolated in a dedicated `<db>_retrieval` test database (cross-suite FK isolation defect found by first CI exposure): PR #119.
- CI migration-harness gate (`db/migrations/tests/*.test.sql` run in the database job): PR #115; database job now logs `OK: 2 migration harness(es) run` (0003 + 0004).
- External benchmark and ontology research recovered from PRs #74/#75 onto the M2/M3 design branch without merging retired `integration/m0` history.
- Issues #57–#62 refreshed to current `main`, concrete dependencies, bounded paths, and implementation acceptance gates.
- Contract-change issues #100 (M2 v0.3.0) and #101 (M3 v0.4.0) created with serialized shared-path ownership.
- M2/M3 implementation design PR #102 merged to main @ `052836d` (Spec Kit packages, ADR-0006/0007, research reconciliation, contract gates documented).

### Tracker note — #96 residual owned by #108

Issue #96 remains **open** as a tracker only. Package `READER-CROSS-STACK` is `merged` via #105 for its `evals/**` mock/stack scope. Remaining acceptance **criterion #11** (production worker → Postgres → FastAPI → real `HttpEvidenceSource` → production Next.js reader + browser/hosted artifacts) is owned by **READER-PROD-SMOKE (#108)**. Do not re-dispatch #96; do not treat #96-open as blocking #57.

## Design gate (closed)

PR #102 merged to `main` @ `052836d`. Design gate is closed. Spec Kit packages, ADR-0006/0007, and recovered research are on trunk.

Still research-draft (not a dispatch blocker): recovered benchmark needs SEC timestamp/provenance/negative-case/range gates in the M2 compiler; recovered ontology needs citation/provenance fixes or explicit v1 exclusion.

## Active

None. No package currently `active`.

## Ready (post-#119 reconciliation)

1. **Ready:** M2-CLAIMS-VERIFICATION (#58) — `packages/retrieval/**`, `packages/retrieval-evals/**`, `apps/api/**`, `evals/**`; deps satisfied (M2-RETRIEVAL-BACKEND merged via #119). New-package scaffold registration for `packages/retrieval-evals` covered by ADR-0008.
2. **Ready:** M2-OBSERVATORY-UI (#59) — `apps/web/**`, `packages/ui/**`; deps satisfied (retrieval trace schema live via #119; reader gate merged via #105).

Dispatch **#58 and #59 in parallel** (disjoint paths). Serialization notes: blocked #108 also lists `apps/api/**` and `apps/web/**` — if #108 unblocks, do not run it concurrently with an in-flight #58/#59. #60 (M3-EXTRACTION-CORE) still waits on #58 and must serialize with any contracts/migrations owner.

## Blocked (registered, not dispatchable)

1. **Blocked:** READER-PROD-SMOKE (#108) — branch `test/reader-prod-smoke`; child F of #87.
   - Blocker A: hosted deployment credentials not provisioned (request by name only; never claim ready).
   - Blocker B: known product residual — API `INTEGRITY_ERROR` classified as web `unavailable` (no integrity-alert UI kind); #108 must stop-and-escalate, not silently patch.
   - Flip to `ready` only after integration-lead provisions hosted secrets **and** clears the integrity residual (fix landed or explicit lead waiver).
   - Shared `.github/**` gated workflow requires separate integration-lead authorization before any smoke PR edits CI.

## Next (after ready merges)

1. After #57: M2-CLAIMS-VERIFICATION (#58); M2-OBSERVATORY-UI (#59) (reader mock/stack gate already satisfied by merged `READER-CROSS-STACK`).
2. After #101: M3-EXTRACTION-CORE (#60) on #58 + #101; then #61/#62.
3. READER-PROD-SMOKE (#108) remains blocked until credentials + integrity residual cleared (does **not** gate #57/#101).

## Credentials

CI and package implementation remain mock-first for #57/#101. Hosted reader production smoke (#108) requires separately authorized deployment credentials — **not provisioned**; request by name only. Do not treat #108 as credential-ready. Request `FEL_OPENAI_API_KEY` only for the explicitly credentialed live retrieval/extraction smoke gates after deterministic fixtures and contracts pass. SEC source re-verification requires the configured compliant SEC identity and rate limiter; do not commit or log personal contact data.

## Resume rules

1. Treat GitHub merged commits, issues, and PRs as authoritative.
2. Reconcile this file with `workstreams.yaml` before dispatch.
3. Never run two packages that own `packages/contracts/**` / `db/migrations/**` concurrently (#101 vs any future contract owner).
4. Do not dispatch any package whose allowed paths overlap an active package.
5. Keep total active packages at four or fewer.
6. `#96` open ≠ package unfinished; residual criterion #11 is #108-owned.
7. Require tests, telemetry where applicable, documentation, acceptance evidence, and an independent PR review before merge.
