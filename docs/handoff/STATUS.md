# Implementation status

Last updated: 2026-07-21

## Repository

- Default and implementation base: `main`.
- Current main tip: `ad1717b` (PR #128 js-yaml override; prior notable tips PR #127 DB-GUARD-HARDENING @ `e55eea8`, PR #119 M2-RETRIEVAL-BACKEND merge @ `c546ec2`).
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
- M2-CLAIMS-VERIFICATION full package: PR #122 / issue #58 (merged) — atomic claim decomposition, citation entailment/verification, abstention, 50–100-question smoke gate, retrieval/performance suite; live 65-question exit gate deferred to follow-up #132.
- M2-OBSERVATORY-UI full package: PR #123 / issue #59 (merged) — Search Observatory trace timeline, lane toggles, evidence feedback, and replay; browser E2E and live SSE deferred to follow-ups #131/#134/#135.
- DB-GUARD-HARDENING: PR #127 / issue #125 (closed) — retroactive 0005 authorization record, as-fel_app guard-harness pass, superseded-pin regression, helper consolidation.
- Migration `0005` query-guard role fix (fel_guard_query FOR SHARE vs SELECT-only fel_app): PR #118, with as-fel_app harness regression.
- Retrieval integration suites isolated in a dedicated `<db>_retrieval` test database (cross-suite FK isolation defect found by first CI exposure): PR #119.
- CI migration-harness gate (`db/migrations/tests/*.test.sql` run in the database job): PR #115; database job now logs `OK: 3 migration harness(es) run` (0003 + 0004 + 0005 from #118).
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

## Ready (post-#122/#123 reconciliation)

1. **Ready:** M3-EXTRACTION-CORE (#60) — `packages/ontology/**`, `packages/providers/**`, `workers/src/fel_workers/extraction/**`, `workers/src/fel_workers/consumer.py`, `workers/src/fel_workers/__main__.py`, `workers/tests/**`; deps satisfied (M2-CLAIMS-VERIFICATION merged via #122; M3-CONTRACT merged via #112).

Serialization notes: #60 must serialize with any contracts/migrations owner. Blocked #108 overlaps `apps/api/**` + `apps/web/**` + `evals/**` — if #108 unblocks, do not run it concurrently with any package holding those paths.

## Blocked (registered, not dispatchable)

1. **Blocked:** READER-PROD-SMOKE (#108) — branch `test/reader-prod-smoke`; child F of #87.
   - Blocker A: hosted deployment credentials not provisioned (request by name only; never claim ready).
   - Blocker B: known product residual — API `INTEGRITY_ERROR` classified as web `unavailable` (no integrity-alert UI kind); #108 must stop-and-escalate, not silently patch.
   - Flip to `ready` only after integration-lead provisions hosted secrets **and** clears the integrity residual (fix landed or explicit lead waiver).
   - Shared `.github/**` gated workflow requires separate integration-lead authorization before any smoke PR edits CI.

## Next (after ready merges)

1. M3-EXTRACTION-CORE (#60) on #58 + #101 (both merged) — now ready; then #61/#62.
2. READER-PROD-SMOKE (#108) remains blocked until credentials + integrity residual cleared (does **not** gate #60).

### M2 follow-ups (issues opened 2026-07-21)

Tracked after the #122/#123 merges; none blocks #60.

- **#132** — M2-CLAIMS live 65-question exit gate (closes M2-024).
- **#133** — M2-CLAIMS: break numeric identity tautology in unit tests (no external deps).
- **#134** — M2-OBSERVATORY: run Playwright E2E in CI (closes criterion 6 browser-E2E).
- **#135** — M2-OBSERVATORY / M3: mount live same-origin SSE proxy + UI consumer (M3-deferred).
- **#136** — M2-OBSERVATORY: full WCAG 2.2 AA + keyboard-operation audit.
- **#137** — M2-CLAIMS fast-follow hardening (mock→live cutover hygiene).
- **#138** — M2-OBSERVATORY: dedicated web-layer client telemetry.
- Draft PR **#131** — Observatory Playwright E2E in fixture mode (stacked on #123; #59 criterion 6).

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
