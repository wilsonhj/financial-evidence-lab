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

## In review (draft PRs open, CI green)

Both M1 packages were dispatched concurrently on 2026-07-13 (disjoint
allowed paths) and delivered draft PRs the same day; CI is green on both
head SHAs. Awaiting integration-lead review and merge decision:

- `M1-INGESTION` / T0101–T0109 (#54) — **draft PR #80**
  (`agent/m1-ingestion` @ `a813cfb`): full mock-first ingestion vertical
  (LiveSecClient behind MockTransport, immutable content-addressed raw
  store, stdlib HTML/iXBRL parser with stable UUIDv5 spans, financial-fact
  normalization with duplicate/restatement handling, idempotent versioned
  jobs with atomic corpus publication, quarantine, vintage-aware FRED,
  Alpha Vantage adapter, FOR-005 fail-closed feature assembly, read-only
  corpus API with as_of filtering). 68 new tests (95 Python total).
  Flagged pre-authorized deviation: additive-only
  `db/migrations/0002_corpus_core.sql` (public corpus tables, no
  org_id/RLS by documented design, `fel_app` SELECT-only).
- `M1-EVIDENCE-UI` / T0110 (#55) — **draft PR #79**
  (`agent/m1-evidence-ui` @ `cdcffbe`): Next.js 16 App Router runtime,
  evidence reader at `/reader/[documentId]` (keyboard-navigable outline,
  non-color-only span highlights, fact panel, scale-aware string-decimal
  duplicate-conflict detection, amendment/restatement banners, client-side
  notes) against a synthetic fixture via the typed `EvidenceSource`
  interface. 52 JS tests; `pnpm --filter @fel/web build` exit 0. Flagged
  pre-authorized deviations: root `tsconfig.json` (apps/web out of the
  composite graph), `pnpm-workspace.yaml` postcss `^8.5.10` override
  (CVE'd transitive pin from next 16), mechanical lockfile.

## Not started

All implementation tasks after M1 (M1-CORPUS-QA becomes ready when
M1-INGESTION merges).

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

1. Review and merge draft PRs #80 (M1-INGESTION) and #79 (M1-EVIDENCE-UI);
   the 0002 migration deviation on #80 needs integration-lead sign-off.
2. After #80 merges: mark M1-CORPUS-QA (#56) ready and dispatch it; swap
   the web reader's `evidenceSource` binding to `HttpEvidenceSource` once
   the ingestion API is deployed (noted in #79's handoff).
3. Decide the EXT unblock path: allowlist the three SEC hosts in the cloud
   environment's network settings (new session required), or hand
   execution of PRs #74-#76 to a network-enabled agent environment. The
   same decision gates live-credential integration runs for M1-INGESTION.
4. Keep at most four packages active concurrently.
5. Update this file and `workstreams.yaml` after every integration merge.

## Known tooling caveat

Do not invoke Spec Kit task-to-issue generation without modification: its current deduplication pattern expects three-digit task IDs while this repository uses four-digit IDs. GitHub issues were created from the explicit package IDs in `workstreams.yaml`.
