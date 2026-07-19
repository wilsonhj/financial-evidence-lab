# Implementation status

Last updated: 2026-07-19

## Repository

- Default and implementation base: `main`.
- Current main tip: `0290446` (PR #112 M3-CONTRACT merge; prior tip PR #115 harness gate @ `cfd8991`).
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

1. **Active:** M2-RETRIEVAL-BACKEND (#57) — `packages/retrieval/**`, `apps/api/**`; mock-first; branch `agent/m2-retrieval-backend`. Dispatched 2026-07-19 from main @ `e9b511e` (post-#110). First slice: M2-010 item builder. Parallel-safe with #101. Scaffold dir-list grant recorded on #57.

## Ready (post-#105/#106 reconciliation)

None. Both ready packages are now active.

Dispatch note: #101 is merged; #57 continues alone. Next contract owner (#60 M3-EXTRACTION-CORE chain) must serialize with any other contracts/migrations owner.

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
