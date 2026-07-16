# Implementation status

Last updated: 2026-07-16

## Repository

- Default and implementation base: `main`.
- Current main tip: `052836d423a600cb7b84caeebf83841a76f83e6f` (PR #102 merged; prior tip was PR #99 @ `70ee86f`).
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
- External benchmark and ontology research recovered from PRs #74/#75 onto the M2/M3 design branch without merging retired `integration/m0` history.
- Issues #57–#62 refreshed to current `main`, concrete dependencies, bounded paths, and implementation acceptance gates.
- Contract-change issues #100 (M2 v0.3.0) and #101 (M3 v0.4.0) created with serialized shared-path ownership.
- M2/M3 implementation design PR #102 merged to main @ `052836d` (Spec Kit packages, ADR-0006/0007, research reconciliation, contract gates documented).

## Design gate (closed)

PR #102 merged to `main` @ `052836d`. Design gate is closed. Spec Kit packages, ADR-0006/0007, and recovered research are on trunk.

Still research-draft (not a dispatch blocker): recovered benchmark needs SEC timestamp/provenance/negative-case/range gates in the M2 compiler; recovered ontology needs citation/provenance fixes or explicit v1 exclusion.

## Active

None. Next dispatch is ready-queue only (no package currently `active`).

## Ready (post-#102 dispatch)

1. **Ready:** READER-CROSS-STACK (#96) — `evals/**`; dispatch from current main.
2. **Ready:** M2-CONTRACT (#100) — mock-first v0.3.0 freeze; `db/migrations/**`, `packages/contracts/**`, `docs/handoff/CONTRACTS.md` only.

Dispatch **#96 and #100 in parallel** (no path overlap). **Never** run #100 concurrent with #101.

## Next (after ready merges)

1. **Blocked until both #96 and #100 merge:** M2-RETRIEVAL-BACKEND (#57).
2. Then M2-CLAIMS-VERIFICATION (#58) on #57; M2-OBSERVATORY-UI (#59) on #57 (+ #96 already satisfied if merged).
3. **Blocked until #100 merges:** M3-CONTRACT (#101) — same shared paths as #100; serialize after #100 merges (never concurrent).
4. Then M3-EXTRACTION-CORE (#60) on #58 + #101; M3-REVIEW (#61); M3-CONFIDENCE-GATE (#62).

## Credentials

CI and package implementation are mock-first. Request `FEL_OPENAI_API_KEY` only for the explicitly credentialed live retrieval/extraction smoke gates after deterministic fixtures and contracts pass. SEC source re-verification requires the configured compliant SEC identity and rate limiter; do not commit or log personal contact data.

## Resume rules

1. Treat GitHub merged commits, issues, and PRs as authoritative.
2. Reconcile this file with `workstreams.yaml` before dispatch.
3. Never run #100 and #101 concurrently; both own contracts/migrations.
4. Do not dispatch any package whose allowed paths overlap an active package.
5. Keep total active packages at four or fewer.
6. Require tests, telemetry where applicable, documentation, acceptance evidence, and an independent PR review before merge.
