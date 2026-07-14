# Implementation status

Last updated: 2026-07-13

## Repository

- Default branch: `main`
- Spec Kit setup merged: `41ef824` via PR #1
- Parallel handoff merged: `369777f` via PR #2
- Active implementation base branch: `main` (M0 trunk `integration/m0`
  merged into `main` on 2026-07-13; M1+ packages branch from and target
  `main`)
- Milestone gate issues: #3–#8
- Work-package issues: #51–#68, one per pending package, mapped by the
  `issue:` field in `workstreams.yaml`. Legacy issues #9–#49 are closed
  (#9 completed via PR #50; #10–#49 superseded by the queue restructure).

## Active gate

M0 is **complete and its exit gate passes** (evaluated 2026-07-13):

- CI checks pass — four-job gate (gitleaks, JS, Python + Postgres 17
  service, DB backup-restore smoke) green on every M0 merge.
- A user can authenticate, create an organization and workspace, and cannot
  access another tenant's records — proven by the RLS negative cross-tenant
  suite and membership-canonical auth (PR #78, incl. forged-claim tests).
- Database restore and migration smoke tests pass — CI database job applies
  migration 0001 and verifies dump → drop database → restore.
- Hard cost limits reject synthetic over-budget work — 402
  COST_LIMIT_EXCEEDED test in the cost-ceiling suite.

Next gate: M1 — point-in-time evidence corpus.

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
- **PR #78 merged at `9213962`** (external security review round fully
  addressed): `M0-PLATFORM` / T0002+T0004–T0008+T0010 complete —
  membership-canonical mock auth, RLS tenancy with negative cross-tenant
  and forged-claim tests, workspace APIs (idempotency replay with ETag,
  If-Match concurrency, timezone-aware as_of), request observability +
  append-only audit, cost ceilings, provider interfaces + deterministic
  mocks, lease-fenced SKIP LOCKED job queue. **M0 is complete.**

## In review

- `M1-INGESTION` / T0101–T0109 (#54) — **PR #80** (`agent/m1-ingestion`,
  ready-for-review): full mock-first ingestion vertical. Review round 1
  (at `d12e57c`) fixed all 6 external findings plus the 20-finding
  internal audit — entity/accession-scoped idempotency, divergent-bytes
  quarantine, quarantined-doc invisibility, job consumer with e2e test,
  canonical-text persistence, iXBRL transform registry, non-finite
  rejection, stack-based nested parsing, FRED no-lookahead vintage,
  race hardening, ADR-0004 grant removal (147 pytest). Round 2 in
  flight for three re-review findings: continuous lease heartbeat +
  reap_stale wiring, fail-closed live storage binding
  (LocalDirStorageProvider + FEL_STORAGE_DIR), and the documented
  visibility ruling (M1 reads gate on "successfully parsed";
  corpus-version gating deferred to M2 retrieval).

## Recently merged (M1)

- **PR #79 merged to `main` at `932f367`** (2026-07-14): `M1-EVIDENCE-UI`
  / T0110 complete — evidence reader on Next.js 16 (keyboard-navigable
  outline, fail-closed citation-integrity verification with explicit
  error states, scale-aware string-decimal duplicate comparison,
  deterministic amendment linkage, document-scoped `EvidenceSource` with
  distinct document/version IDs, `HttpEvidenceSource` with auth + as_of +
  typed errors + capability gating). External re-review passed clean at
  `d8bbe54`; 99 tests. Root-config hunks covered by ADR-0003 (PR #82,
  merged at `a5ec237` with the machine-readable shared-path policy).

## Not started

All implementation tasks after M1 (M1-CORPUS-QA becomes ready when
M1-INGESTION merges). Follow-up issues awaiting queue slots: #83
(FR-ING-001 company-facts ingestion), #84 (Railway worker startCommand →
consumer mode; infra paths), #81 (EXT-2b supplemental stress cohort;
needs SEC egress session).

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

1. Land PR #80's round-2 fixes (lease heartbeat, live storage binding,
   visibility ruling), verify, obtain clean re-review, merge.
2. After #80 merges: mark M1-CORPUS-QA (#56) ready and dispatch it;
   schedule #83 (company-facts) alongside it or early M2; wire #84
   (Railway consumer startCommand) with the deploy milestone; swap the
   web reader's `evidenceSource` binding to `HttpEvidenceSource` once
   the ingestion API is deployed.
3. EXT (egress-enabled session): PR #76 has two integration-lead
   disposition comments to action (8th feature, excerpts, validator,
   amendments, email, retarget to main); PRs #74/#75 execute per
   `SESSION_BRIEF_SEC_EGRESS.md`; #81 (EXT-2b) runs after #76 closes
   out. Stale trackers #71–#73 closed (2026-07-14); the PRs are the
   live state. M0 gate issue #3 closed.
4. Keep at most four packages active concurrently.
5. Update this file and `workstreams.yaml` after every integration merge.

## Known tooling caveat

Do not invoke Spec Kit task-to-issue generation without modification: its current deduplication pattern expects three-digit task IDs while this repository uses four-digit IDs. GitHub issues were created from the explicit package IDs in `workstreams.yaml`.
