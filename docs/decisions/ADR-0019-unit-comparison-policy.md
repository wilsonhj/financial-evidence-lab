# ADR-0019: Consistent unit comparison without rewriting source payloads

Status: Accepted for implementation under the owner's complete-backlog request;
independent source analysis and integration-lead design review completed.

Date: 2026-09-10. Issue: #153.

## Decision

Adopt `unit-comparison/v1`, one ontology-owned comparison policy shared by
accounting identities, duplicate/conflict grouping, monetary detection and
ontology value-family checks. Keep issuer unit spelling in normalized payloads
apart from the existing boundary trim. Do not constrain the free-form unit
schema, infer currency, convert units/FX, or change guidance ordering (#154).

Gross-profit, RPO/cRPO and segment identities must use the same unit key as
duplicates and conflicts. When multiple observations make an identity ambiguous,
its existing deferral to conflict detection must still flag the observations.
Folding only one side is forbidden.

## Explicit vocabulary

Trim boundary whitespace; never strip interior whitespace or normalize Unicode.
Case aliases require an ASCII guard. Known tokens `count`, `currency`, `pure`,
`ratio`, `shares`, `customers`, `percent`, `percentage`, `pct`, `pp` and
`percentage_points` admit ASCII case variants. `%`, `pct` and `percentage` map to
`percent`; `pp` maps to `percentage_points`. Percentage points remain distinct
from percent. Pure/ratio and shares/customers/count remain distinct identities.

Currency UNIT aliases use an explicit checked-in ISO-code vocabulary with source,
retrieval date and version recorded alongside it. Include the supported currency
set rather than a six-code shortcut; preserve CHF/SEK/INR coverage. Membership,
not an arbitrary three-letter regex, determines currency-unit aliases. USD/usd
map to USD; EUR/eur map to EUR. Unknown CPU/cpu remain distinct issuer units.

For slash forms, canonicalize a known currency numerator and preserve the
denominator verbatim: usd/mo becomes USD/mo, but USD, USD/mo, USD/yr and USD/Mo
remain distinct. Generic currency and recognized currency numerators require a
declared currency, including rate suffixes. Lowercase monetary units must not
bypass the existing missing-currency blocker. No currency is inferred.

Unknown strings retain case and Unicode: ss/ß, k/K and I/ı/İ remain distinct.
Malformed non-string values remain invalid; they must not collapse into a valid
empty token. The currency FIELD retains its existing uppercase ASCII alpha-3
syntax and is a separate identity axis. This does not relax lowercase currency
fields or equate USD with EUR or generic currency.

Apply canonical units to existing ontology family comparisons and retain issuer
spelling in diagnostics. Percent/PERCENT/% aliases behave consistently. Do not
expand this issue into unrelated family restrictions for unchanged pure, ratio,
shares or arbitrary unknown units. Existing percent-point plausibility checks
may share a family predicate without merging their identities with percent.

## Persisted identity

The clean payload and proposal-ID algorithm stay unchanged. For identical
run ID, kind, metric ID and clean payload, proposal IDs remain identical;
underscore metadata is stripped before hashing today. USD and usd source
payloads therefore retain distinct proposal IDs even when grouped together.

Conflict keys deliberately change: hash an envelope containing
`unit_policy_version` and the existing fact identity with canonical unit, after
the existing ontology-key substitution. All new groups use the new namespace,
including already-canonical units. Historical conflict keys, membership,
adjudication and history are not rewritten or aliased. Newly grouped proposals
require new review; old adjudication must not silently apply. Preserve the
same-policy terminal-conflict guard and idempotent replay.

## Versioned rollout and checkpoint safety

New-policy requests use `extraction-workflow/v2` and `validate/v2`. Keep the
normalizer version unchanged and explicitly pin the unit policy in both
normalize and validate stage inputs, alongside their normalizer/validator
versions. Include policy/version provenance in validation summaries, not clean
source payloads. The workflow namespace separates downstream stage identities.

Check supported workflow version at entry, before any checkpoint recovery.
The existing check inside validate_request can itself be skipped by recovery
and is insufficient. Valid old checkpoints must not bypass this boundary.
Preserve typed failure/audit behavior and reject before provider dispatch.

Never repin an existing immutable v1 run to v2. Re-extraction creates a new v2
run; historical v1 results remain readable. Completing an old v1 run requires
its pinned old release, or an explicit new run under v2. Document this deployment
boundary. No database migration, historical data rewrite or automatic bulk
re-extraction is authorized. Merely salting validate is insufficient because
persisted proposal inserts can retain old validation on conflict.

## Verification

Replace both known-gap tests with positive identity and duplicate/conflict
regressions across mixed case, including all three accounting identities.
Test distinct currencies, denominators, unknown/Unicode units, monetary blockers,
definition aliases, unchanged clean payload/proposal hashes, versioned conflict
keys and PostgreSQL adjudication/replay guards. Old valid v1 checkpoints must
be rejected before recovery; v2 crash-resume must preserve blockers and grouping
without extra provider calls. Verify actual stage input hashes carry the policy.

Run ontology and full extraction tests, PostgreSQL replay tests, formatting,
lint/types and current CI. No canonical task completion or live acceptance is
claimed by this policy decision. Independent implementation review precedes merge.
