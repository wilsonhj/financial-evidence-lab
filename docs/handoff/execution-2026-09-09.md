# Backlog execution record — September 9, 2026

Plan: [backlog resolution](../superpowers/plans/2026-09-09-backlog-resolution.md).
Parent specification and canonical task ledger govern; this is issue execution
evidence, not a second task-completion checklist.

September 10 continuation: control PR #258 merged at abc6bcc. PR #257
merged the owner-preserving checkpoint repair at 6c409e8; external PR #260
then removed the unreachable tool layer and corrected the worker-role note at
c16955c. PR #261 merged claims provenance at 29c241c and PR #259 merged
locked runtime installation and heartbeat recovery at 7a69133. The latter
retains hosted restart verification under live cutover; #200 was subsequently closed in GitHub. All remote commits are preserved.

Starting revision: a184374. Starting live inventory: 37 issues, zero PRs.
Owner requested implementation of all open issues with parallel agents.
ADR-0017 records the initial dispatch and scope narrowing.

| Issue | Branch | Scope | State | Evidence |
|---|---|---|---|---|
| #248 | agent/test-query-p95-flake | API query test/performance instructions | merged, PR #256 @ 1e6765c | Independent review; real PostgreSQL module 24 passed, 1 deliberate benchmark skip; opt-in local p95 0.052s; all CI passed |
| #230 | agent/test-publish-race-wait | Two named ingestion race test files | merged, PR #255 @ 802d0eb | Independent review caught real-clock test flake; deterministic-clock fix reviewed; warning-removal mutation fails; real PostgreSQL 3 passed; all CI passed |
| #221 | agent/arch-checkpoint-rerun | Extraction source/tests only | merged, PR #257 @ 6c409e8 | Immutable rejected-row CAS preserves concurrent owner; failed-attempt retry durable; independent 479 PostgreSQL tests passed |
| #137 | agent/137-cutover-hardening | Retrieval API provenance and retrieval/evaluation model guards | merged, PR #261 @ 29c241c | Independent review verified provenance through rollback failure; current CI passed; issue closed |
| #219 | agent/m4-formula-ast | Calculation engine, ADR-0018 and canonical task additions | merged, PR #262 @ dff71f0 | Independent 233 tests including local benchmarks; legacy golden hashes and SCC oracle verified; final CI passed |
| #200 | agent/200-locked-runtime | Runtime packaging, locks and health/recovery | code merged, PR #259 @ 7a69133; hosted acceptance pending | Independent clean install, all packaged assets, 50 focused PostgreSQL tests and current CI passed; watchdog exits and local supervisor relaunch proved |
| #194 | claude/close-trailing-acceptance-gaps | Remove unreachable extraction tool layer | merged, PR #260 @ c16955c | Independent code review and full PostgreSQL extraction suite passed; worker-role adoption remains #190 |
| #153 | agent/153-unit-policy | Ontology-owned comparison policy and extraction checks | merged, PR #264 @ 54cad9a | Independent 657 PostgreSQL-enabled tests, wheel import and SIX vocabulary verified; final CI passed |
| #190 | agent/190-worker-role-rollout | Committed Railway role selection | code merged, PR #265 @ 65f7159 | Independent 47 PostgreSQL tests and exact restricted-login startup checks passed; hosted verification pending |
| #203 | agent/203-ci-observability | Coverage floors, required checks, browser cache, deployed Sentry package | merged, PR #269 @ c7b2d0c | 1778 Python tests and 419 JS tests passed; negative coverage probes fail; SDK privacy verified; seven strict admin-enforced required checks applied and read back; real reviewer staffing and hosted telemetry remain |
| #266 | agent/266-terminal-schedule-test | Test database-clock invariant | merged, PR #267 @ 41857d2 | Independent 17 PostgreSQL tests, regression mutation and final CI passed |
| #154 | agent/154-guidance-range-ordering | Signed guidance ordering and universal range validation | merged, PR #270 @ 3fbc8ac | 720 PostgreSQL-enabled source tests; independent 141 tests, 1681 endpoint combinations, final CI passed; issue closed |
| #191 | agent/191-pagination-reader | Bounded API reads and coordinated web consumers | active, PR #272 | Backend and web agents share one worktree with disjoint file ownership; adversarial and integration checks pending |
| #196 | agent/arch-complexity-split | Extraction control/stages/checkpoints/stores | extraction merged, PR #274 @ 5e0bf99 | 1112 full worker/ontology/provider tests, independent 208 PostgreSQL tests and 64 global bindings; unchanged tests/goldens/SQL; API portion waits for #191 |
| #197 | agent/197-data-model-design | Canonical model/forecast/export storage sketch | merged, PR #275 @ 05d85d8; issue closed | Existing 0009 PostgreSQL harness and independent design/231 engine tests passed; historical missed ordering disclosed; table implementation stays #64/#66/#68 |
| #81 | agent/81-sec-fixture-recovery | Historical fixture recovery and supplemental SEC discovery | blocked after read-only recovery design | Final d8fd80e has 60 rows/7 asserted features; no committed validator/bytes/receipts. Current SEC contact identity requested; no fetches or new byte verification |
| #188 | agent/188-execution-wave7 | Execution plan and ownership | coordinating | Initial control PR #254 merged @ 2b15032; subsequent paths checked |

Ruling: narrow #230 and #221 test ownership — their original workers/tests/**
globs overlapped, while the required implementation is separable — any shared
fixture need forces serialization rather than concurrent edits.

Ruling: retain #230's warning-first timeout semantics — that is the issue's
accepted behavior — hard failure would need changed acceptance and could
reintroduce host-load flakiness.

Ruling: use the accepted OpenAI baseline for future adapter preparation unless
an evidence-backed substitution is accepted — the Proposed ADR-0012 is not an
active provider decision — this avoids unnecessary multi-vendor work.

Live-environment prerequisite: approved environment/secret locations and total
provider-spend cap requested from the owner, names/locations only. Offline
implementation continues; no paid call or hosted mutation is justified by an
unanswered question.

Other issues retain the dependency and closure criteria in the
[complete audit](../research/2026-09-09-open-issue-audit.md). Leaf code completion,
operational rollout and milestone live acceptance are recorded separately.

September 10 dispatch ruling: #137 follows merged #248 and owns only its named
API files plus retrieval/evaluation packages. It does not overlap #221's
extraction subtree or #230's ingestion tests. #219 is read-only design work
until its AST/iteration ADR and canonical task additions are concretely reviewed.
No shared contract or root configuration change is delegated to #137.

#200 ruling: generate hash-verified runtime/dev locks from the first-party
dependency closure, install/audit that closure, and prove clean runtime builds
exclude developer tools. Record the owner's implementation authorization on
its contract-change PR. Railway probes health only during deployment; stalled
heartbeat restart needs a watchdog/recovery proof that tolerates legitimate
long-running jobs. No paid rollout is authorized by this scheduling record.

#221 review confirmed the stale-owner overwrite can be fixed entirely in
extraction checkpoint persistence using compare-and-swap. Consumer source and
its named test file are therefore assigned to #200 for heartbeat observation;
they remain disjoint from #221's extraction subtrees. #200 must not alter queue
claim/fencing semantics when observing successful lease heartbeats.

#219 design ruling: retain both §8.5 clauses. Record concrete grammar, bounded
Jacobi iteration and group provenance mechanics in ADR-0018; add T0411/T0412
unchecked in the canonical ledger, then implement. Existing Decimal precision,
units, cutoff rules and legacy graph identities remain binding. The narrow
workstreams edit in that PR only maps those two new task IDs; the coordinator
does not edit this file concurrently while that mapping is prepared.

#153 ruling: use one ASCII-guarded explicit unit vocabulary at comparison
boundaries, preserving raw payload spelling and distinct unknown/Unicode units.
Namespace new conflict grouping; never rewrite historical adjudication. Version
new extraction runs and enforce the version before checkpoint recovery so old
validation cannot silently satisfy the new policy. ADR-0019 records the exact
policy and compatibility boundary. Do not broaden unrelated unit-family
validation or currency-field syntax, or change #154's guidance ordering here.

#190 residual ruling: after #200 merges, select the existing `fel_worker` role
in the Railway worker start command, keeping migration checks in their separate
pre-deploy process. Verify the exact command and effective worker role locally,
including forbidden deletion/DDL. Do not change role grants or the optional
local development switch. Configuration merge alone does not prove an existing
hosted process has adopted the role; record that acceptance separately.

The old worker sources cite ADR-0013, but that number belongs to canonical
ledger reconciliation on main. ADR-0020 records the rollout decision without
rewriting immutable migration 0008 or misattributing the historical decision.

#203 residual ruling: both Sentry initialization paths are on main. Enable
measured Python/JS coverage floors at the baseline minus one percentage point,
including unimported source files; prove a coverage regression fails. Register
all current required CI check names and inspect existing repository settings
before any application. Implement the requested version-keyed browser cache
without skipping OS dependency installation; permit one CI-only retry with
trace evidence. Install the Sentry SDK in the locked runtime closure and align
worker automatic data collection with the accepted API privacy settings. No
DSN means no initialization. No additional CODEOWNER may be invented, and
hosted telemetry acceptance requires the approved environment. Root config and
lock changes are narrowly authorized for this issue; no contracts or numerical
semantics change. These paths do not overlap #153 or #219 implementation.

#266 test-only ruling: #203's real PostgreSQL baseline reproduced the terminal
failure test's database/host clock comparison (133 ms skew). Assert `available_at` equals the same-statement
`finished_at` on terminal failure instead, proving zero retry delay. Preserve production
queue code and existing status/finished-time checks. The single test file is
disjoint from #153 extraction tests and #203 health tests.

#154 ruling: canonicalize only `high < low < 0` after existing numeric parsing
and scale reconciliation. Apply strict range validation independently of ontology
membership. Preserve source wording, signed magnitudes, sign blockers and
point/floor/ceiling semantics. Positive, cross-zero and zero-to-negative inverted
bounds stay reviewable errors. Advance the workflow/normalizer/validator pins
and conflict namespace; reject old runs before recovery and never rewrite their
payloads or adjudication. Accepted ADR-0022 precedes implementation. The scope
is disjoint from #203's worker entrypoint and health tests.

The integration lead verified the merged #219 leaf implementation and updates
only the corresponding canonical checkbox/annotation state. The concurrent-user
performance acceptance and remaining M4 milestone gates are not inferred from
local engine tests.

#191 residual ruling: ADR-0021 accepts explicit bounded page mode with complete
legacy success or a declared pagination-required error, preserving array shapes
and shipping the actual web consumers together. Reader/trace evidence stays
complete within each declared scope or returns an explicit size error; no
clipped success or false whole-history conclusion. SSE replays all events in
bounded batches. Cursor data is strictly typed and scope-bound continuation,
never authorization; every page reapplies tenancy/cutoff/pin gates. No new
cursor signing secret is needed for this continuation-only contract. Pin-based
comparison is distinguished from mutable browsing. API observability source
and tests remain owned by #203; reuse existing request telemetry. Reserve only
index migration 0010 under this ADR, retaining only indexes supported by query
plans. Provider metering remains explicitly tracked under #195.


September 10 reconciliation: GitHub shows #190 and #200 closed at 22:52 UTC.
Their code and local acceptance were verified; no hosted adoption or restart is
inferred from their closure. Keep those operational checks in #177/#108's live
cutover, which still requires the approved environment. The current inventory
after #270 is 27 open issues and PR #272.

#196 extraction ruling: dispatch the [mechanical split plan](../superpowers/plans/2026-09-10-extraction-complexity-split.md)
from merged #154. Retain workflow's hash construction and runtime patch lookups,
and persist's ownership lookup. Bound both workflow.py and persist.py; leave
tests, financial modules, versions, SQL and event order unchanged. The existing
510-line accounting validator satisfies the approximate 500-line target and
stays untouched. API retrieval is explicitly excluded until #191 merges; this
portion alone cannot close #196.

#195 remains held at the installed OpenAI credential skill's mandatory initial
key decision. No key was found in process/conventional environment locations;
reuse/provision versus secure creation was requested, with no answer yet. No
API-dependent design, code or smoke test has been undertaken after this gate.
Second CODEOWNER identity and approved live environment/spend cap also remain
unanswered. Independent offline work continues.


#191 bounded test-path ruling: the full PostgreSQL suite found the existing
`test_query_snapshot_keeps_every_run` in `test_retrieval_costs.py` assumes a
51-run legacy success. Authorize only its request/expectation update: the
unpaged call must return PAGINATION_REQUIRED, then an explicit page must retain
all 51 runs. Preserve the metering assertions and all other cost tests. This
single test path is disjoint from the parallel web coverage work.

#81 recovery finding: PR #76's final three dataset blobs at d8fd80e exist only
on retired integration history, not main. Restoring that source requires its
MIT notice and explicit provisional provenance. No fetcher, validator, full
byte cache or receipt log was recovered. Historical labels do not establish
fresh verification. Original validation/excerpt/amendment debt precedes the
required 3–6 supplemental issuers and >=8 byte-verified feature gate. The
approved current FEL_SEC_USER_AGENT is missing; the owner was asked for the
application/contact identity. No historical personal identity was adopted and
no SEC request was made. A blocked dataset-only dispatch records this work.


September 11 UTC: PR #272 merged at fa4cfa2eb03865471bd9d29bf8016cf825a4c71f.
Independent review approved exact head e590bc94134720407726e59cac2519416e1f2adf
after eight final PostgreSQL regressions passed; lead approval and final CI
links are recorded in the PR. All seven required checks and preview passed.
Earlier full verification included 1,898 Python and 457 JavaScript tests with
unchanged coverage floors. No actual provider billing or hosted gate is claimed.

The live inventory before this merge contained 25 open issues and only PR #272.
GitHub had closed #196 at 00:18 UTC without an API implementation; its remaining
five-file split stays in the plan, with administrative closure preserved.
The [retrieval split plan](../superpowers/plans/2026-09-10-retrieval-complexity-split.md)
keeps all seven router endpoints and runtime patch behavior stable, with tests,
goldens, financial calculations and SQL unchanged. Independent review and final
required CI gate its merge. #61 remains blocked pending its concrete contract
and persistence decision, not by API path contention once this scope is narrowed.

#81 offline ruling: restore the exact final manifest and source MIT notice,
replace historical documentation to omit its personal contact and unverified
claims, and add an explicitly scoped structural validator. This work needs no
SEC identity or network. The [six-file plan](../superpowers/plans/2026-09-10-sec-fixture-offline-restoration.md)
requires default full-acceptance failure, verified_feature_count=0 and honest
labels for the seven historical assertions. Its focused unittest suite must
run explicitly on the final head because current pytest discovery excludes
this dataset path. Fresh byte/feature/excerpt/amendment and supplemental
acceptance remains blocked separately; #81 stays open.

September 11 continuation: PR #279 merged at
2541d66d2d7aa4ff8cca9628531191375da78340 after independent review,
explicit approval, ten offline test methods and all required checks. It restores
60 historical records covering 20 issuers, with seven asserted feature tags and
zero freshly verified features. The full validator deliberately refuses to
certify acceptance. Issue #81 remains open for current SEC identity and evidence.

PR #281 merged at f16ea050f4172db1eff949f7377d5c3a0a6079af after independent
approval of final head f30a5ad31031fdb634d3f21d2949f01955ef6477 and all seven
required checks. The API split preserves 47 definition ASTs, 41 SQL constants,
263 runtime bindings, full OpenAPI and all seven retrieval route dependencies.
Independent verification passed 59 tests with one existing opt-in timing skip.
ADR-0017 records the measured 615-line facade exception; four helpers remain
243–417 lines. This completes the API portion retained after GitHub closed #196.

PR #280 merged at c105f1b594097dbb4da0123134eff853cb8850d1 after independent
approval of final head 0bb237bc03ea6505708e27c3998173ad3c340736 and all seven
required checks. The reviewer verified 60 PostgreSQL tests, 41 contract tests
and 13 permissions schema cases. Lead checks include 736 extraction/ontology
tests, fresh migration installation, a legacy-row-preserving 0010 upgrade and
backup/restore with SQL guards. Earlier full CI measured 1,922 Python passes,
three existing skips and 90.07% coverage; final contract-only delta passed the
same required CI. Issue #278 is closed; no #61/#135 or live completion is inferred.

The next control wave registers the independently reproduced #135 event
commit-order gap as a four-file worker/test prerequisite. A checkpoint event
can receive an ID before commit while a later standalone event commits; a
reader resuming after the larger ID then misses the earlier one. Run locks
must precede event allocation and earlier child writes in atomic transactions.
Independent PostgreSQL probes reproduced the late lock-upgrade deadlock and
verified early locking. This does not claim to solve broader worker lease or
terminal lifecycle questions. The bounded plan and disjoint #61 API/web plans
govern subsequent dispatch; canonical tasks and live gates remain unchanged.
