# Implementation handoff

This directory is the restart point for all implementation agents. Fable must be able to reconstruct the queue solely from GitHub and `workstreams.yaml`; conversation history is optional context.

## Current state

- Specification (v1.2) and architecture (ADR-0002) are approved.
- Spec Kit setup PR #1 was squash-merged to `main` as `41ef824`.
- The monorepo scaffold (T0001) is implemented on PR #50, in review.
- The next gate is `G0`: merge the scaffold, then freeze contract conventions.
- Provider credentials are intentionally unavailable. M0 must use mocks.

Read `STATUS.md` for live state and `workstreams.yaml` for the authoritative dependency graph.

## Source of truth

1. GitHub merged commits, issues, and PRs
2. `workstreams.yaml`
3. `STATUS.md`
4. Spec Kit artifacts under `specs/001-financial-evidence-lab/`

Only the integration lead changes bundle status to `merged`, checks tasks, changes dependencies, or updates shared contracts.

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
