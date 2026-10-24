# Review: beepboop2025/financial-evidence-skills (v0.1.5, `8aeb6c0`)

Reviewed 2026-09-26 for ideas worth adapting. The project is a small,
read-only router that fetches JSON from four fixed public endpoints and
returns it as a "packet" without scoring it. Most of its guarantees are
already exceeded here (claim verification, point-in-time cutoffs,
content-addressed raw storage). What follows is what was adopted, what was
improved on, and what is left as a proposal.

## Adopted, in `workers/src/fel_workers/http.py`

| Their idea | Their form | Adapted form here |
|---|---|---|
| Fixed destination allowlist | Exact URL set; all redirects refused | Per-adapter HTTPS host set, enforced on **every hop before it is sent** via an httpx request hook. SEC keeps working redirects inside EDGAR. |
| Reject redirects | Custom urllib handler | A 3xx is an error whenever the client does not follow redirects; previously it returned as a successful response. |
| Bounded body | `read(max_bytes + 1)` on the raw stream | Streamed cap on **decoded** bytes (a gzip body cannot expand past it), with a `Content-Length` pre-check. 64 MiB default; 256 MiB for EDGAR. |
| Per-request timeout | Socket timeout only (slow-drip can run unbounded) | Adds a total per-attempt deadline; a slow drip is retried like a transport error. |
| Retrieved ≠ usable (`transport_status` vs `evidence_status`) | Packet-level fields | Alpha Vantage's HTTP-200 `Note`/`Information` refusals now raise a refusal error instead of "adjusted data is unavailable"; non-JSON bodies from FRED/Alpha Vantage raise the adapter's domain error. |

The allowlist closes a real gap: `handle_sec_filing_fetch` passes the job
payload's `url` to `LiveSecClient.fetch_document`, which previously followed
redirects to any host and stored the reply as a filing.

## Not adopted

- **Multi-channel distribution** (Agent Skill, MCP, Homebrew, marketplaces).
  It is a product decision, and the lab has no public read API that is ready to
  expose yet.
- **Duplicated standalone script.** The skills repo keeps two copies of its
  core so the skill has no dependencies, and that invites drift. If the lab ever
  ships an Agent Skill, it should call a published API or package, not a copy.
- **"Never convert absence to zero"** is already enforced for market bars
  (FOR-005) and by the claim pipeline.

## Proposals that need an ADR (they touch frozen contracts)

1. **Retrieval receipts for non-SEC sources.** Proposed as [ADR-0029](../decisions/ADR-0029-retrieval-receipts.md) and implemented without changing the frozen protocols. The original candidate text follows. SEC bytes are
   content-addressed. FRED and Alpha Vantage values are not: a
   `VintageObservation` carries no source URL, retrieval clock or byte hash.
   Adding `{source_url, retrieved_at, content_sha256}` would let every FRED or
   market number cite the exact bytes it came from, as SEC spans already do.
   `FredClient`/`MarketDataProvider` return shapes are frozen protocols.
2. **Explicit FRED missing values.** Proposed as [ADR-0030](../decisions/ADR-0030-explicit-fred-missing-values.md) and implemented without changing the frozen protocols. The original candidate text follows. ALFRED's `"."` placeholder is currently
   dropped. The series then reads as if the period never existed. Returning an
   explicit missing marker would distinguish "not published" from "not
   requested"; this changes the `FredClient` return type.
3. **Named clocks on source-reported metadata.** The skills repo keeps each
   upstream clock separate (`generated_at`, `as_of`, release vs collection) with
   a JSON Pointer to where it was read. The lab's spec 10.3 temporal fields
   could record which upstream field each clock was taken from.
