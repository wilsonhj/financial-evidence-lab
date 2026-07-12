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
