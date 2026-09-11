# Financial Evidence Lab — Implementation Plan

**Specification:** `spec.md` v1.2
**Deployment:** Railway-hosted team SaaS with Supabase state
**Initial vertical:** US-listed B2B SaaS
**MVP model:** Revenue and gross profit

## 1. Delivery strategy

Build a pnpm/Python monorepo with a Next.js web process, FastAPI modular-monolith API, and one Python worker. Use Supabase for Postgres/pgvector, Auth, RLS, and Storage; Railway for runtime deployment; OpenAI for initial generation/embeddings; and Alpha Vantage for the first market-data adapter. Establish temporal semantics, immutable evidence, typed contracts, deterministic calculations, and evaluation fixtures before adding generative workflows.

Each milestone ends with a deployable increment and an objective exit gate. Tasks are defined in `tasks.md`; requirement identifiers refer to `spec.md`.

## 2. Workstreams

| Workstream | Scope | Primary outputs |
|---|---|---|
| Platform | Team SaaS foundation | Supabase Auth/RLS, organizations, RBAC, Railway environments, GitHub Actions |
| Data | SEC, XBRL, FRED, BYO market data | Immutable source store, parsers, normalized facts, corpus versions |
| Retrieval | Observable hybrid RAG | Lexical/vector/fact/table search, fusion, reranking, traces |
| Visualization | Coordinated analytical UI | Evidence reader, Search Observatory (Embedding Atlas deferred post-MVP) |
| Extraction | Typed human-reviewed agents | KPI, guidance, driver extraction and deterministic validation |
| Modeling | Revenue/gross-profit graph | Decimal calculation engine, scenarios, lineage, sensitivities |
| Forecasting | Quarterly 1–8 quarter forecasts | Baselines, driver models, backtests, intervals (analogues deferred post-MVP) |
| Trust | Evaluation, security, audit | Release gates, cost limits, threat controls, reproducible exports |

## 3. Milestones

### M0 — Platform and contracts

Deliver the monorepo, direct local Next.js/FastAPI processes, hosted Supabase development environment, Supabase Auth/RLS/Storage, PostgreSQL job queue, Railway service configuration, Sentry/JSON logging, API contracts, provider mocks, and cost-metering skeleton.

Exit gate:

- CI checks pass.
- A user can authenticate, create an organization and workspace, and cannot access another tenant’s records.
- Database restore and migration smoke tests pass.
- Hard cost limits reject synthetic over-budget work.

### M1 — Point-in-time evidence corpus

Deliver SEC entity/submission ingestion, HTML/iXBRL parsing, source spans, XBRL normalization, FRED vintages, the first BYO market-data adapter contract, corpus publication, and the evidence reader.

Exit gate:

- At least 20 benchmark issuers and eight years of available filings ingest idempotently.
- Source hashes and source spans remain stable across identical reruns.
- Temporal-cutoff tests achieve 100% validity.
- Market-data contract rejects missing corporate-action adjustments.

### M2 — Observable hybrid retrieval

Deliver finance-aware chunks, lexical/vector/fact/table indexes, query planning, reciprocal-rank fusion, reranking, Search Observatory, structured claim/citation states, and citation verification. The Embedding Atlas is deferred post-MVP.

Exit gate:

- Retrieval and citation gates in `spec.md` Section 19.6 pass on the 50–100-question smoke benchmark (`spec.md` Section 19.5).
- A saved query replays immutable inputs and retrieval trace.

### M3 — Agentic extraction

Deliver durable bounded workflows, KPI/guidance/revenue-driver extractors, SaaS ontology, unit/period normalization, deterministic validators, conflict handling, confidence calibration, and review queues.

Exit gate:

- Extraction and contradiction gates pass.
- No monetary fact, guidance item, or assumption auto-approves.
- Every approved record has a stable source span and audit history.

### M4 — Revenue and gross-profit model

Deliver typed model nodes, dependency graph, decimal calculation engine, unit checks, sparse scenarios, model versions, lineage, revenue bridges, gross-profit waterfalls, sensitivities, and exports.

Exit gate:

- Approved extractions populate model nodes without re-entry.
- A 5,000-node model recalculates within the p95 target.
- Scenario changes cannot mutate reported history.
- Model versions can be diffed and restored.

### M5 — Forecast Lab and MVP release

Deliver seasonal-naive and driver baselines, rolling-origin backtests, 1–8 quarter horizons, 50/80/95% intervals, forecast comparison, complete audit graph, research briefs, evidence manifests, and production readiness. Historical analogue retrieval is deferred post-MVP.

Exit gate:

- The frozen, dual-adjudicated >= 300-question benchmark (`spec.md` Section 19.5) is complete, and all Section 19.6 release gates pass on it.
- Advanced models beat the seasonal-naive baseline or remain non-default.
- Security, accessibility, load, restore, cost, and end-to-end tests pass.
- The complete definition of done in `spec.md` Section 26 passes.

## 4. Recorded architecture decisions

The locked MVP stack, its revisit triggers, and the change rule are recorded in `docs/decisions/ADR-0002-mvp-stack.md` (Status: Accepted). This plan does not restate them.

The embedding projection method remains an implementation detail selected by benchmark quality and performance, not a product-scope decision.

## 5. Quality strategy

- Build the frozen benchmark concurrently with ingestion, not after feature development.
- Treat temporal validity, monetary accuracy, and tenant isolation as zero-tolerance gates.
- Add deterministic fixtures for every production incident or material analyst correction.
- Version parsers, schemas, prompts, models, indexes, projections, and benchmark datasets.
- Promote releases only from immutable artifacts that passed the complete gate suite.

## 6. Dependency order

```text
Platform/contracts
  -> temporal corpus
  -> retrieval
  -> extraction
  -> model graph
  -> forecasting
  -> audited release
```

Work may proceed in parallel inside a milestone when contracts are stable, but no downstream milestone may bypass the preceding exit gate.

## 7. M4/M5 storage sketch and delivery ownership

Accepted design: [ADR-0023](../../docs/decisions/ADR-0023-model-and-forecast-storage-boundaries.md).
This is the missing #197 sketch, added after #63 merged; the requested
pre-#63 sequencing was missed. Existing migration 0009 already validates the
organization references on audit events, usage events and jobs and documents
`workspaces.active_scenario_id` as reserved. Future tables below are planned,
not present. Feature-owned contract slices add them without rewriting applied
migrations or bypassing the dependencies in section 6.

### 7.1 Identities, tenancy and immutable model snapshots — #64

| Entity | Responsibility and references |
|---|---|
| `model_graphs` | Stable graph identity in one organization/workspace; entity and analysis context. Any mutable current-version pointer must reference that same graph/workspace/organization. |
| `model_graph_versions` | Immutable snapshot: graph, parent version, engine snapshot ID/schema, exact canonical snapshot bytes, calculation version, cutoff, corpus/input pins, author and creation time. Maps the specification's logical `model_versions` entity to one table. |
| `model_nodes` | Version-scoped node ID and typed node payload, unit, period and provenance. A source-fact node references an immutable approved extraction version supplied by #61, never an unreviewed proposal or a mutable latest-record lookup. |
| `model_edges` | Version-scoped source/target node references plus role and operand order from `Node.inputs()`. Both endpoints must belong to the same graph version. |
| `scenarios` | Immutable scenario revision in one graph/workspace, with base graph version, label, scenario identity, as-of and optional parent scenario revision. Bull/base/bear are labels over the shared base, not three copied reported histories. |
| `scenario_overrides` | Sparse, scenario-revision-scoped target node and finite Decimal override with assumption provenance. Targets must exist in the scenario's base graph version and be eligible assumptions/drivers under the existing engine policy. |

Each table is organization-owned. Database UUIDs identify records; they do not
replace the engine's existing snapshot/result content hashes or node slugs.
Use composite unique/reference keys carrying `org_id` and the relevant
workspace/graph/version identity. Tenant checks alone are insufficient when
two workspaces belong to the same organization. Parent references must stay
inside the same graph. Source version/evidence relationships must also pass the
existing publication cutoff and corpus-pin checks.

Persist the exact engine canonical serialization, including Decimal encoding,
AST and iteration policies. Do not hash a JSONB reserialization or invent a
second calculator. Node/edge projections are generated from, and inserted
atomically with, the verified canonical snapshot. Loading must verify the
snapshot hash and reject inconsistent projections; relational indexes are for
lookup, not an independent editable source of truth.

A parent may have multiple children. Engine version numbers express ancestry
depth, so do not impose uniqueness on `(graph_id, version_number)`. Restoring
an older model derives a new child of the current version with the selected
historical content and records the restored-from version in its audit event;
it never mutates history or rewinds the audit chain. Reuse existing engine
rules for retained/replaced iteration groups and scenario lineage.

The base scenario references the unchanged base snapshot and has no override
rows; do not pass an empty override set to the engine's non-empty `Scenario`
constructor. An edit to a non-base scenario creates a new immutable revision
and derived graph snapshot. Reported/source fact nodes remain immutable and
cannot be overridden, irrespective of UI state.

The migration creating `scenarios` must also constrain
`workspaces.active_scenario_id` to a scenario in that same workspace and
organization, through a composite key such as `(active_scenario_id, id, org_id)`
referencing `(scenario_id, workspace_id, org_id)`. Preflight every existing
non-null value; invalid values stop migration with a report for an explicit
repair decision. Do not silently clear or fabricate scenario rows. Update the
reserved-column comment in this new migration, leaving 0009 unchanged.

### 7.2 Frozen forecast requests and results — #66, #67

| Entity | Responsibility and references |
|---|---|
| `forecast_runs` | Immutable admitted request: organization/workspace, exact model/scenario revision, target/unit, fiscal horizon, cutoff, dataset/corpus versions, training window, feature vintages, algorithm/configuration version, input hash and approved budget reference. |
| `forecast_results` | One append-only completion per run with success/abstention/failure, reason, output hash, registered model version and evaluation/calibration provenance. Mutable job/lease state stays in the queue, outside the immutable request/result records. |
| `forecast_points` | Immutable result-scoped fiscal-quarter/horizon points with reported/modeled/assumed provenance, finite Decimal values and interval bounds/levels. A failed or abstained result cannot appear as a successful partial forecast. |

Freeze exact physical columns and HTTP/job contracts with #66 before code
consumes these tables. Result plus points publish atomically and retries use
request identity/idempotency without replacing committed outcomes. Different
provider/algorithm/input pins produce a distinct run, not an overwrite.

Targets, one-to-eight-quarter horizons, short-history disclosure, baseline
comparison and interval requirements remain those in spec section 8.6. #67's
rolling-origin runs must freeze the actually available vintage at each origin;
no later corrected value may enter an earlier training set. Store metrics and
50/80/95% interval calibration with their target/horizon, evaluation dataset and
method versions. A confidence/calibration claim cannot be inferred from a
point forecast. Advanced-model default eligibility remains the existing
seasonal-naive gate, not a database default.

### 7.3 Immutable export evidence — #68

`export_bundles` identifies an organization/workspace-owned immutable manifest
with exact model/scenario/forecast/extraction versions, cutoff, format, renderer
version, object keys and artifact hashes. Generation publishes the manifest
only after all referenced bytes and hashes verify. Regeneration creates a new
bundle. Objects and all typed provenance references must resolve within the
authorized tenant/context; possession of a content hash is not authorization.

Preserve the source → approved extraction → model → forecast → export chain
with versioned typed references, including assumptions and calculation
provenance. A missing required edge fails export acceptance. Store references
and integrity metadata in PostgreSQL and artifact bytes in existing private
object storage; do not copy credentials or unbounded binary content into rows.

### 7.4 Access, migrations and verification

Use explicit least-privilege grants plus RLS under the existing `fel_app` and
`fel_worker` role/organization-claim model. Enable and force RLS for these tenant
tables; define SELECT/INSERT and any justified pointer-UPDATE policies with
both row eligibility and new-row checks. Revoke inherited public/client grants
where those roles exist; no direct browser Data API access is introduced.
Immutable records reject UPDATE/DELETE at the database boundary, not only in
application code. Organization/history references use restrictive deletion,
not cascading removal. Administrative threshold changes remain audited under
#62; this sketch grants no new user powers.

Each owning contract slice must demonstrate migration/restore, allowed role
operations, denied cross-tenant and same-tenant cross-workspace references,
invalid active-scenario preflight, immutable record enforcement, concurrent
idempotency, and atomic publication/rollback. #64 also proves engine round-trip
hash identity (v1 and v2), valid branching/restore and scenario non-mutation;
#66/#67 prove vintage cutoff and failure/abstention isolation; #68 proves every
artifact hash and required provenance edge. Runtime lists/readers follow the
bounded request rules established by #191.

No M4 or M5 feature is marked complete by this sketch. #64's model storage,
#66's forecast storage and #68's export storage each need a separately reviewed
migration/contract dispatch and their original milestone exit evidence.
