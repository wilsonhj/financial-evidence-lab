# Signed guidance range policy deployment

[ADR-0022](../decisions/ADR-0022-guidance-range-ordering.md) introduces
`guidance-range-order/v1`, `normalize/v2`, `validate/v3` and
`extraction-workflow/v3`. Unit comparison remains `unit-comparison/v1`.
This supersedes the v2 producer target in the
[unit policy rollout](unit-policy-migration.md).

Normalized range `low` and `high` are signed numeric lower and upper bounds.
After Decimal parsing and common-scale reconciliation, only `high < low < 0`
is swapped: `(5)` to `(15)` becomes `-15` to `-5`. Positive, mixed-sign and
zero-to-negative inversions remain blocked for review. All range metrics,
including free-text issuer labels, receive the strict ordering validator.
Point, floor, ceiling and qualitative shapes retain their meaning.

Source wording, signed magnitudes and source unit spelling are preserved.
The clean payload hash and proposal ID legitimately change when negative
endpoints are rewritten; unchanged clean payloads retain their hashes and IDs.
The proposal ID algorithm and `extraction-payload/v1` schema are unchanged.
Opposite source wordings can retain distinct proposal IDs while producing the
same economic-value fingerprint and a duplicate finding.

## Deploy and verify

1. Retain the old worker release for queued or interrupted v1/v2 runs. Deploy
   the v3 worker and configure new extraction requests to pin
   `extraction-workflow/v3`. Producers must use the version supported by their
   worker. Existing persisted run pins are immutable: never automatically repin
   an old run. An explicit new v3 extraction run is the alternative to finishing
   an old run with its matching worker release.
2. Verify normalize and validate stage input hashes include their component,
   unit-policy and range-policy pins. Validation summaries must report
   `normalize/v2`, `validate/v3`, `unit-comparison/v1` and
   `guidance-range-order/v1`. Policy metadata belongs to summaries and stage
   inputs, not clean source payloads.
3. Verify the new worker rejects both v1 and v2 before loading any checkpoint
   or dispatching any provider call, including valid succeeded old checkpoints.
   No old checkpoint migration or reuse is supported. Keep historical completed
   proposals and source payloads readable without modification.
4. Run the fixture-backed extraction and ontology suites with
   `TEST_DATABASE_URL` pointed at an isolated, migrated test database. The real
   PostgreSQL regressions cover fresh-store resumes after normalize and validate,
   preserved raw and normalized payload hashes, zero repeated model calls, old
   v1/v2 checkpoint rejection and historical conflict preservation.

All new conflict groups include both unit and range policy versions in their
identity envelope, including groups without ranges. This prevents a new-policy
reading from reusing old disagreement reasons or adjudication. Old conflict
rows, members, resolutions and audit history remain unchanged. The new group
requires its own review; there is no automatic adjudication transfer. Replaying
an open same-policy group remains idempotent, and the terminal-conflict guard
still rejects attachment to an adjudicated same-policy group.

Rollback means routing runs to a worker that supports their immutable pin.
Do not route v3 runs to an old worker or rewrite them as v2. Stop new v3 request
creation if the v3 worker is unavailable; retained old workers can finish their
own existing runs. No database migration, bulk re-extraction, historical rewrite,
live provider calls or hosted deployment is part of this policy change.
