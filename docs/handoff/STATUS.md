# Implementation status

Last updated: 2026-07-12

## Repository

- Default branch: `main`
- Spec Kit setup merged: `41ef824` via PR #1
- Parallel handoff merged: `369777f` via PR #2
- Active implementation integration branch: `integration/m0`
- Milestone gate issues: #3–#8
- Work-package issues: #51–#68, one per pending package, mapped by the
  `issue:` field in `workstreams.yaml`. Legacy issues #9–#49 are closed
  (#9 completed via PR #50; #10–#49 superseded by the queue restructure).

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
- **PR #69 merged to `integration/m0` at `222e17e`** (external review round
  addressed): `M0-INFRA-CI` / T0009 is complete — four-job GitHub Actions
  gate (gitleaks, JS, Python, Postgres backup-restore smoke into a fresh
  database), db/ migration conventions, Railway api+worker config-as-code,
  and the `python -m fel_workers` heartbeat entrypoint; all checks green
- **PR #77 merged to `integration/m0` at `8d92cb1`**: `M0-CONTRACTS` /
  T0003 is complete and the ADR-0001 contract freeze is in effect —
  OpenAPI 3.1 v0.1.0, seven versioned JSON Schemas with fixtures and
  contract tests, drift-gated generated TypeScript client, frozen
  versioning rules (packages/contracts, VERSIONING.md, CONTRACTS.md)

## Ready

- `M0-PLATFORM` / T0002+T0004-T0008+T0010 (#53) on `agent/m0-platform` —
  the final M0 package: local processes, Supabase Auth/RLS (mock-first),
  workspace APIs with as-of cutoff, audit/observability, cost ceilings,
  and provider interfaces + mocks

## Not started

All implementation tasks after T0001 and T0009.

## Blockers

None for mock-first M0 work. Hosted integration credentials will be requested only by labeled integration issues.

## External preparation status (EXT-1/2/3)

All three external preparation packages are **blocked on environment network
policy**: this session's egress gateway 403-denies CONNECT to `www.sec.gov`,
`data.sec.gov`, and `efts.sec.gov` (verified at the proxy level; only package
registries are exempt). Each agent delivered a blocked-work checkpoint with a
complete ready-to-execute methodology and zero fabricated data:

- EXT-1 benchmark seed — draft PR #74 (`agent/ext-benchmark-seed`), Refs #71
- EXT-3 ontology survey — draft PR #75 (`agent/ext-ontology-research`), Refs #73
- EXT-2 SEC fixtures — draft PR #76 (`agent/ext-sec-fixtures`), Refs #72

Unblock by either allowlisting the three SEC hosts in the environment network
settings, or executing the committed methodologies from a network-enabled
agent environment on the same branches/PRs.

## Next actions

1. Implement and merge `M0-PLATFORM` (#53) — the final M0 package; then
   evaluate the M0 exit gate, merge integration/m0 into main, and reset the
   queue's base branch to main.
2. Decide the EXT unblock path: allowlist the three SEC hosts, or hand
   execution of PRs #74-#76 to a network-enabled agent environment.
3. Keep at most four packages active concurrently.
4. Update this file and `workstreams.yaml` after every integration merge.

## Known tooling caveat

Do not invoke Spec Kit task-to-issue generation without modification: its current deduplication pattern expects three-digit task IDs while this repository uses four-digit IDs. GitHub issues were created from the explicit package IDs in `workstreams.yaml`.
