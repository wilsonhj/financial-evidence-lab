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

September 11 event-ordering verification: PR #283 merged at
2e3f92b13611cc03235c9532eba0ddab67b74f33. Independent review approved exact
head 3dfb542598b1b7c426518920adb1e0fc131d9ba3 after 103 PostgreSQL tests passed
without skips. The new 14-case suite and full 750-test extraction/ontology suite
passed; the original RED checkpoint demonstrated a committed higher ID hiding
a later-committing lower ID from resumed reads. Full local gates passed with
1,936 Python tests, three existing opt-in skips and 463 JavaScript tests. All
seven required checks passed (CI 34654504867, Shared paths 34654504917). Root
recorded explicit lead approval and merged with the reviewed-head guard.
Same-run transaction ordering is verified; old unordered writers must be drained
before relying on it. No stronger queue lease guarantee or hosted rollout is
claimed, and #135 remains open for actual API/browser SSE acceptance.

The refreshed inventory then contained 25 open issues and no other PR. Backend
preflight identified a concrete #61 contract gap: worker normalization intentionally
retains malformed/uncited candidates, but proposal reads required valid financial
payloads and at least one evidence edge. Issue #284 separately owns the reviewed
candidate-display correction under ADR-0024 Amendment 1 before runtime dispatch.
JSON text extracted directly from stored fields preserves unsafe numeric values
without browser rounding. It does not relax strict approval inputs or financial
rules. The wrapper is a display choice, not an inferred validation outcome.

Issue bodies #61/#64 now reference the merged contract prerequisite, #65/#56
name main rather than retired integration history, and #56 clarifies #177's sole
live-ingestion ownership. #191/#201 distinguish merged bounded API/mock gate code
from outstanding real-provider billing and passing live benchmark acceptance.
No canonical task completion or live threshold changed in this reconciliation.

PR #285 merged at f8731e69a1a98a2fe49435effccaeff6fd50e10f after independent
approval of final head 80b9422d5d960455d8c35620991ccda1274cebef and all seven
required checks (CI 34656860298, Shared paths 34656860240). Contract 0.9.0 adds
the read-only candidate-fields projection and permits zero proposal evidence.
The original contract RED had 18 failures; final 66 contract tests and 488 full
JavaScript tests pass with coverage floors intact. Four API version/parity tests
also pass. Independent compiler review exposed required `$defs` metadata in both
candidate and existing financial payload types; actual typed fixture probes now
pass after the narrow generator correction. Its AST regression preserves every
unrelated type and all seven financial variants. Frozen financial schemas,
worker code and migrations are unchanged. Issue #284 is closed; runtime SQL
projection, safe browser rendering and #61/#135 acceptance remain outstanding.

Both registered #61 implementation children are now ready on the merged contract
and event-ordering baseline. The root dispatches API and web work separately,
preserving independent review and final-head CI for each. The parent keeps its
canonical task ownership and waits for combined acceptance. The pending owner
inputs for live credentials/environment/spend, SEC identity and second CODEOWNER
remain unresolved; no paid/provider/hosted request is implied by this dispatch.


September 13 recovery reconciliation: fresh GitHub inspection found main
10d2ca4ab1a6200b0e79c58629a276eac822622c after another agent merged PR287/288
through PR290. PR289's destructive sibling rebuild proposal was closed without
merge; main uses the checksummed non-destructive isolated sibling setup. The
merged integration reports 633 JS and 2,036 Python passes (89.25% coverage),
24 fixture browser passes and the new production-mounted HTTP/worker/browser
acceptance. These are mock-provider/local-CI proofs, not hosted/live gates.

The old local branches are preserved. Their redundant validator cache was never
pushed; equivalent caching is already in main. PR288's recovery-era body was
corrected to its actual merged head711e7b4. PR291 merged at cde9cea after independent approval of74910f7 and149 focused
tests. Lead inspection verified all seven required jobs plus HTTP acceptance
green at that exact head, then explicitly approved and merged with a head guard.

Current-main review identified bounded API peer/adjudication residuals and raw
web patch-text command-member injection. ADR0017 records replacement branches
under the existing #61 child ownership, with non-overlapping paths. The parent
remains open; no canonical task checkbox or milestone gate is changed. Issue292
now tracks production authentication separately, preserving #108's explicit
mock-auth exception. Live environment/spend, provider key choice, SEC identity
and second CODEOWNER inputs remain pending.


PR294 merged at c4ffc2ef4c587fa5732df1c86d5336d25c9d5c40 after independent
approval of1baabdb and28 focused tests,641 full JS tests with unchanged coverage
floors, all seven required jobs and actual HTTP acceptance. Standalone parsing
prevents raw edit/merge text from overriding command action or expected versions
while preserving original numeric text. The web child is now merged; API review
residuals remain active in PR295, so the parent remains open.

Issue135 closed after independent audit of both stated streaming criteria:
mounted same-origin proxy and live async browser delivery. Actual cross-stack
acceptance34742696474 observes queued events before the worker, later review
waiting, and review/terminal events after another browser page submits review.
Forced browser disconnect/reconnect is covered by separate client/proxy and
actual HTTP API tests, not asserted by that cross-stack scenario. Hosted108 and
old-writer draining remain separate conditions; canonical checkboxes unchanged.


PR295 merged at e6e24b064533ab7fa979a1f952ffe47369ca9bf0 after independent
approval of d5d8573, 21 real PostgreSQL tests and four additional edit/merge
controls. Full Python verification passed 2,047 tests with three existing
opt-in skips and 89.28% coverage; all required checks and HTTP acceptance pass.
Unrelated malformed peers no longer block selected valid review; relevant
financial families, explicit groups and unknown identities remain included.
Each conflict records its winning approvals. The proposed correction race
was not reachable through current guarded writers, so no speculative fix landed.

The next six-case actual-API/PG audit showed NaN, Infinity, -Infinity and1e400
returning200 and persisting null, plus canonical/uppercase UUID aliases with
versions2/1 being accepted at version1. The bounded command rejection fix is
registered by ADR0017 under the same #61 API owner. The parent remains open.
The local benchmark preflight passed 100-item approval and both reconnect
checks; its measured series is pinned to e6e24b and is not yet a passing p95
claim. No hosted/provider action or canonical checkbox change is recorded.


September 13 measured local reference acceptance at backend
`e6e24b064533ab7fa979a1f952ffe47369ca9bf0`: one correctness preflight, ten
warmups and 100 sequential measured cycles all passed without retries or
dropped observations. Each cycle creates a fresh tenant/run, uses the real
mounted HTTP API and production queue/durable mock worker, and reviews 100
distinct dated ARR proposals against matching hashed synthetic bytes. One
proposal is worker-produced; 99 are explicit setup clones with recalculated
normalization/validation metadata. Setup and worker execution are outside timing.
All 111 cycles verify 100 accepted version2 proposals, 100 immutable approvals,
source/evidence hashes, a succeeded job at attempt1 and exact reconnect events.

| Operation | p95 ms | Required less than ms | Result |
|---|---:|---:|---|
| Create | 12.451541 | 500 | Pass |
| 100-item review | 550.613459 | 1000 | Pass |
| Waiting-review reconnect | 16.744875 | 2000 | Pass |
| Terminal reconnect | 12.971000 | 2000 | Pass |

The lead independently recalculated the nearest-rank p95 (95th of 100 sorted
samples) from raw integer nanoseconds and inspected the timing/postcondition
code. POST timing includes complete response bytes and transaction commit;
reconnect measures a fresh connection to its first complete eligible durable
SSE frame, not headers/heartbeats. This is one local client, one Uvicorn worker,
6,208 source bytes and a conflict-free workload. It excludes Next/browser
rendering, hosted networking, model latency and worst-case peer/evidence loads.
Existing cross-stack functional tests separately prove later event production.

Machine: Mac16,11, 12 logical CPUs, 24 GiB RAM, macOS26.6.2, Python3.11.16,
PostgreSQL17.10. Durability stayed enabled (fsync/synchronous_commit on),
shared_buffers128MB, normal pool defaults. One-minute host load was3.52 at
start and3.84 at end. The owned API stopped cleanly; isolated synthetic database
and scratch artifacts remain preserved. No production or provider credentials.

Runner SHA256: `efe758e19737fb61fb1b45321f8e05844f204e7d5f6532b0e5e3250158fd8e9d`.
Full cycle artifact SHA256: `ed72d9158e489be26001724403ac40a2f8b40707a1041bd9ba7527faf581d6a8`.
Source SHA256: `sha256:13a2e5130e59ec36b3e9d36fa36fc5e805af22b8f22ac306b476ee1acfc1e2bf`.

<details>
<summary>Raw measured nanoseconds, in sample order</summary>

Columns: create, 100-item review, waiting-review reconnect, terminal reconnect.
Warmups/preflight are excluded from these 100 measured rows.

```jsonl
[9766333,377295458,11735000,11872625]
[10159208,378481208,10591833,11835708]
[10446625,422924708,11977875,12108125]
[9940875,382664916,10290958,11651583]
[11041750,383282291,11236917,12129417]
[10225958,380883209,10582500,12197416]
[10564125,396295750,12228208,12999125]
[10129500,384414083,11221791,12182916]
[9746834,466637584,13638625,12197708]
[11610250,415366458,14280542,11432792]
[10115750,403723666,10225250,10983500]
[15058708,513858916,13199917,14428792]
[11066584,391251625,11280250,11733166]
[10495417,393497333,10753875,10857083]
[10781000,387748708,11848709,11887666]
[9659125,402057625,10681625,11769917]
[9719375,450109041,11992334,12054958]
[9797917,761428625,11486416,12820541]
[10381083,399558208,12356875,10612375]
[9735375,341023000,9533250,11113083]
[7925875,404310625,10001500,11826959]
[9823333,405531667,19310750,11947750]
[9803167,393070583,10574917,12184500]
[9629542,406268125,10954875,11727167]
[9477000,408424583,10898708,11595750]
[9973000,411023875,11829708,11723333]
[9759250,429242875,11790541,11596625]
[9789792,404660625,10369333,11638292]
[9948959,441784250,10574125,11946542]
[10108584,463698375,12694750,10995583]
[10478208,404434541,16662833,11071792]
[10521875,548978959,11664708,11847541]
[9731000,421421291,10436792,11904584]
[9521208,422049500,10606958,12644959]
[10723250,424592416,10301917,12686292]
[10579958,420009750,10608416,11755375]
[10308041,428004708,10593125,11842959]
[9955334,416818334,10936958,11627000]
[9892167,431137625,10694042,11806041]
[10480667,428591542,11829750,11729167]
[10229083,435058000,10485666,11881250]
[9947500,438587583,10520792,11877000]
[10302958,435955250,11767917,12003792]
[9969667,427532375,18619333,11695084]
[9711916,469508208,11987625,14203334]
[12451541,432957042,10705000,11835000]
[9992834,437015000,10578875,12674875]
[10421416,436610000,10751625,11950083]
[10410750,456739167,11276125,12071416]
[10188958,440983791,10477375,11584250]
[10031291,440808875,10680666,11769500]
[10124208,440750250,12569375,11665791]
[9662042,630053917,10549208,12971000]
[13430042,455585625,13560375,11837208]
[10451583,455182792,12312209,11921667]
[10207500,458076292,11538667,11812625]
[10000541,447182500,10177875,11884334]
[9803333,452278458,10407125,11739583]
[9885459,456780041,10708417,12019875]
[9976666,480527708,11463791,12052709]
[10007709,461494916,10248250,11079916]
[10614875,453449334,11904458,10912500]
[11068042,491769917,11285291,10715875]
[10812083,464073208,10576916,11545083]
[10332875,458871417,11785292,11862541]
[10185708,459036167,19101208,11674917]
[10573000,474867209,11147625,12206917]
[10072208,464560625,11432500,11546500]
[10407792,467734833,11595667,10855875]
[10619125,471619250,10281625,15533167]
[21314833,479857333,11353167,11048291]
[10081333,477344750,11638125,11969500]
[10161833,478302333,11114917,12392834]
[10215084,470424792,12013542,12357083]
[10080875,582379208,11758041,11502667]
[10070958,478720584,11632417,11767291]
[10340042,500943416,11846500,11930000]
[10043292,475030125,11909333,11814750]
[9707208,472535375,11453916,11565667]
[9781375,474991959,10514084,11840333]
[9568500,480824041,11362834,11838833]
[9910291,488274167,11657541,10968416]
[10033416,500241542,12249959,12821083]
[10948500,504251250,11518875,12060666]
[10230084,478881833,12079000,12654584]
[10272625,550613459,19358333,12263416]
[8902958,458134875,10442792,10052250]
[8287792,526621458,21111375,10737792]
[10332958,492861209,10633709,12029792]
[9786958,544938291,11283000,11901791]
[12765208,494417625,10684167,11789333]
[9750541,572758625,13537208,12106917]
[11290000,523702917,11011750,11744250]
[10062791,545315625,12031542,12817167]
[17904791,558033916,16744875,11796833]
[10061167,504435500,11350916,12681292]
[10667792,412662792,10420500,11800959]
[11925583,362475500,11455916,11809000]
[10819083,353134250,10756042,13440750]
[10487917,357299084,11027292,11913917]
```

</details>


## September 13 — reader prerequisite and acceptance reconciliation

PR297 merged at 73a7d2bfd9c95a055ba17b412ef659e79855d446 after independent
final-head approval, all seven required checks and HTTP/worker/browser
acceptance. PR298 merged at 3888942848a7aa08d1896eadb76247f85e2ee0ce with
the independently verified local benchmark and command-boundary dispatch.
The sequential local benchmark does not establish the parent specification's
25-user release profile. PR300 owns offline production-auth implementation
after accepted design PR296; no hosted identity acceptance is inferred.

The read-only #96/#87 audit confirms both remain trackers for #108. The new
extraction browser smoke uses SQL-seeded source evidence and one section; it
does not prove ingestion-produced corpus, non-first-section or corruption
screenshots, or hosted operation. Existing API-detected INTEGRITY_ERROR still
becomes generic unavailable in the web source. Dedicated issue #301 and the
reader-integrity plan repair this narrow classification prerequisite. Its
seven-file lane is disjoint from extraction API tests and production auth.
No #108/#96/#87 closure, corpus-pin policy change or canonical checkbox is
authorized by this registration.
