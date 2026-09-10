# Implementation handoff

This directory is the restart point for all implementation agents. Fable must be able to reconstruct the queue solely from GitHub and `workstreams.yaml`; conversation history is optional context.

## Current state

Resolve the live queue from GitHub, then read [`STATUS.md`](STATUS.md) and
[`workstreams.yaml`](workstreams.yaml). Those files include dated evidence;
do not infer current dispatchability from a historical commit or issue list.
The [September 9 issue audit](../research/2026-09-09-open-issue-audit.md) and
[resolution plan](../superpowers/plans/2026-09-09-backlog-resolution.md) distinguish
merged implementations from outstanding acceptance evidence.

- `main` is the implementation base; `integration/m0` is retired. Use one
  issue/branch/worktree per implementation and required CI before merge.
- The project is Apache-2.0 with NOTICE obligations. The parent specification
  remains version 1.2; the accepted stack is defined by ADR-0002.
- Read `packages/contracts/openapi/openapi.yaml` for the current contract
  version, and the migration ledger/applier for applied database state. Never
  infer either from this restart document.
- M3 core, terminal-run semantics and migration 0006 are merged. M4's Decimal
  engine package #63 is merged. Review/calibration, model product workflows,
  forecasting and release acceptance remain separate work.
- A merged M1/M2 package does not prove the live corpus or retrieval exit gate.
  #56/#132/#177 and hosted reader #108 own the remaining live evidence. #96 is
  a tracker for #108's production-path criterion, not a package to redispatch.
- Provider preparation remains mock-first. Request credentials by name only
  when the scoped live test is ready. ADR-0012 is Proposed and does not replace
  the accepted OpenAI baseline. A fixture or abandoned-branch comment cannot
  authorize a provider substitution or establish deployment readiness.
- Follow the dispatch checklist below. An explicit blocked entry is not
  permission to work merely because a historical blocker has cleared; confirm
  dependencies, path ownership and the current lead registration first.

## Source of truth

1. GitHub merged commits, issues, and PRs
2. `workstreams.yaml`
3. `STATUS.md`
4. Spec Kit artifacts under `specs/001-financial-evidence-lab/`

Only the integration lead changes bundle status to `merged`, checks tasks, changes dependencies, or updates shared contracts.

## Reviewing ledger changes

`workstreams.yaml` and this file are reconciliation ledgers: a PR that edits
them changes the very state their prose describes. Review that prose against
the state that will exist **after** the merge, not against the branch's diff
base. Branch-to-trunk review cannot catch self-falsifying prose by
construction — on the branch, "this entry still reads `ready` on trunk" and
"this reconciliation is what flips it" are both accurate, and both become
false the instant the PR lands (#179).

Ledger prose must therefore not contain:

- a present-tense claim about trunk that the merge itself falsifies
  ("still reads `ready` on trunk", "is not applied at any commit since");
- a forward reference to its own PR ("this reconciliation is what flips it",
  "the fix ships here");
- a commit pin for a state that the merge supersedes.

Write the history in the past tense with an end bound instead: "read `ready`
from the 2026-08-11 merge until `ebe77af` (2026-08-31)". That sentence stays
true on the branch, at the merge, and forever after.

## Dispatch checklist

A package is ready only when:

- every `depends_on` package is `merged`;
- its base branch contains the dependency commits;
- no active package overlaps its allowed paths;
- fixture and schema versions match;
- any credential requirement has been explicitly fulfilled; and
- an issue and isolated branch/worktree exist.

Cap concurrency at four packages at all times. Prefer PRs below roughly 600 changed lines and split work that cannot be reviewed independently.

## Emergency resume

1. Fetch `main` and inspect `STATUS.md`.
2. Reconcile `workstreams.yaml` against open GitHub issues and PRs.
3. Treat pushed PR commits as authoritative over uncommitted agent work.
4. Reassign only packages with no active heartbeat or after explicitly closing the previous attempt.
5. Resume the lowest-numbered ready gate; do not bypass milestone exit criteria.
