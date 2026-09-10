# ADR-0015: Structured claims output and independent numeric verification

Status: Accepted
Date: 2026-09-06
Occasioned by: issue #193 and review of PR #241
Acceptance: integration-lead review on 2026-09-07 ([PR #241](https://github.com/wilsonhj/financial-evidence-lab/pull/241#issuecomment-5574652267)); renumber to ADR-0015 approved there.

## Context

The reader needs a bounded structured-generation result for atomic claims,
citations, and explicit abstention. PR #241 adds `claims-output/v1` but originally
leaves the contract version at 0.4.0 and attributes the change to ADR-0012, which
instead concerns a proposed LLM provider substitution. `VERSIONING.md` explicitly
classifies a new schema as an additive minor change, even without HTTP changes.

The initial numeric shape omits scale and the generator copies scale from cited
evidence. Comparing that copied value with the same evidence cannot detect a
model asserting the wrong magnitude. Inheriting missing unit or period similarly
turns unknown assertions into apparent agreement. Spec sections 13.3 and 19.6
require independent numeric value, unit, period, sign, and scale checks.

## Decision

1. Register the new `claims-output/v1` schema, its fixture, and deterministic
   contract tests in `packages/contracts`. Advance OpenAPI `info.version`,
   `CONTRACT_VERSION`, and the package version from 0.5.0 to 0.6.0, serialized after PR #232. The new schema
   retains its initial `x-fel-version: 1.0.0`; it has not been released, so fixing
   its proposed shape does not revise an already frozen v1 schema.
2. Validate model output structurally before constructing claims. Objects reject
   unknown properties; nullable members remain required. Claims need nonempty
   text and citations. Each citation must resolve to an immutable selected item
   ID, and its nonempty quote must occur in that item's evidence text. Structural
   validity and quote presence do not establish semantic entailment.
3. Require each non-null numeric object to assert a finite decimal-string value
   and an integer base-ten scale independently of the evidence. Unit and period
   remain required nullable fields; null means unknown, never permission to copy
   evidence metadata. Numeric verification must not mark unknown dimensions as
   established agreement. Authoritative arithmetic remains decimal arithmetic.
4. Keep claim/citation confidence and support decisions with the verifier.
   Generation confidence is not evidence confidence. Unsupported, partial, or
   contradicted conclusions retain the existing qualified rendering rules.
5. Represent provider failure, invalid output, and explicit model abstention as
   typed generation outcomes, preserving available usage for cost accounting.
   Avoid converting an unsuccessful generation into apparently supported claims.

## Affected packages and migration analysis

- `packages/contracts`: schema, registry, fixture, version identity, and negative
  contract tests. Regenerate the TypeScript client and check for drift; the
  version-only OpenAPI edit adds no HTTP types or operations.
- `packages/retrieval`: structured generator, immutable context lookup, numeric
  construction, typed abstention, and verification inputs.
- `packages/providers`: deterministic mock output must include the explicit
  numeric scale and preserve the schema shape.
- Existing API integration consumes the generated claims through the existing
  retrieval pipeline. No endpoint or response-schema changes are proposed.
- No database migration is proposed. Quotes are carried and checked in process;
  the existing citation storage has no quote column. This ADR does not claim
  durable quote storage or authorize adding such a column.
- No live provider adapter or provider substitution is proposed. ADR-0012 stays
  separate and retains its own evidence and acceptance requirements.
- The schema is the local validation authority, not a guarantee of identical
  provider schema support. For example, [Anthropic's documented subset](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#pattern-support-regex)
  excludes string-length constraints and regex lookaheads; [OpenAI documents its
  own subset](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas).
  A live adapter must validate provider compatibility and, if necessary, adapt
  the generation schema while retaining full local output validation. This
  mock-only change does not prove that live-provider boundary.

## Mock verification boundary

The deterministic mock grants full text support only when the claim matches the
whole evidence text after whitespace normalization. Token overlap for transformed
prose is at most partial support with confidence below 1, even when a separately
asserted numeric tuple matches. Token sets do not preserve signs, negation, or
word order. Numeric mismatches remain decisive before the text check.

The prompt exposes evidence numeric metadata; independent assertion means the
provider returns its own tuple, not that it is blinded to the evidence. Matching
that tuple does not establish agreement between the claim prose and the tuple.
The whole-text restriction closes that gap for the mock without claiming live
semantic verification. Partial mock coverage is a lexical score, not a calibrated
probability of correctness. Live cutover must supply and evaluate a semantic
verifier before transformed prose can receive full support.

## Alternatives rejected

- Delay the version bump until an HTTP change: contradicts the explicit new-schema
  rule in `VERSIONING.md` and obscures the new contract identity.
- Copy missing numeric fields from evidence: verifies the evidence against itself
  and cannot test whether the model independently asserted the correct quantity.
- Treat a verbatim quote as sufficient entailment: an accurate quotation can
  still fail to support the claim's meaning.
- Mark this ADR accepted while fixing the PR: acceptance belongs to the
  integration lead and must be recorded through the review process.

## Verification and acceptance

Contract tests must validate all fixtures and schema registrations, reject absent
or non-integer scale and non-finite/non-decimal value strings, preserve nullable
unit/period, enforce version agreement, and detect generated-client drift.
Retrieval tests must reject altered magnitude and unknown numeric metadata as
verified agreement, reject unselected citations and ungrounded quotes, and retain
usage on abstention. Mock tests must exercise both numeric and qualitative output.

The integration lead accepted the decision and renumbering in the linked review.
The required `contract-change` label and review still apply to implementation
changes; acceptance does not waive verification or merge sequencing.
