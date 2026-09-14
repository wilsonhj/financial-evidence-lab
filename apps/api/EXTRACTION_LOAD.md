# Extraction HTTP load acceptance (#61)

This opt-in benchmark implements the subordinate extraction specification's
500 ms create, 1,000 ms 100-item review, and 2,000 ms missed-event reconnect
p95 thresholds with 25 active clients. Each wave uses distinct real mock-auth
memberships and isolated tenant/workspace resources. Thresholds are strict;
p95 is nearest rank, including every measured request. Any HTTP error,
timeout, missing sample, failed postcondition, or wave with less than 25
observably overlapping request intervals fails acceptance. No retries occur.

This is a **scaled local synthetic profile**, not the full release profile in
canonical specification §16.1. It cannot certify 100 issuers/eight years,
10 million passages/15 million embeddings, the specified server hardware, or
50 Mbps/50 ms client networking. No hosted or live-model performance is claimed.

## Run

Use the committed locked Python environment and a dedicated, already migrated
local database whose name starts with `fel_load`. Supply its DSN through
`FEL_DATABASE_URL` without logging it. No other worker may consume its queue.
Set `FEL_STORAGE_DIR` to a dedicated writable local directory. Existing data
is retained; unfinished jobs cause refusal. The runner owns one real Uvicorn
process using a socket bound before startup, and shuts it down in `finally`.
It never drops data or changes pool, rate-limit, durability, or financial rules.

```sh
export FEL_AUTH_MODE=mock FEL_ALLOW_MOCK_LLM=1 FEL_WORKER_DB_ROLE=fel_worker
export PYTHONPATH=apps/api:evals:workers/src:packages/providers:packages/ontology:packages/retrieval:packages/retrieval-evals
python -m benchmarks.extraction_load --output /path/to/new/artifact-directory
```

Default: one single-user correctness preflight, one 25-user warmup wave, and
four measured 25-user waves (100 observations for each of four operations).
`--waves` may increase but never decrease the four-wave floor. `--preflight-only`
checks setup only and always exits nonzero because it is not load acceptance.
Use `--port` to select a free local socket (default 8231). No application service
already using that port is contacted. Setup/worker phases precede each timed
review wave. Client timeout is 60 seconds; a timeout remains a failed sample.

## Workload and timing boundaries

The seed creates platform configuration and a 5,699-byte synthetic filing
with 100 explicit dates and matching hashed storage/source-span rows. A
schema-shaped mock reply returns 100 distinct dated ARR proposals. **All 100
are normalized, validated, citation-checked and persisted by the production
queue consumer**; no SQL proposal expansion or approved-row seeding occurs.
The mock's token counts do not estimate a real 100-item model response and
model production is outside measured timing. This is a conflict-free bulk
review workload, not worst-case peer/conflict/model generation performance.

POST timing includes the complete HTTP response, authentication, pool checkout
and transaction commit (a conservative superset of create's auth/connect
exclusion). Independent client creation is before the synchronized barrier;
TCP connection establishment occurs within the timed HTTP request. SSE timing
ends only after receiving the complete expected durable event, not headers or
comments. The cursor is the penultimate committed event, so exactly one event
is pending; the full projected event is compared to PostgreSQL. Waiting-review
and terminal reconnect are measured separately. Clients close streams normally.

Postconditions inspect 100 accepted version-2 proposals, 100 immutable first
approved versions, unchanged source hash and source-run links, pinned corpus,
and a succeeded queue job at attempt 1. Setup and warmup are recorded separately
and excluded from p95. A failed operation retains its wave's observations and
stops dependent workflow stages; missing remaining observations fail the report.

Artifacts: `samples.jsonl` (all request intervals, statuses, actor/run IDs and
verification), `metadata.json` (revision/tree, harness hashes, source counts,
hardware, process/pool/rate-limit settings and PostgreSQL durability),
`report.json` (gates and explicit full-profile false), `server.log` (owned
process). Output directories must be new. No token or DSN is included.
Retain failed baselines; never tune a pool, drop slow samples, or disable rate
limits to relabel a failure. Extraction currently has no rate-limit dependency;
normal configuration stays enabled and unexpected 429s are failures.

Focused report tests:

```sh
python -m pytest apps/api/tests/test_extraction_load_report.py
```

## September 14 local results

All three measured runs completed 100 observations per operation, zero HTTP or
verification errors, and 25-way overlap in every wave. The strict bulk-review
latency gate **remains failed**. None is full reference-profile acceptance.

| Code/workload checkpoint      | Create p95 ms | Bulk review p95 ms | Waiting SSE p95 ms | Terminal SSE p95 ms |
| ----------------------------- | ------------: | -----------------: | -----------------: | ------------------: |
| Original, `4feb4ac`           |        156.22 |        **4147.19** |             152.43 |              115.66 |
| Batched SQL, `0b143ed`        |        131.30 |        **1002.23** |             127.15 |              120.13 |
| Projected bindings, `7df3e67` |        152.48 |        **1501.91** |             218.22 |              284.67 |

These are local macOS 10-CPU / 16-GiB runs against the same disposable PostgreSQL
17 database in Docker with the normal pool maximum of 10, fsync and synchronous
commit enabled. Earlier test data remains in the isolated database. Host load
varied; raw intervals and environment metadata are retained rather than selecting
a favorable run. No API/worker/browser test suite ran alongside the third load
run. Environmental causation is not established by these measurements alone.

The verified SQL repair reduced one 100-item review from 829 to 37 statements.
An isolated profile improved from 759.89 ms to 135.71 ms. Projected identity/head
bindings additionally reduced unnecessary JSON from 396,200 to 25,200 bytes,
without changing immutable financial payloads. Existing atomicity, concurrency,
correction, tenant, ETag and provenance tests pass. This establishes the repair's
behavior and reduced work, not satisfaction of the latency requirement.

Raw samples, reports and profiles: [original baseline](benchmarks/results/2026-09-14-baseline/),
[batched baseline](benchmarks/results/2026-09-14-batched/), and
[projected bindings](benchmarks/results/2026-09-14-projected/).
