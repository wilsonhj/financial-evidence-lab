# API hardening and compatibility

PR #232 addresses query admission and accounting (T0008), connection reuse,
and per-organization rate limiting. It preserves the frozen listing and reader
behavior; OpenAPI 0.5.0 declares only the 402 and 429 responses this PR serves.
The proposed `limit` parameters, truncation, and
reader overflow responses are deferred with #191 to a coordinated pagination,
contract, and web-client change. Complete filing/workspace/run discovery remains
available, including records beyond the former 50-row default and 200-row cap.

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
than 50 records and temporal filtering; `tests/test_list_contract.py` prevents
reintroducing the undeclared parameters.

Run the repository's Python CI job with migrated PostgreSQL/pgvector and
`FEL_REQUIRE_DB=1`; without `TEST_DATABASE_URL`, database tests are skipped.
Providers remain deterministic mocks. Pricing is configured locally; embedding
usage and enforcement of live-provider generation budgets require their provider
contract work before enabling paid providers. In-process rate limits multiply
with API replica count as documented in `app/ratelimit.py`.
