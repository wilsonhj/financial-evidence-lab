# M3 Agentic Extraction — Implementation Tasks

Tasks are test-first. Integration lead alone marks completion after merge and evidence.

## Phase 0 — Shared contract gate (serial)

- [ ] **M3-000** Reconcile PR #75 artifacts to `main`; correct or explicitly track the post-merge provenance/coverage review findings.
- [ ] **M3-001** Merge issue #101 against accepted ADR-0007: migration `0004_extraction_core.sql` (after M2 `0003_retrieval_core.sql`), RLS/grants/immutability tests, extraction JSON schemas/fixtures/OpenAPI v0.4.0, generated client, and additive structured-provider protocol/mock.
- [ ] **M3-002** Verify contract semver, generated drift, migration up/down/restore smoke, RLS negatives, and `make ci` before implementation branches rebase.

## Package #60 — M3-EXTRACTION-CORE

- [ ] **M3-100 / T0301** Convert reconciled research into validated `saas-metrics.v1.json`; encode aliases, qualifiers, derivations, and comparability keys; add golden tests for all 14 initial metrics across nine families.
- [ ] **M3-101 / T0302** Implement finite workflow/run context, budgets, cancellation, checkpoint/resume, stage hashes, and typed failures.
- [ ] **M3-102 / T0302** Add `extraction_run` dispatch to the existing consumer with lease fencing/heartbeat and crash-after-every-stage tests.
- [ ] **M3-103 / T0303** Implement typed classifier and fact/table candidate roles with fixed read-only tool allowlists.
- [ ] **M3-104 / T0303** Implement KPI, guidance, and revenue-driver roles; strict structured output, explicit refusals, one repair maximum, prompt-injection fixtures.
- [ ] **M3-105 / T0304** Implement Decimal-based period/currency/unit/sign/scale/dimension normalization and property tests.
- [ ] **M3-106 / T0305** Implement schema/accounting/range/duplicate/definition/conflict/citation validators and deterministic conflict groups.
- [ ] **M3-107** Add telemetry/redaction, run fixtures, operator docs, and full mock workflow acceptance evidence.

## Package #61 — M3-REVIEW (after #60)

- [ ] **M3-200 / T0308** Implement run create/get/list/cancel/rerun APIs and resumable SSE events with auth, idempotency, cutoff validation, and error contracts.
- [ ] **M3-201 / T0308** Implement proposal queue/list/detail and atomic accept/edit/reject/merge/bulk APIs with a required expected version per selected proposal; add If-Match correction/history APIs for approved records.
- [ ] **M3-202 / T0309** Implement immutable approved versions, correction/history/head APIs, evidence manifests, and M4-ready approved-record read contract.
- [ ] **M3-203 / T0308** Build accessible execution graph/table, evidence review, blockers/conflicts, batch actions, and history UI.
- [ ] **M3-204** Add API/web RLS, temporal, race, merge, SSE replay, accessibility, and browser tests; document review operations.

## Package #62 — M3-CONFIDENCE-GATE (after #61)

- [ ] **M3-300 / T0306** Build versioned adjudicated extraction dataset and deterministic `isotonic-v1` calibrator artifact with insufficient-data fail-closed tests.
- [ ] **M3-301 / T0306** Apply calibrated record/field confidence and owner-only audited 0.85/0.80 policies; add threshold-boundary tests.
- [ ] **M3-302 / T0307** Prove all proposals require human action and monetary/guidance/assumption outputs cannot auto-approve through any API, worker, bulk, replay, or policy path.
- [ ] **M3-303 / T0310** Evaluate exact guidance and KPI/driver matching plus 99% numeric accuracy; reference M2 contradiction report rather than adding a detector.
- [ ] **M3-304** Run live OpenAI structured-output smoke with approved secret, provider-failure suite, `make ci`, independent review, and publish immutable eval report.

## Parallelism

- M3-000 research reconciliation and M3-001 contract design can be drafted concurrently but merge in one reviewed shared-path PR.
- Inside #60, ontology/tests and workflow runtime can proceed in disjoint modules after contracts freeze; consumer wiring merges last.
- #61 API and web can run in parallel using the merged generated client and mock fixtures, with disjoint `apps/api/**` and `apps/web/**` ownership.
- #62 dataset/calibrator work may start fixture-only while #61 runs, but integration and gate publication wait for #61 merge.
- Do not dispatch M4 packages owning extraction/API/web integration until the relevant M3 dependency is merged.
