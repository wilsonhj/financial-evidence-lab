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
  19 milestone-scoped packages, with Embedding Atlas (T0211–T0213) and
  analogue retrieval (T0506) deferred post-MVP, and T0214 split into T0214a
  (M2 smoke benchmark) and T0214b (M5 frozen 300-question adjudicated
  benchmark)
- Specification v1.2 with ADR-0002 (single-source docs, pgvector/RLS
  mandates, Atlas → P1, lanes 7 → 4, benchmark phasing)
- **PR #50 merged to `integration/m0` at `1ec35dc`** (two review rounds
  addressed): `M0-SCAFFOLD` / T0001 is complete — monorepo scaffold, `make ci`
  gate (format-check, lint, typecheck, tests, full-scope audits), toolchain at
  ESLint 10 / TypeScript 6.0 / Vitest 4 / httpx2

## Ready

- `M0-INFRA-CI` / T0009 on `agent/m0-infra-ci` — GitHub Actions gates,
  db/ migration skeleton, Railway service configuration, backup-restore
  smoke test (mock-first: CI Postgres container, no hosted credentials)

## Not started

All implementation tasks after T0001 and T0009.

## Blockers

None for mock-first M0 work. Hosted integration credentials will be requested only by labeled integration issues.

## Next actions

1. Re-sync GitHub issues #9–#49 to the consolidated 19-package queue (in
   progress).
2. Implement and merge `M0-INFRA-CI` (in progress), then dispatch
   `M0-CONTRACTS`.
3. Keep at most four packages active concurrently.
4. Update this file and `workstreams.yaml` after every integration merge.

## Known tooling caveat

Do not invoke Spec Kit task-to-issue generation without modification: its current deduplication pattern expects three-digit task IDs while this repository uses four-digit IDs. GitHub issues were created from the explicit package IDs in `workstreams.yaml`.
