# ADR-0024: Extraction review and conflict occurrences

Status: Accepted by the integration lead under the owner's backlog implementation instruction

Date: 2026-09-10

Issue: #278, prerequisite for #61 and #135

## Context

The M3 contract describes human review, immutable approval history and reruns,
but generic review patches leave the implementation's atomic decisions unclear.
Run versions do not advance on every worker update, and the current workspace-wide
conflict identity refuses a child run after the earlier group is adjudicated.
PR #272 supplies bounded paging and complete-or-error evidence reads; accepted
ADR-0022 defines the current normalizer and range semantics.

The owner requested implementation of all open issues with parallel agents and
review, tests and approval before every PR merge. This decision defines the
contract prerequisite without changing financial calculations or accepting a
live-provider substitution. The detailed implementation design is
[the extraction review plan](../superpowers/plans/2026-09-10-extraction-review.md).

## Review, history and concurrency

Use typed, closed accept/edit/reject/merge inputs. Every selected proposal has
an expected version; any stale member aborts the transaction with 412. Edit
supplies a full typed replacement and evidence. Merge copies one explicitly
selected input payload and preserves the verified union of evidence; no numeric
aggregation or implicit existing-head lookup is permitted.

Explicit conflict resolution carries a complete bounded membership/version
snapshot, its ETag, selected winners and a reason. Unselected states remain
unchanged. The immutable review records the adjudication. Later contradictory
acceptance is blocked against recorded winners; an explicit edit eliminating
the contradiction is revalidated. A reason never waives financial, citation,
accounting or temporal blockers. No reopening or rewriting an earlier decision.

Approved corrections use existing immutable child versions, append-only audit
and exact receipts. They do not expand the proposal-review action enum. New
versions record current validation policy plus original source-run provenance
in nullable immutable validation_context; historical NULL provenance is not
invented or backfilled. Current normalize/v2, including only its accepted
negative-range canonicalization, remains authoritative and unchanged.

Run ETags digest the complete deterministic representation, including status,
usage and cancellation; compare after locking the run. The stored integer version
is metadata, not an assumed concurrency token. No version trigger is added.
New extraction idempotency scopes use a versioned request-hash/headers/body
envelope in existing response_body. Successful replay returns that original
semantic response after current authorization and before stale-version checks.
Different canonical actor/resource/action/body/preconditions with the same key
return 409. Receipts, review, versions, audit and state commit atomically.

Queued/running cancellation sets a durable run marker and the bound job marker,
then relies on existing cooperative worker fencing. Waiting-review cancellation
appends its terminal event and state together, preserving proposal history.
Terminal events precede terminal state; a fresh terminal cancellation is 409.

## Conflict occurrence persistence

Preserve the financial conflict hash and all existing NULL legacy occurrences.
Add nullable occurrence_run_id with a same-tenant/workspace run foreign key;
replace uniqueness with (org_id, workspace_id, conflict_key, occurrence_run_id)
NULLS NOT DISTINCT. Existing keys and decisions are never rewritten.

New run producers pin conflict_occurrence_policy = run/v1 inside their immutable,
hashed, text-free input_manifest. Persistence reads the authoritative manifest
and proposal run IDs: all members of a new occurrence belong to that run. An
absent policy retains legacy behavior; a present malformed/unknown policy fails
closed. A retry reuses its occurrence; a child run gets an independent group
with no inherited approval. This is explicit persistence identity, not a change
to the financial hash function or workflow/normalizer/validator v3/v2/v3 pins.

A worker-aware member-insert guard first locks/asserts the member run, then locks
the group, matching review's run-before-group order. It rechecks open state,
tenant/workspace and occurrence constraints. It closes the race between
worker status reads and a reviewer resolving the group. Exact existing-member
retry may remain an ON CONFLICT no-op without adding or rewriting history.
Occurrence identity and resolved adjudication are immutable.

## Bounds and temporal context

Run/proposal/history lists use explicit pages, default 50 and maximum 200.
Reviews select at most 100 proposals; complete conflict membership is bounded
and cannot be inferred from a partial page. Creation resolves every requested
source ID and caps requests/evidence before expensive materialization. The plan
specifies request, evidence, event and client-retention ceilings. Oversized
validation dependencies fail explicitly rather than accepting partial evidence.

Existing artifacts expose and use their frozen source/corpus/cutoff. New creation
uses min(workspace cutoff, requested cutoff); a new child uses min(current
workspace cutoff, parent cutoff). If unchanged selected sources no longer qualify,
fail before enqueue rather than widening the cutoff or silently dropping sources.

SSE carries existing extraction-event/v1 metadata only, with bounded history,
strict resume IDs, heartbeats, tenant rechecks and connection release between
fetches. Waiting_review is nonterminal. Confidence NULL means uncalibrated;
this decision does not invent calibration or auto-approval.

## Scope and rollout

Issue #278 owns the 0.8.0 contract, generated types/fixtures, additive migration
0011 and compatible conflict persistence together. Individual new /v1 schemas
start at x-fel-version 1.0.0. Existing financial payload/event schemas and old
migrations remain unchanged. The reference extraction contract is aligned with
the root OpenAPI under the same ownership. Backend and web implementation are
separate dependent lanes; no consumer hand-maintains generated types.

Old workers use the three-column ON CONFLICT target. Drain/stop them before
applying 0011, then deploy the compatible worker before enabling new producers.
No zero-downtime claim is made. Rollback stops producers and preserves migrated
rows; no destructive downgrade is authorized. Hosted execution remains subject
to #177/#108's environment gate and is not performed by this implementation.

## Verification

Require fresh-install and 0010-upgrade PostgreSQL tests, RLS/grants/immutability,
legacy NULL compatibility, same-run retry and concurrent upsert, resolved-parent
child success, cross-run rejection and member-insert/resolution races. Full
worker/ontology/financial goldens remain unchanged. Contract generation, valid
and invalid fixtures, full required CI and independent final-head approval gate
merge. The API/UI then prove real-byte validation, atomic review/correction,
exact replay, cutoff/tenant behavior and incremental browser SSE before #61/#135
acceptance. Live provider, calibration and release evidence remain separate.

### Test migration compatibility authorization

The integration lead authorizes only `_SCHEMA_PROBES` additions in
`workers/tests/extraction/test_postgres_crash_resume.py` for the 0011 occurrence
column and four-column NULLS NOT DISTINCT unique identity. Existing sibling
databases must fail the current-schema probe until upgraded/rebuilt. Helper
behavior, existing financial assertions and goldens remain unchanged.

The full regression suite requires two existing SQL fakes to return authoritative
proposal/run manifest rows for the new occurrence lookup. The lead authorizes
only those fake-result additions in test_conflict_resolution_reuse.py and
test_review_fixes.py; their existing assertions and financial tests are preserved.
The terminal conflict error retains its resolved/superseded status description.

The lead also authorizes the shared-version assertion in
`apps/api/tests/test_list_contract.py` to advance from 0.7.0 to 0.8.0 alongside
this contract release. Its existing pagination and reader assertions are unchanged.

### Workspace permissions projection

The lead accepts a narrow planned workspace extraction-permissions read so the
web UI can render role-appropriate controls even for an empty queue. Return only
workspace_id and a closed allowed_actions list, derived from database-resolved
membership and workspace visibility. Owners/editors receive all eight actions;
reviewers receive accept/edit/reject/merge/correct; viewers receive none. All
four roles may read. Reauthorize every mutation; use no-store and keep these
mutable capabilities out of immutable artifact representations/ETags. No new
authentication system or trust in token role claims is introduced. The handler
and role matrix tests belong to the dependent #61 backend implementation.

## Amendment 1: readable invalid candidates (#284)

Accepted by the integration lead on 2026-09-11 after independent design review.
Worker normalization deliberately preserves malformed candidates with blockers;
the proposal read contract must not hide them or require a repair to display them.
Only `ExtractionProposal.payload` gains an alternative closed wrapper with
`schema_version: extraction-candidate-fields/v1` and `fields`. The latter is a
closed map of the finite union of existing public financial property names to
strings containing each persisted field's JSON representation. The financial
payload schema itself, approved records and all mutation inputs remain strict.
Only proposal-read evidence permits zero edges. Top-level proposal kind, metric,
confidence, state and version retain their existing definitions.

Read classification strips only legitimate worker evidence extensions before
checking the frozen financial schema. Use the text projection if the candidate
fails that schema or contains a JSON numeric leaf that is not an integer within
plus/minus 9,007,199,254,740,991. Apply this display predicate recursively, excluding
booleans and numeric strings; fractional numbers conservatively use text. Ordinary
schema-valid, display-safe data keeps its existing shape even when other blockers
remain. The wrapper does not determine financial validity or approval status.
For the text projection, obtain allowlisted field text directly from PostgreSQL
`(payload -> key)::text`, before numeric decoding in Python or JavaScript. Missing
keys remain absent; present JSON null becomes the string `null`. This preserves
persisted JSON values and types, not original provider lexical spelling (JSONB
normalizes formatting). Do not use this display representation for financial
hashing. Unknown/control field names and values are omitted from the public map.

The browser renders these strings as plain text without JSON.parse, Number,
HTML interpretation or automatic conversion into edit commands. An edit is a
deliberately supplied full strict replacement. No new lossless parser is needed.
Bound each field representation to 65,536 characters and preflight serialized
proposal payload bytes to 1 MiB before fetching; overflow returns a typed 413 with
the safe resource ID, never a truncated candidate. The finite field map bounds
its overall shape. Projection of stored blockers is separate and safe: retain
failure codes without reflecting submitted values, unknown field names or raw
summary objects. Never infer an overall pass from `validation_summary.ok`, which
can remain true after duplicate blockers were appended.

Issue #284 owns package/OpenAPI version 0.9.0, the new individually versioned
schema, generated types, fixtures/tests, reference OpenAPI alignment and backend/
web plan clarifications. The API list-contract test may change only its shared
version assertion. ADR-0017 and the handoff register this prerequisite before
both runtime lanes. No migration, worker change, provider call or task completion
is implied. Require invalid-value/empty-evidence fixtures, safe-number edge cases,
control-field rejection, unchanged valid shape, strict mutation rejection,
generation checks, independent review and all required CI before merge.
