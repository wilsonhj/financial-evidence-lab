# Contract versioning rules

These rules are frozen by ADR-0001 and govern every artifact in this package:
`openapi/openapi.yaml`, every `schemas/*.schema.json`, the generated client in
`src/generated/`, and the fixtures.

## Version identity

- The API contract version is `info.version` in `openapi/openapi.yaml` and
  follows semver. It is independent of application release versions.
- Every JSON Schema carries a versioned `$id` of the form
  `https://contracts.fel.dev/schemas/<name>/v<major>` and a `x-fel-version`
  (full semver). The `$id` major only changes on breaking changes.
- Fixture files are validated against their schema in CI; a fixture is part
  of the contract and changes to it follow the same rules.

## What is a breaking change (major bump)

- Removing or renaming a path, method, field, or enum value.
- Tightening a type, format, range, or `required` set.
- Changing the meaning of an existing field (including unit/scale/temporal
  semantics).
- Changing error `code` values or the error envelope shape.

## What is additive (minor bump)

- New paths, optional fields, new enum values where the consumer contract
  says unknown values must be tolerated (explicitly marked
  `x-fel-open-enum: true`), new schemas.
- Widening a type to admit `null` while the property stays in `required`
  (OpenAPI 3.1 `type: ["string", "null"]`). The key is still always on the
  wire; only the value set grows, so every previously valid document stays
  valid. This is the mirror image of tightening and never bumps a schema
  `$id` major.

## Non-negotiable invariants (never change without a new spec version)

- Monetary values are decimal **strings**, never floats
  (`financial-fact.schema.json`).
- Claim status and citation entailment enums are **closed** sets
  (`x-fel-open-enum: false`); a claim renders as a factual conclusion only
  when `supported` or `derived`.
- Every evidence-bearing object carries the temporal fields from spec
  section 10.3 (`published_at`, `filed_at`, `period_start`, `period_end`,
  `ingested_at`, `valid_from`, `valid_to`) where applicable.
- Job envelopes: terminal states are exactly `succeeded`, `failed`,
  `cancelled`; every mutation of a job carries `idempotency_key` semantics.

## Change process

1. ADR under `docs/decisions/` + GitHub issue labeled `contract-change`.
2. Affected-package and migration analysis in the PR.
3. Update schemas + fixtures + regenerate the client **in the same PR**
   (`pnpm --filter @fel/contracts generate`); CI fails if
   `check:generated` detects drift.
4. Integration-lead approval before dependent packages rebase.

Compatibility is decided by the deterministic contract tests
(`contracts.test.ts`), never by field-name similarity.

## Changelog

The authoritative per-release record — what changed, which issue and ADR
authorized it, and which migrations shipped with it — lives in
`docs/handoff/CONTRACTS.md`. This list is the version index.

| Version | Date | Authority | Summary |
|---|---|---|---|
| 0.1.0 | 2026-07 | ADR-0001 | Initial freeze: conventions, workspaces, entities, documents, source spans, ingestion jobs, error envelope. |
| 0.2.0 | 2026-07-15 | PR #92, ADR-0005 | Reader composite endpoint; `reader-response/v1`; `FinancialFact` promoted into the generated types. |
| 0.3.0 | 2026-07-16 | issue #100, ADR-0006 | Observable hybrid retrieval: queries, reruns, typed resumable SSE, traces, evidence feedback. |
| 0.4.0 | 2026-07-19 | issue #101, ADR-0007 | Bounded agentic extraction: runs, typed SSE, proposals/review, approved versions; open-enum loosening on volatile M2 labels. |
| 0.5.0 | 2026-09-02 | issues #194, #193, #157; ADR-0011, ADR-0012 | Additive: `claims-output/v1` schema + fixture; `ExtractionProposal.record_confidence` widened to nullable (required, NULL = "not yet scored"); `x-fel-status: planned` convention documented; `limit` on list endpoints; 413 `READER_TOO_LARGE`; `extraction_run_steps.output` per ADR-0011. |
