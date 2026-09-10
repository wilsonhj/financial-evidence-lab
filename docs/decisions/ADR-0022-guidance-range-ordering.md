# ADR-0022: Signed guidance range ordering

Status: Accepted for implementation under the owner's backlog execution request

Date: 2026-09-10

Issue: #154; prerequisite: ADR-0019 and merged PR #264

The integration lead accepts the independently prepared narrow design below.
It implements the existing issue acceptance without widening positive/mixed-sign
repair or modifying the payload schema. Scope and tests are registered in the
execution ledger; no canonical task completion is implied.

## Outcome and selected policy

Normalized guidance `low` and `high` are signed numeric lower and upper bounds,
respectively. An invalid candidate can retain inverted fields for review, but
must carry the existing `guidance range low must be <= high` blocker. Apply the
same rule to ontology metrics and issuer-defined/free-text metrics.

The permitted canonicalization is deliberately narrower than unconditional
sorting: after existing Decimal parsing and common-scale reconciliation, swap
the two fields only when `high < low < 0`. This accepts both source orders of a
wholly negative accounting range, including parentheses and explicit minus
notation. Never apply `abs()` to persisted values. Never infer negative values
from a metric named `net_loss`, from prose, or from the standalone `sign` field.

| Input endpoints | Normalized endpoints | Ordering result |
| --- | --- | --- |
| `(5)`, `(15)` | `-15`, `-5` | valid |
| `(15)`, `(5)` | `-15`, `-5` | valid |
| `-5`, `-15` | `-15`, `-5` | valid |
| `-15`, `-5` | `-15`, `-5` | valid |
| `(5)`, `(5)` | `-5`, `-5` | valid |
| `120`, `125` | `120`, `125` | valid |
| `300`, `200` | `300`, `200` | blocked, including `revenue` |
| `-5`, `5` | `-5`, `5` | valid |
| `5`, `-5` | `5`, `-5` | blocked |
| `-5`, `0` | `-5`, `0` | valid |
| `0`, `-5` | `0`, `-5` | blocked |

The zero/mixed-sign boundary is an explicit conservative choice, not an issue
requirement: issue 154 proves the two-negative case and requires that positive
transcription errors stay detectable. Sorting across zero also changes which
polarity the payload's one `sign` describes. Keep those ambiguous reversed
inputs reviewable instead of adding a second sign contract in this issue.
The integration lead may widen this boundary before dispatch, but must then
specify declared-sign validation and add corresponding tests.

For both-negative pairs, `sign` remains negative before and after the swap. The
existing declared-sign contradiction blocker survives; e.g. a declared positive
sign over `(5)`/`(15)` must not become clean merely because ordering was fixed.
No new normalizer blocker is necessary for a permitted swap. Positive and mixed
inversions are validation errors, as today for known metrics; do not manufacture
a normalizer rejection that changes unrelated accounting participation.

## Preserve source and shape semantics

- Preserve `raw_value` verbatim, including endpoint order, punctuation and units.
  Existing raw model-stage checkpoints preserve the actual input fields; no new
  public `source_low`/`source_high` properties or issuer qualifiers are needed.
- Preserve the signed endpoint multiset and existing mantissa-plus-scale
  representation. Reconcile suffix scales first, then compare the reconciled
  signed Decimal values. For example `(900 million)` / `(1.2 billion)` becomes
  `low=-1200`, `high=-900`, `scale=6`, with original `raw_value` unchanged.
- Keep unit spelling exactly as policy 153 specifies. Unit aliases are a
  comparison policy; this issue intentionally rewrites only eligible range
  endpoints. No FX conversion, unit folding, or metric polarity assumptions.
- Only `kind=guidance, shape=range` gets the swap. Point, floor, ceiling and
  qualitative shapes retain their fields and meaning. A negative floor stays a
  floor with its `low`; a negative ceiling stays a ceiling with its `high`.
- Preserve existing invalid-scale, missing-field, currency, sign, schema and
  citation blockers. No inference from raw prose to repair malformed endpoints.
  Re-normalization is idempotent and never mutates the caller's dictionary.

## Minimal implementation

1. `workers/src/fel_workers/extraction/normalize/payload.py`: after numeric
   parsing and common-scale reconciliation for a range, conditionally swap the
   two negative Decimal endpoints before formatting them back to strings.
   Keep the existing `_resolve_sign` path and blocker retention. The two-negative
   predicate means moving endpoints cannot by itself change primary polarity.
   Do not introduce a generic sorting framework or change the numeric parser.
2. `workers/src/fel_workers/extraction/validate/range.py`: make `range_errors`
   translate the existing `check_range` codes to the existing live messages.
   It runs unconditionally through `_collect_blockers`, so this fixes free-text
   metrics without granting them ontology status. Keep `check_range` strict: a
   direct validator caller with `low=-5, high=-15` must be blocked until it
   normalizes. Avoid NaN/Infinity comparisons by treating non-finite endpoints
   as `range_bounds_not_decimal`; these are already outside decimal-string
   contracts, and must fail closed at this newly universal ordering boundary.
3. `workers/src/fel_workers/extraction/validate/accounting.py`: remove its
   `check_range` import and ordering loop once `range_errors` owns the live call.
   Leave its ontology gate and metric-specific checks alone. Update direct
   helper tests that previously expected an accounting helper to own range
   validation; assert full-pipeline and `range_errors` behavior instead.
4. Add a small `RANGE_POLICY_VERSION = "guidance-range-order/v1"` constant beside
   workflow component constants in `types.py`. Set `WORKFLOW_VERSION` to
   `extraction-workflow/v3`, `NORMALIZER_VERSION` to `normalize/v2`, and
   `VALIDATOR_VERSION` to `validate/v3`. Unit policy stays `unit-comparison/v1`.
5. `workflow.py`: include `range_policy_version` in both normalize and validate
   stage input payloads alongside the existing component/unit pins. Retain the
   entry version gate before any checkpoint loading. `validate/pipeline.py`
   includes range policy and normalizer version in validation summaries, beside
   validator/unit policy provenance; do not put them into clean source payloads.
6. `validate/duplicates.py`: add `range_policy_version` to the hashed conflict
   envelope alongside `unit_policy_version` and `identity`, after ontology key
   substitution. Apply it to ALL groups in this release, not only range-shaped
   rows: shape-selective salting would separate otherwise comparable guidance
   observations before their values can be checked. Fact identity axes and
   `value_fingerprint` algorithms themselves do not change.
7. Record the decision in reserved ADR-0022 and a focused deployment runbook
   `docs/runbooks/guidance-range-policy-migration.md`; add a short successor
   pointer to the unit-policy runbook so v2 is not advertised as the current
   producer target after v3 ships. The ADR explicitly defines normalized bound
   semantics and permitted source-order correction. Structural payload schema
   and `extraction-payload/v1` stay unchanged: no field/type changes or new DB
   migration are needed. Prompt changes are unnecessary to make the rule
   deterministic; do not broaden this into model extraction redesign.

## Persisted identity and deployment decision

`validate/pipeline.py` computes `raw_payload_hash = hash_json(clean)` after
stripping underscore metadata. `proposal_id_for` hashes run ID, kind, metric ID
and that hash. Keep this algorithm. For a fixed run ID, the rewritten negative
range legitimately gets a new clean hash/proposal ID relative to v2; unchanged
payloads keep identical hashes and IDs. `raw_value` still participates in clean
hashing, so equivalent ranges with different issuer wording may have distinct
proposal IDs while sharing an economic-value fingerprint. Do not assert that
all semantically equal extractions collapse to one proposal.

Bounds are absent from `comparability_key_for` and `conflict_key_for` fact
identity, but present in `value_fingerprint`. Canonicalization can therefore
change an existing disagreement into a duplicate without changing the old fact
key. Keeping 153's envelope alone risks reusing an old conflict's reason codes
(`ON CONFLICT DO NOTHING`) or hitting its adjudication guard. A separate range
policy namespace answers this problem explicitly. Historical keys, members,
resolution, reviewer history and proposal payloads remain unchanged; new-policy
groups receive new IDs. This intentionally also creates fresh namespaces for
unchanged groups, a simple deployment boundary like ADR-0019's. It does not
implement missing cross-run candidate retrieval.

153's v2 pins MUST advance again: both normalized payloads and validator results
change. Salting only validate or normalize is insufficient: recoverable downstream
checkpoints can skip work, and persisted proposal upserts can retain stale
validation for unchanged clean payloads. New extraction requests use immutable
v3 runs. Never repin an existing v1/v2 run or rewrite completed results. A queued
or interrupted old run uses its pinned old worker release, or an explicitly new
v3 extraction run. The new worker rejects v1 AND v2 before checkpoint recovery
or provider dispatch, even when old checkpoints have valid output hashes.

No bulk re-extraction, historical backfill, cross-version checkpoint migration,
automatic conflict adjudication transfer, schema-major release, or live provider
calls are authorized. Existing historical results remain readable. Preserve
same-policy idempotent persistence, atomic outputs and terminal-conflict guards.

