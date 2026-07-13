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
