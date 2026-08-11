# Implementation handoff

This directory is the restart point for all implementation agents. Fable must be able to reconstruct the queue solely from GitHub and `workstreams.yaml`; conversation history is optional context.

## Current state

- Specification (v1.2) and architecture (ADR-0002) are approved. Contracts are
  frozen at OpenAPI `v0.4.0` with migrations through `0005`.
- `main` is the only implementation base; `integration/m0` is retired. Every
  push and PR is CI-gated.
- M0, M1 and M2 are complete. The M3 core landed as `M3-EXTRACTION-CORE` (#60,
  PR #145 @ `61058e4`), with follow-up fixes in #156 and #160.
- Next dispatchable package is `M3-REVIEW` (#61). #145 unblocked it, but it
  carries an explicit `status: blocked` in `workstreams.yaml` that must be
  flipped. Gate: #146 (terminal-run retry semantics) should resolve first.
  `M3-CONFIDENCE-GATE` (#62) is not unblocked — it `depends_on: [M3-REVIEW]`.
- In review, both unreviewed: PR #162 (#155) and PR #164 (#151, so
  `EVALS-REPORT-RENDER` is in review despite still reading `ready` in
  `workstreams.yaml`). PR #166 proposes relicensing MIT → Apache-2.0.
- Unresolved fork: ADR-0009 (Proposed) and #157 are mutually exclusive and need
  an integration-lead ruling before #61 exposes the SSE surface.
- Provider credentials are intentionally unavailable. Work stays mock-first;
  hosted smoke (#108) credentials are not provisioned.
- Trunk health: `main` @ `ace7b83` fails the fail-closed `audit-bulk` gate on
  `js-yaml` GHSA-5p4m-2wfm-xmqj and `nanoid` GHSA-2v37-7h3g-55p8. PR #167 fixes
  both and is green; until it merges, every branch inherits the red JS/TS job.
  Check the latest CI run on `main` before assuming a red branch is your doing.

Read `STATUS.md` for live state and `workstreams.yaml` for the authoritative dependency graph. External agents doing parallel preparation work start from `EXTERNAL_AGENT_BRIEF.md`.

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
