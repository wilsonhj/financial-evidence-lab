# ADR-0017: Bounded parallel backlog execution

Status: Accepted for execution under the owner's September 9 instruction

Date: 2026-09-09

Occasioned by: #188 and the merged backlog plan in PR #251

## Authorization and scope

The repository owner explicitly requested: "create and implement a plan to
resolve all open issues in this repo in parallel with /agent-teams
/dispatching-parallel-agents". This record makes that dispatch concrete. It
implements the requested parallel scheduling within the existing four-agent
limit; it does not authorize a new product requirement or waive a release gate.

The initial ready work is #248, #230 and #221. Dependencies for all three are
already merged. Their existing broad test-path claims are narrowed to the
actual files/subtrees in workstreams.yaml, so ingestion tests and extraction
checkpoint tests can execute concurrently without sharing a conftest or helper.
Their registered branches are retained. One coordinator owns only this
execution record and shared-path scheduling. Every issue retains its own PR.

## Decisions

- Cap concurrency at three implementers plus the coordinator. Serialize merges
  and overlapping paths, contracts, migrations and root configuration changes.
- Start #248 in the named API test files; #230 in the named ingestion race test
  files; #221 in extraction source and extraction test subtrees. Shared test
  fixture edits require rescheduling or explicit narrowing before implementation.
- Use real isolated local/CI PostgreSQL for durable-state proofs; localhost
  synthetic test identities are not deployed credentials. Never point tests at
  a production database.
- Preserve #230's warning-on-timeout behavior; #248 keeps a separately invoked
  performance measurement while default tests check operation/query invariants.
- #221 repairs the migration-0006 row output/hash checkpoint atomically, not
  the obsolete event-payload checkpoint design. Existing immutable identity,
  fencing and terminal-state rules remain binding.
- Execute subsequent issues from the merged plan when their prerequisite and
  path checks pass. Record concrete rulings and ownership before each dispatch.
  No canonical task checkbox is changed by an implementer.

## Limits and verification

This scheduling decision authorizes implementation and the normal reviewed PR
integration requested in this session. It does not by itself accept a provider
substitution, change numerical financial semantics, permit destructive data
operations, authorize an unknown paid-provider budget, or certify a live gate.
Those requirements must be satisfied explicitly by their owning issues.

Each behavioral fix requires demonstrated regression failure before the fix,
focused passing tests, independent review and current required CI. The control
PR validates unique workstream IDs, resolved acyclic dependencies and pairwise
non-overlap of the dispatched paths. Durable completion evidence lives in
GitHub and the execution record, separate from the canonical task ledger.


#196 extraction ruling: after #154 merges, narrow the existing refactor dispatch
to the exact workflow/stage/checkpoint/store modules in workstreams.yaml. Keep
all tests/goldens, financial logic, hashes, version pins and SQL unchanged.
Preserve workflow-global crash/hash hooks and persistence ownership patching.
The existing 510-line accounting validator is within the issue's approximate
500-line target and stays unchanged. API retrieval remains excluded until
#191 merges and the lead registers that portion. This split alone cannot close
#196. The lead may publish its bounded plan and reconcile verified branch
protection settings in .github/required-checks.md within the control PR.


Wave 7 ruling: #196's extraction portion is verified and merged; register its
remaining API portion separately, blocked until #191 merges and a concrete
split design narrows ownership. #197's hygiene/design issue is closed after
PR #275; feature-owned table implementation remains #64/#66/#68. Authorize the
single #191 legacy-51-run regression update in test_retrieval_costs.py without
changing metering expectations. Register #81 dataset-only recovery as blocked:
its historical source is available, but fresh byte verification, original
acceptance debt and fetched supplemental discovery remain. No SEC request uses
the historical contact without a current approved FEL_SEC_USER_AGENT.


Wave 8 ruling: PR #272 merged at fa4cfa2 after independent final-head approval,
local PostgreSQL regressions and all required CI. Register #196's remaining API
split in exactly retrieval.py and four named helper files. Preserve tests, SQL,
route signatures and per-call patch lookups; no main, reader or pagination edits.
GitHub closed #196 independently before this API work; retain the closure while
finishing its recorded acceptance scope. The approximate 500-line target permits
a small (~550-line) facade when another abstraction would reduce clarity.
All PRs require independent review, tests and an explicit approval decision
before merge, as reiterated by the owner on September 10 local time.

Split #81's independently feasible offline restoration from its blocked SEC
network phase. Authorize exactly six dataset files: original manifest and MIT
notice, sanitized provisional documentation, a standard-library structural
validator and tests. No contact identity, fetched filing, supplemental selection
or verified feature is inferred. Default validation must report unavailable
full acceptance; explicit structural mode never claims acceptance. The network
phase depends on this restoration and retains its current-identity/evidence hold.

#196 measured implementation ruling: the integration lead accepts the 615-line
retrieval facade, above the plan's approximately 550-line estimate. Explicit
compatibility exports and seven unchanged HTTP signatures retain the existing
transaction, metering and lazy SSE patch boundaries; the four helper modules
measure 243–417 lines. Further splitting would add indirection around those
boundaries. This is a measured size exception only: unchanged tests, SQL,
route signatures and runtime patch proofs remain required, together with
independent review, explicit approval and final-head CI before merge.

Wave 9 ruling: PR #280 supplies accepted ADR-0024, contract 0.8.0 and migration
0011 at c105f1b. Close its prerequisite issue only; preserve all #61/#135 and
live acceptance work. A concrete event-store race allocates a lower event ID
in an uncommitted checkpoint transaction while a later standalone run-start
event commits. An ID-based reconnect can then miss the lower event. Register
a narrow #135 writer-ordering prerequisite before backend/web dispatch. Acquire
the per-run transaction lock before identity allocation and before earlier
child writes in the two atomic persistence methods; avoid SHARE-to-exclusive
lock upgrades and keep locks out of model execution. Preserve event IDs, schema,
financial hashes and existing terminal guards. Test real PostgreSQL concurrency.

Split #61 implementation into disjoint API and web child packages after that
prerequisite merges. The existing M3-REVIEW entry retains canonical task IDs and
becomes combined acceptance only, with no overlapping implementation paths.
Authorize only extraction planned-marker removal in root/reference OpenAPI with
the backend router mount; keep strict parity tests. This is implementation
status alignment under ADR-0024, not a new contract shape or version. The
permissions projection is already frozen in #280. No provider, credential,
financial semantics, live release gate or canonical checkbox changes here.

Preserve the independent #64 model/scenario research as a non-binding note.
Its scalar eligibility, unit/period, historical evidence and scenario-layer
questions require resolution before that feature's contract freeze. Publication
does not select those policies or clear #61/#62 prerequisites.
