# Backlog execution record — September 9, 2026

Plan: [backlog resolution](../superpowers/plans/2026-09-09-backlog-resolution.md).
Parent specification and canonical task ledger govern; this is issue execution
evidence, not a second task-completion checklist.

September 10 continuation: control PR #258 merged at abc6bcc. PR #257
merged the owner-preserving checkpoint repair at 6c409e8; external PR #260
then removed the unreachable tool layer and corrected the worker-role note at
c16955c. PR #261 merged claims provenance at 29c241c and PR #259 merged
locked runtime installation and heartbeat recovery at 7a69133. The latter
retains hosted restart acceptance under #200. All remote commits are preserved.

Starting revision: a184374. Starting live inventory: 37 issues, zero PRs.
Owner requested implementation of all open issues with parallel agents.
ADR-0017 records the initial dispatch and scope narrowing.

| Issue | Branch | Scope | State | Evidence |
|---|---|---|---|---|
| #248 | agent/test-query-p95-flake | API query test/performance instructions | merged, PR #256 @ 1e6765c | Independent review; real PostgreSQL module 24 passed, 1 deliberate benchmark skip; opt-in local p95 0.052s; all CI passed |
| #230 | agent/test-publish-race-wait | Two named ingestion race test files | merged, PR #255 @ 802d0eb | Independent review caught real-clock test flake; deterministic-clock fix reviewed; warning-removal mutation fails; real PostgreSQL 3 passed; all CI passed |
| #221 | agent/arch-checkpoint-rerun | Extraction source/tests only | merged, PR #257 @ 6c409e8 | Immutable rejected-row CAS preserves concurrent owner; failed-attempt retry durable; independent 479 PostgreSQL tests passed |
| #137 | agent/137-cutover-hardening | Retrieval API provenance and retrieval/evaluation model guards | merged, PR #261 @ 29c241c | Independent review verified provenance through rollback failure; current CI passed; issue closed |
| #219 | agent/m4-formula-ast | Calculation engine, ADR-0018 and canonical task additions | design accepted for implementation | Restricted typed formula AST; explicit bounded Jacobi groups, caller-specified seeds/tolerances, immutable group provenance; no parent scope deferral |
| #200 | agent/200-locked-runtime | Runtime packaging, locks and health/recovery | code merged, PR #259 @ 7a69133; hosted acceptance pending | Independent clean install, all packaged assets, 50 focused PostgreSQL tests and current CI passed; watchdog exits and local supervisor relaunch proved |
| #194 | claude/close-trailing-acceptance-gaps | Remove unreachable extraction tool layer | merged, PR #260 @ c16955c | Independent code review and full PostgreSQL extraction suite passed; worker-role adoption remains #190 |
| #153 | agent/153-unit-policy | Ontology-owned comparison policy and extraction checks | design accepted for implementation | ADR-0019; preserve payload spelling, version conflict grouping, require fresh version-pinned runs |
| #190 | agent/190-worker-role-rollout | Committed Railway role selection | code merged, PR #265 @ 65f7159 | Independent 47 PostgreSQL tests and exact restricted-login startup checks passed; hosted verification pending |
| #203 | agent/203-ci-observability | Coverage floors, required checks, browser cache, deployed Sentry package | dispatched | Measure current source coverage before setting floors; real reviewer staffing and hosted telemetry remain explicit |
| #188 | agent/188-execution-wave4 | Execution plan and ownership | coordinating | Initial control PR #254 merged @ 2b15032; subsequent paths checked |

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
