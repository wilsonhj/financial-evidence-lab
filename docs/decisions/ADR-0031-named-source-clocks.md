# ADR-0031: Named source clocks

Status: Accepted by the integration lead on PR #354 (2026-10-27).

Date: 2026-10-24

## Context

ADR-0029 records when the lab fetched a response. A provider also reports
times about its own data inside the response. ALFRED gives the real-time window
that a vintage describes and the observation range. Alpha Vantage gives the
date its series was last refreshed and the time zone that date is in. These are
different clocks from the retrieval time, and none of them is interchangeable
with another. Without them, a reader cannot tell a stale series fetched today
from a fresh one.

This was the third ADR candidate in
`docs/research/financial-evidence-skills-review.md`. That review found that an
external project read each such field through an explicit allowlist, kept the
field's JSON Pointer, and never inferred freshness from it.

## Decision

1. **`SourceClock(name, value, path)`.**
   - `value` is the source's string verbatim. It is never parsed, normalized or
     converted between time zones: the source's own spelling and convention are
     the evidence.
   - `path` is the RFC 6901 JSON Pointer the value was read from. It points into
     the exact bytes the enclosing receipt's `content_sha256` identifies.
2. **Explicit allowlists, never discovery.** Each adapter declares the fields it
   reads. `read_source_clocks()` follows only those exact object-key paths. A
   clock is recorded only when its path exists and holds a non-empty string; a
   null, a number or any other value counts as not reported.
   - **FRED** (`FRED_SOURCE_CLOCKS`): the top-level `realtime_start`,
     `realtime_end`, `observation_start` and `observation_end`. Per-row
     `realtime_*` fields are not read: with the real-time window pinned to one
     day, they only repeat it.
   - **Alpha Vantage** (`ALPHAVANTAGE_SOURCE_CLOCKS`): `Meta Data` →
     `3. Last Refreshed` and `5. Time Zone`. The time zone is recorded beside
     the date, because the date alone does not name one.
3. **Clocks ride on the receipt.** `RetrievalReceipt.source_clocks` holds them.
   The clocks describe the same bytes the receipt vouches for, and every
   observation, gap and feature row already carries the receipt, so no fetch
   signature changes.
4. **"None reported" differs from "not read".** `source_clocks == ()` means an
   adapter looked and the source reported none. `None` means nothing
   source-aware read the body: the HTTP layer alone never fills it.
5. **No inference.** Nothing derives freshness, staleness or eligibility from a
   clock. Comparing clocks, for example refresh date against retrieval time, is
   a downstream policy decision that needs its own record.

## Consequences

- Forecast storage (#66) can store each input's source clocks with its receipt.
  A view can then show "fetched at X, source refreshed Y" with a pointer to
  where Y came from.
- Adding a clock to an adapter is a reviewed one-line allowlist change, not a
  parser change.
- No API, schema, migration or frozen-protocol change is made. Receipts that
  ADR-0029 already defines gain one optional field.

## Out of scope

- **Freshness or staleness rules** built on these clocks.
- **SEC.** EDGAR filing times are already recorded as `documents.filed_at` and
  `documents.published_at` (spec 10.3).
- **Per-row clocks** for sources whose rows carry real information, which no
  current adapter has.
