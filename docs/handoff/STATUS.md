# Implementation status

Last updated: 2026-07-12

## Repository

- Default branch: `main`
- Spec Kit setup merged: `41ef824` via PR #1
- Parallel handoff merged: `369777f` via PR #2
- Active implementation integration branch: `integration/m0`
- Milestone gate issues: #3–#8
- Work-package issues: #9–#49 — **STALE**: these were generated from the
  original 41-package queue and are pending re-sync to the restructured
  package set in `workstreams.yaml`. Do not dispatch from their bodies until
  the re-sync lands.

## Active gate

`G0` — scaffold and contract conventions.

## Completed

- Product specification, plan, tasks, constitution, and architecture defaults
- GitHub read/write verification for `wilsonhj`
- Spec Kit initialization and history reconciliation through PR #1
- Claude Code/Fable handoff protocol, machine-readable queue, templates, and ownership rules
- Architecture audit and queue restructure: 41 work packages consolidated to
  19 milestone-scoped packages (18 pending once the scaffold merges), with
  Embedding Atlas (T0211–T0213) and analogue retrieval (T0506) deferred
  post-MVP, and T0214 split into T0214a (M2 smoke benchmark) and T0214b
  (M5 frozen 300-question adjudicated benchmark)

## In review

- `M0-SCAFFOLD` / T0001 implemented on PR #50 (branch
  `claude/repo-analysis-g0fvjy`, commits `a45b999` + `e2966a2`), awaiting
  integration merge

## In progress

- Spec v1.2 is being prepared: Embedding Atlas demoted to P1, lanes reduced
  from 7 to 4, benchmark phasing (T0214a/T0214b), and pgvector/RLS mandates

## Not started

All implementation tasks after T0001.

## Blockers

None for mock-first M0 work. Hosted integration credentials will be requested only by labeled integration issues.

## Next actions

1. Merge PR #50 (`M0-SCAFFOLD`) into `integration/m0`.
2. Re-sync GitHub issues #9–#49 to the consolidated 19-package queue.
3. Dispatch `M0-INFRA-CI`, then the dependency-ready M0 packages.
4. Keep at most four packages active concurrently.
5. Update this file and `workstreams.yaml` after every integration merge.

## Known tooling caveat

Do not invoke Spec Kit task-to-issue generation without modification: its current deduplication pattern expects three-digit task IDs while this repository uses four-digit IDs. GitHub issues were created from the explicit package IDs in `workstreams.yaml`.
