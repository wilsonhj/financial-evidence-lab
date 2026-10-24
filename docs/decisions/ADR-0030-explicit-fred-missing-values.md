# ADR-0030: Explicit FRED missing values

Status: Proposed. Awaiting integration-lead acceptance on the implementing PR.

Date: 2026-10-24

## Context

ALFRED returns `"."` for an observation date that a vintage covers but has no
value for. `LiveFredClient.series_vintage` dropped those rows, so the series
then read as though the date had never been requested. Downstream there was no
way to tell three cases apart:

- the source published no value for this date;
- this date was outside the request;
- the client cannot know.

The same parser also silently skipped rows that were not JSON objects, and it
treated a row with no `value` key as a published gap. It accepted `NaN` and
`Infinity` as values.

The frozen `FredClient.series_vintage()` returns `list[tuple[date, Decimal]]`.
That type cannot carry an absence without changing a contract other code
depends on. This was recorded as an ADR candidate in
`docs/research/financial-evidence-skills-review.md`.

## Decision

1. **Parse once and keep the gaps.** `LiveFredClient.fetch_vintage()` returns a
   `FredVintageFetch` containing:
   - `points`, the published values;
   - `missing`, the dates returned as `"."`;
   - `receipt`, the ADR-0029 retrieval receipt.

   `series_vintage()` and `series_vintage_with_receipt()` derive from that one
   parse, and their output is unchanged.
2. **Workers-local capability.** `GapReportingFredClient` extends
   `ReceiptedFredClient` with `fetch_vintage()`. This is the same
   additive-capability pattern as ADR-0029, and `FredClient` is untouched.
3. **Gaps are domain records, never values.** `ingest_fred_vintage_record()`
   returns a `FredVintageRecord`:
   - `observations` are the `VintageObservation`s, as before;
   - `missing` holds one `MissingObservation(series_id, observed_on, as_of,
     receipt)` per gap.

   A gap is never turned into a zero, a carried-forward value or a dropped row.
   Each gap carries the receipt of the response that reported it.
4. **"No gaps" differs from "unknown".** `missing == ()` means the source
   reported no gaps. `missing is None` means the client cannot report them, for
   example the mock. Code must not treat `None` as `()`.
5. **`ingest_fred_vintage()` keeps its contract.** It returns the same
   observations and omits gaps. It now delegates to `ingest_fred_vintage_record`.
6. **Malformed rows fail closed.** The parser raises `FredIngestionError` for a
   row that:
   - is not an object;
   - lacks `date` or `value`;
   - repeats an observation date;
   - has a value that is not a finite decimal.

   Only the exact `"."` placeholder means missing.

## Consequences

- Forecast storage (#66) can store a gap as an explicit row. It must not
  interpolate or impute one without recording that it did.
- `series_vintage()` now rejects payloads it used to skip silently. Real ALFRED
  responses are unaffected: they never repeat a date in a single-day realtime
  window and always carry both keys.
- No API, schema, migration or frozen-protocol change is made.

## Out of scope

- **Named source clocks.** Recording release times and period coverage from the
  payload is still an open ADR candidate.
- **Gap semantics beyond the source's own report.** Whether a gap means "not
  yet released" or "discontinued" is not inferred. The record keeps only what
  ALFRED said.
