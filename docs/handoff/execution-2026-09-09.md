# Backlog execution record — September 9, 2026

Plan: [backlog resolution](../superpowers/plans/2026-09-09-backlog-resolution.md).
Parent specification and canonical task ledger govern; this is issue execution
evidence, not a second task-completion checklist.

Starting revision: a184374. Starting live inventory: 37 issues, zero PRs.
Owner requested implementation of all open issues with parallel agents.
ADR-0017 records the initial dispatch and scope narrowing.

| Issue | Branch | Scope | State | Evidence |
|---|---|---|---|---|
| #248 | agent/test-query-p95-flake | API query test/performance instructions | merged, PR #256 @ 1e6765c | Independent review; real PostgreSQL module 24 passed, 1 deliberate benchmark skip; opt-in local p95 0.052s; all CI passed |
| #230 | agent/test-publish-race-wait | Two named ingestion race test files | merged, PR #255 @ 802d0eb | Independent review caught real-clock test flake; deterministic-clock fix reviewed; warning-removal mutation fails; real PostgreSQL 3 passed; all CI passed |
| #221 | agent/arch-checkpoint-rerun | Extraction source/tests only | PR #257 under independent review | 468 real PostgreSQL extraction tests passed; stale-owner repair race under investigation |
| #137 | agent/137-cutover-hardening | Retrieval API provenance and retrieval/evaluation model guards | dispatched | Reconcile existing refusal/cost/supports behavior before implementing actual residuals |
| #219 | agent/m4-formula-ast | Read-only engine architecture investigation | design preparation | Retain both parent requirements; no canonical edits or implementation before concrete ADR and ownership |
| #188 | agent/188-execution-wave2 | Execution plan and ownership | coordinating | Initial control PR #254 merged @ 2b15032; subsequent paths checked |

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

The remaining 34 issues retain the dependency and closure criteria in the
[complete audit](../research/2026-09-09-open-issue-audit.md). Leaf code completion,
operational rollout and milestone live acceptance are recorded separately.

September 10 dispatch ruling: #137 follows merged #248 and owns only its named
API files plus retrieval/evaluation packages. It does not overlap #221's
extraction subtree or #230's ingestion tests. #219 is read-only design work
until its AST/iteration ADR and canonical task additions are concretely reviewed.
No shared contract or root configuration change is delegated to #137.
