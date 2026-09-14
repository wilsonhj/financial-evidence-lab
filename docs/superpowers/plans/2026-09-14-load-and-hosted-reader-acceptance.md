# Extraction load and hosted reader acceptance

Parent: `specs/001-financial-evidence-lab/spec.md` (especially §16.1), the
existing canonical task ledger, `specs/003-agentic-extraction/spec.md`,
accepted ADR-0024, and issue #108's accepted July 21 design addendum.
Those sources govern; this plan neither changes a gate nor declares a task done.

## Outcome and authorization

The September 14 owner request authorizes implementing and exercising #61's
load acceptance and #108's real worker-to-hosted-reader smoke. The integration
lead releases the bounded offline implementation below. Hosted execution waits
for an identified dedicated smoke environment and available credentials; no
existing shared or production service may be stopped as a substitute.

Use the existing Python/Next/PostgreSQL stack and locked dependencies. Keep the
original user worktree intact. Each issue has its own implementation branch.
No schema, financial formula, threshold, canonical checkbox or production
identity policy changes are part of this plan.

## Decisions

1. Reuse a real HTTP API and PostgreSQL for load rather than in-process route
   calls: include full response/commit and first complete durable SSE frame.
   This costs more test time but observes queues and connection contention.
2. Start with a reproducible scaled 25-user profile, which §16.1 permits for CI.
   Preserve the full release profile as a separate unproven result unless its
   corpus, hardware and network requirements are actually supplied. Never close
   #61 unconditionally on a scaled result or relabel sequential samples.
3. For #108 follow the accepted fixture SEC transport and colocated worker/API
   design, rather than add remote storage or seed evidence with SQL. Platform
   org/membership/workspace bootstrap and queue insertion are allowed. Corpus
   publication calls existing production pipeline helpers after real ingestion.
4. Retain the explicitly authorized mock-auth smoke environment. No new
   identity implementation or paid model request is needed.
5. The consumer currently drops explicit reporting periods. Add a separately
   tested, bounded pass-through of an optional validated date pair in filing
   jobs; the committed fixture manifest supplies the pair. Do not infer a period
   from arbitrary comparative XBRL contexts or update evidence columns by SQL.
6. Worker process exit zero alone is insufficient: inspect expected jobs and
   ingestions before starting the API. Reject failed/quarantined/missing work.

## #61 measurable proof

- Default run: 25 distinct authenticated users, independent scoped resources,
  one preflight, separately identified warmup and at least four measured waves
  (100 observations per operation). Synchronize wave starts and retain request
  start/end times and observed overlap. Insufficient concurrency is a failure.
- Operations: create a run; atomically approve exactly 100 proposals; resume
  SSE from a known event and receive the next complete eligible durable frame.
  Targets are nearest-rank p95 strictly below 500/1000/2000 ms respectively.
- Use normal application configuration and record pool/process/durability
  settings, hardware, fixture size and code/tree hashes. Do not silently enlarge
  pools, reduce batch size, retry requests, omit errors or discard slow samples.
- Setup is outside timing; disclose every synthetic seed and proposal expansion.
  Never pre-seed approved records. Confirm durable jobs, 100 versioned approvals,
  matching evidence and exact resumed events after measured requests.
- Emit machine-readable samples and a human-readable report; nonzero exit on
  errors, missing observations, postcondition failures or latency failures.
  A failing baseline is evidence for systematic diagnosis, not a passing gate.

## #108 acceptance matrix

| Requirement                                 | Evidence                                                                                                                            |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Committed filing → real worker → PostgreSQL | Exact committed transport bytes, real consumer process, successful jobs and ingestion rows; no SQL evidence writes                  |
| Production reader via authenticated HTTP    | Real Next build, HTTP runtime configuration, actual reader endpoint                                                                 |
| Valid non-first-section citation            | Exact verified canonical text selected; screenshot and source/hash record                                                           |
| Corrupt storage fails closed                | Flip one canonical blob byte, API INTEGRITY_ERROR, browser alert without verified quote; screenshot; restore in finally             |
| Future/missing anti-oracle                  | Same API 404 envelope and equivalent browser not-found result                                                                       |
| Pinned/unpinned/repeated selection          | Explicit version/cutoff/pin queries, including empty corpus pin; compare returned IDs and scope                                     |
| Terminal amendment authority                | At least two amendments with explicit reporting periods; load complete related history and inspect terminal linkage                 |
| Auth and outage failures                    | Real missing/invalid token and denied membership; typed 401/403; real service outage and recovery, report actual observed 5xx codes |
| Hosted execution                            | Dedicated Railway API/storage plus web services; capture URLs, deployed revision, logs, traces, screenshots and artifact digests    |

Local smoke exercises the same implementation before deployment but does not
satisfy the final hosted row. Do not claim a platform-generated 503 if only 502
was observed. No product middleware may fake the outage. Fault injection and
service stop/start must be limited to the dedicated smoke target and restored
even after assertion failure.

## Implementation order and ownership

1. Lead (#188, `agent/188-load-reader-plan`): publish this plan and bounded
   workstream registration; independent review and `contract-change` label.
2. #61 (`agent/61-load-acceptance`):
   `apps/api/benchmarks/extraction_load.py`, support files in that directory,
   `apps/api/tests/test_extraction_load_report.py`, and
   `apps/api/EXTRACTION_LOAD.md`. Test report statistics/concurrency/error gates,
   run against isolated migrated PostgreSQL and real Uvicorn; retain baseline.
3. #108 worker subtask (`test/reader-prod-smoke`, disjoint owner):
   `workers/src/fel_workers/ingestion/fixture_sec_client.py`,
   `workers/src/fel_workers/__main__.py`, `workers/src/fel_workers/consumer.py`,
   and their focused tests. RED→GREEN for exact bytes/no network fallback,
   missing/hash-mismatched/traversing files, mutually exclusive strict mode
   flags, required fixture/storage paths, and reporting-period pass-through.
4. #108 lead subtask (same issue branch, disjoint files): committed
   `evals/datasets/reader-prod-smoke/**`; `evals/harness/reader_prod_smoke*.py`;
   `evals/tests/test_reader_prod_smoke.py`; real browser acceptance/config under
   `apps/web`; a `workflow_dispatch`-only
   `.github/workflows/reader-prod-smoke.yml` under the existing named exception.
   Bootstrap platform state, enqueue filings, run consumer, inspect outcomes,
   publish through existing helpers, emit a secret-free manifest, start API.
5. Independently review both implementations and run focused/full CI plus the
   existing extraction HTTP workflow. Diagnose any reproduced product defect in
   a specifically authorized scope; do not weaken assertions to get a pass.
6. Execute local 25-user and real-ingestion/browser proofs. Archive all raw
   measurements, failures and digests with an honest environment description.
7. Once dedicated hosted access exists, deploy reviewed code and perform #108's
   real hosted flow and controlled fault/recovery sequence. Protected environment
   secrets supply credentials; never print tokens, DSNs, raw auth headers or
   unsanitized HAR files. Publish artifact links and a small evidence digest.
8. Lead audits criteria against actual results. Issue closure/canonical task
   changes require sufficient evidence; unavailable hosted access or an unmet
   reference-profile/load gate remains explicitly outstanding.

## Initial access inventory

At planning time no Railway CLI/login, FEL/RAILWAY environment variables or
GitHub repository/environment secrets were available. The Supabase connector
requires reauthentication. Existing GitHub environments are Preview/Production,
without protection rules; neither is assumed to be a disposable smoke target.
The owner has been asked for the dedicated target names and access method,
without requesting credential values in chat. Implementation and local proof
can proceed while hosted access is resolved.

## Measured baseline and bounded performance repair

The unchanged 25-user baseline at load runner commit `4feb4ac` completed all
100 observations per operation without errors and with 25-way overlap.
Create p95 was 156.22 ms, waiting reconnect 152.43 ms and terminal reconnect
115.66 ms. Bulk review p95 was 4147.19 ms and **failed** the 1000 ms gate.
The raw baseline remains retained; it must not be replaced by a later pass.

Profiling a 100-item review reproduced 829 SQL statements, consuming 704.93 ms
of 759.89 ms total. Initial approvals account for 500 statements, proposal and
evidence loading 201, and individual proposal updates 100. Deterministic
validation took 14.68 ms. The integration lead authorizes bounded batching in
`apps/api/app/extraction/review.py` and `approved.py` plus a meaningful query
budget regression in `apps/api/tests/extraction/test_review_query_budget.py`.
Preserve tenant predicates, ordered locks, transaction boundaries, immutable
history, evidence verification, ETags, limits and financial rules. Run existing
atomicity, concurrency, correction and tenant tests before repeating the same
load profile. Pool sizing, thresholds and workload remain unchanged.

The real reader fixture smoke can exercise only one derived version per
accession with the current parser/normalizer release. A repeated identical
job is a no-op and changed raw bytes are quarantined. Do not fabricate a
parser-version override or insert evidence rows to claim competing-version
selection. Corpus membership, explicit existing version selection and repeats
are exercised now; competing derived-version acceptance remains unverified
until a genuine parser/normalizer release exists.
