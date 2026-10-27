# ADR-0029: Retrieval receipts for non-SEC provider fetches

Status: Accepted by the integration lead on PR #354 (2026-10-27).

Date: 2026-10-24

## Context

SEC evidence is content-addressed. `store_raw_document` keeps the exact bytes
under `raw/sha256/<hex>`, and `documents.content_hash` must match the bytes each
published version was parsed from. FRED and Alpha Vantage values have no
equivalent. `VintageObservation` and the frozen `MarketBar` carry a value and a
date, but not the URL, the retrieval time or a hash of the bytes the value was
parsed from. A forecast built from them cannot cite its inputs the way a
filing-backed claim cites a span.

This gap was recorded as an ADR candidate in
`docs/research/financial-evidence-skills-review.md`. That review found that an
external project attached, to every fetched source, the fetched-byte SHA-256, the
retrieval clock and the source URL. Nothing persists FRED or market data yet:
forecast storage is deferred to #66 by ADR-0023. So the receipt format and its
capture can be fixed now, before any storage depends on them.

## Decision

1. **Capture receipts at the shared HTTP layer.**
   `ThrottledRetryingClient.get_with_receipt()` returns the decoded response
   together with a `RetrievalReceipt`. `get()` is unchanged and drops the
   receipt. A receipt is produced only for a successful response; failed
   fetches still raise `HttpRequestError`.

2. **Receipt fields.**

   | Field | Meaning |
   |---|---|
   | `source_url` | The requested URL with its full query string. |
   | `final_url` | The URL that answered. It differs from `source_url` only when a followed redirect moved the request. |
   | `retrieved_at` | The timezone-aware instant, normalized to UTC, at which the body finished reading. The clock is injectable; a naive clock is refused. |
   | `status_code` | The final HTTP status. |
   | `content_type` | The response `Content-Type`, as sent. |
   | `byte_length` | The length of the decoded body. |
   | `content_sha256` | The SHA-256 of the decoded body, in the repository-wide `sha256:<hex>` format. This hashes the bytes the parser saw, the same bytes `raw_store` would hash, and not the gzip wire encoding. |
   | `attempts` | How many attempts it took, so retries are visible. |

3. **Credentials are never recorded.** Each adapter declares its secret query
   parameters: `api_key` for FRED and `apikey` for Alpha Vantage. Their values are
   replaced with `REDACTED` in both URLs. The parameter stays visible, so a
   reader can see that a key was sent. A receipt is therefore safe to store and
   display.

4. **The frozen provider protocols stay untouched.** The new capabilities are
   workers-local protocols, the same pattern `CompanyFactsSecClient` uses to
   extend `SecClient`:
   - `ReceiptedFredClient.series_vintage_with_receipt()`;
   - `ReceiptedMarketDataProvider.daily_adjusted_with_receipt()`.

   The live clients implement both. `FredClient`, `MarketDataProvider` and
   `MarketBar` in `packages/providers` do not change.

5. **Receipts reach the domain objects.**
   - `ingest_fred_vintage` attaches the receipt to every `VintageObservation`
     when the client has the capability.
   - `assemble_receipted_forecast_features` returns `(rows, receipt)` beside the
     unchanged `MarketBar` rows.
   - A mock or other non-receipting client yields `receipt=None`, because
     nothing was retrieved. Code must not substitute a placeholder.

6. **A receipt is provenance, not identity.** `VintageObservation.receipt` is
   excluded from equality and hashing. The same vintage fetched twice compares
   equal, which keeps the point-in-time invariants intact, while each copy keeps
   its own receipt.

## Consequences

- Forecast storage (#66) must persist each input's receipt with the input it
  vouches for. Storage must also not accept a live-sourced input without one.
  This ADR does not create that table; ADR-0023 still governs its migration and
  contracts.
- If the raw response bytes are later stored, `content_sha256` is the key that
  ties them to the value. The format matches `content_address()`, so the same
  bytes produce the same key.
- No API, schema, migration or frozen-protocol change is made. `get()`,
  `series_vintage()`, `daily_adjusted()` and `assemble_forecast_features()`
  behave as before.

## Out of scope

- **Explicit FRED missing values.** ALFRED's `"."` placeholder is still
  dropped. Changing that changes the `FredClient` return type and needs its own
  ADR.
- **Named source clocks.** Receipts record retrieval time only; source-reported
  times such as release time and period coverage are not captured.
- **SEC.** Documents are already content-addressed. Adding a retrieval-time
  receipt to `documents` would need a migration.
