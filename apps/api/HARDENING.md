# API hardening and compatibility

ADR-0021 (#191), contract 0.7.0 adds explicit bounded reads while preserving
in-bound legacy response shapes. Lists without limit/cursor return the whole
result through 50 rows or 409 `PAGINATION_REQUIRED`, with restart parameters.
Explicit page mode uses limit 50 (maximum 200), total-key ordering, a high-water
key and next/previous cursor headers. Every page authenticates and reapplies
RLS, cutoff and parsed/corpus eligibility before LIMIT. Cursors are strictly
typed unsigned continuation data; they grant no authority and are never logged.
Refresh starts a new traversal. Backfilled commits and mutable status may appear
between requests; high water is not a cross-request MVCC snapshot.

Reader calls return a complete selected target block or 413 `READER_TOO_LARGE`.
Target-only `include_siblings=false` is independent of sibling history size.
Related pages default to 10, maximum 20. Legacy complete sibling sets stop at
20 (overflow is 409). Optional `document_version_id` keeps target evidence fixed
across requests and must agree with a published corpus pin when supplied.
Each response uses a database snapshot; unpinned cross-page history is browsing,
not authoritative immutable comparison. The web discloses incomplete coverage,
keeps original filing links, and never labels an unvisited amendment chain current.

Fixed positive reader bounds are 2,000 sections, 10,000 spans and 10,000 facts
per document, 16 MiB canonical bytes, 32 MiB total JSON response and 32 MiB
summed hash-verification bytes per document. SQL cap+1/count/byte probes precede
large payload transfer; canonical files use bounded binary reads before strict
UTF-8 decode. Repeated Unicode section slices and overlapping hash work are
counted before materialization. No partial block or orphaned fact is returned.

Complete traces have fixed ceilings of 2,000 candidate IDs / 32,000 lane
contributions, 10,000 events, 1,000 claims, 16,000 citations and 16 MiB serialized
JSON; overflow is 413 `TRACE_TOO_LARGE`. Events have a 256 KiB serialized ceiling.
SSE replays through captured high water in batches of 200 and releases the DB
connection before yielding. First-batch overflow returns 413; later corruption
aborts replay without inventing a terminal event. Last-Event-ID resumes strictly
after the delivered sequence. The independent event-history endpoint supports
oldest/newest inspection even if the full trace cannot fit.

## Measured index and resource evidence

Local PostgreSQL/pgvector, 2026-09-10, 100,000-row synthetic histories,
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` before/after migration 0010:

| Read / SQL order | Before ms | After ms | After scan rows | Index |
| --- | ---: | ---: | ---: | --- |
| workspace created_at,id LIMIT 51 | 10.807 | 0.076 | 51 | workspaces_org_created_id_page_idx |
| document published_at,accession C,id LIMIT 51 | 16.303 | 0.105 | 51 | documents_entity_published_accession_id_page_idx |
| run started_at,id LIMIT 51 | 14.440 | 0.085 | 51 | retrieval_runs_org_query_started_id_page_idx |
| latest parsed created/parser/normalizer/id DESC LIMIT 1 | 19.925 | 0.014 | 1 | document_versions_latest_parsed_page_idx |
| fact version,id LIMIT 10001 | 5.811 | 3.819 | 10001 | financial_facts_version_id_page_idx |
| span version,start,end,id LIMIT 10001 | 37.675 | 4.129 | 10001 | source_spans_version_offsets_id_page_idx |

Each final plan used its named index without Sort. Measurements used the actual
migrated tables, same-entity/org/version distributions and repeated timestamps,
then rolled back benchmark rows. These local timings are characterization,
not a production p95 gate. `test_workspace_keyset_uses_bounded_index_plan`
reproduces the Sort-to-Index-Scan regression on 10,000 rows and asserts that only
51 rows are returned by the scan. Sections and events reuse existing indexes.

`test_large_synthetic_filing_fits_all_document_row_caps` serves a 2 MiB canonical
filing with exactly 2,000 sections, 10,000 spans and 10,000 facts below 32 MiB,
including the last section and verified span. This is offline synthetic capacity
evidence, not proof about the live SEC corpus; oversized real filings retain
explicit error/original-link handling. Provider/live corpus acceptance remains
with its existing issues.

## Query budget accounting

Creation and reruns obtain a transaction-level PostgreSQL advisory lock keyed
by organization. After acquiring it, a single READ COMMITTED statement reads
actual usage plus pending reservations. A successful admission commits the
queued run and an append-only `audit_events` reservation together, then releases
the lock before any provider call. Concurrent API processes therefore see the
committed reservation before admitting more work.

Each `research_query.reserve` audit event names the retrieval run, actual caller,
and configured USD amount at admission. A rerun by a different member reserves
that member's allowance. Pending reservations count across day/month boundaries;
changes to the configured query budget do not resize existing reservations.
The existing audit and run schemas suffice; no public payload or migration
changes are introduced.

Terminal run state and actual reported usage commit in the same transaction.
Their shared snapshot replaces the reservation without either an accounting
gap or double counting. Reported spend is never clipped to the reservation.
If verification or persistence fails after generation, the failure transaction
records the reported spend with the failed run. A failure before reported
provider usage releases the reservation without inventing a charge.

If both persistence attempts fail, the run remains queued and its reservation
continues to consume budget. Idempotent replay returns that run and does not
regenerate or release the reservation. Such interrupted runs require operator
reconciliation; do not expire reservations automatically or classify unconfirmed
provider work as free. This favors a visible stuck run over unrecorded overage.

## Verification

`tests/test_retrieval_costs.py` covers concurrent admission, caller-attributed
reruns, normal metering, and transient/persistent usage-write failures against
PostgreSQL. `tests/test_retrieval_metering.py` checks transaction boundaries and
reported-cost retention without a database. Listing regression tests cover more
than 50 records and temporal filtering; `tests/test_list_contract.py` checks explicit pagination and unchanged array shapes.
`test_pagination`, `test_reader_bounds`, and `test_retrieval_read_bounds` cover
malformed/scope-swapped cursors, full bidirectional history, byte/row overflow,
2,201-event replay, resume, cancellation and mid-stream failure.

Run the repository's Python CI job with migrated PostgreSQL/pgvector and
`FEL_REQUIRE_DB=1`; without `TEST_DATABASE_URL`, database tests are skipped.
Providers remain deterministic mocks. Pricing is configured locally; embedding
usage and enforcement of live-provider generation budgets require their provider
contract work before enabling paid providers. In-process rate limits multiply
with API replica count as documented in `app/ratelimit.py`.
