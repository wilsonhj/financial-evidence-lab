# Backlog execution record — September 9, 2026

Plan: [backlog resolution](../superpowers/plans/2026-09-09-backlog-resolution.md).
Parent specification and canonical task ledger govern; this is issue execution
evidence, not a second task-completion checklist.

Starting revision: a184374. Starting live inventory: 37 issues, zero PRs.
Owner requested implementation of all open issues with parallel agents.
ADR-0017 records the initial dispatch and scope narrowing.

| Issue | Branch | Scope | State | Evidence |
|---|---|---|---|---|
| #248 | agent/test-query-p95-flake | API query test/performance instructions | implementing | Reproduce noisy wall-clock test, replace functional gate with operation invariant |
| #230 | agent/test-publish-race-wait | Two named ingestion race test files | implementing | Prove timeout warning visible under pytest -q, preserve cleanup |
| #221 | agent/arch-checkpoint-rerun | Extraction source/tests only | implementing | Real PostgreSQL corrupt-checkpoint repair and fresh-store resume |
| #188 | agent/188-parallel-execution | Execution plan and ownership | coordinating | Pairwise paths and dependencies checked |

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
