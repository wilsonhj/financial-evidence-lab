# Implementation status

Last updated: 2026-07-16

## Repository

- Default and implementation base: `main`.
- Current reconciled main before this design branch: `70ee86fd4ff1a4bc9abe54bc0e0f56144566bc89` (PR #99).
- Canonical product spec: `specs/001-financial-evidence-lab/spec.md` v1.2.
- M2 implementation design: `specs/002-observable-hybrid-retrieval/` plus ADR-0006.
- M3 implementation design: `specs/003-agentic-extraction/` plus ADR-0007.

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

## Active design gate

The M2/M3 implementation-design PR must merge before #100/#101 or implementation packages dispatch. It contains:

- implementation-ready Spec Kit `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, `tasks.md`, and clarify/analyse reports;
- ADR-0006 and ADR-0007;
- recovered research and a reconciliation audit; and
- all high/medium cross-artifact findings resolved.

The recovered benchmark remains a candidate seed until actual SEC acceptance/publication timestamps, quote provenance, negative-case corpus coverage, and range normalization pass the M2 compiler. The recovered ontology remains research draft until citation/provenance gaps are corrected or explicitly excluded from ontology v1.

## Ready / blocked queue

1. **Ready:** READER-CROSS-STACK (#96), now that PRs #98/#99 are merged.
2. **Ready after design PR:** M2-CONTRACT (#100), mock-first, shared contract/migration paths only.
3. **Blocked:** M2-RETRIEVAL-BACKEND (#57) on #100 and #96.
4. **Blocked:** M2-CLAIMS-VERIFICATION (#58) on #57.
5. **Blocked:** M2-OBSERVATORY-UI (#59) for final integration on #57; mock UI may be prepared from #100 after #96.
6. **Blocked:** M3-CONTRACT (#101) on #100; it owns the same shared paths serially.
7. **Blocked:** M3-EXTRACTION-CORE (#60) on #58 and #101.
8. **Blocked:** M3-REVIEW (#61) on #60.
9. **Blocked:** M3-CONFIDENCE-GATE (#62) on #61.

## Credentials

CI and package implementation are mock-first. Request `FEL_OPENAI_API_KEY` only for the explicitly credentialed live retrieval/extraction smoke gates after deterministic fixtures and contracts pass. SEC source re-verification requires the configured compliant SEC identity and rate limiter; do not commit or log personal contact data.

## Resume rules

1. Treat GitHub merged commits, issues, and PRs as authoritative.
2. Reconcile this file with `workstreams.yaml` before dispatch.
3. Never run #100 and #101 concurrently; both own contracts/migrations.
4. Do not dispatch any package whose allowed paths overlap an active package.
5. Keep total active packages at four or fewer.
6. Require tests, telemetry where applicable, documentation, acceptance evidence, and an independent PR review before merge.
