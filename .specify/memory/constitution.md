<!--
Sync Impact Report
- Version change: template -> 1.0.0
- Added principles: Evidence and Temporal Integrity; Deterministic Finance; Test-First Gates; Security and Cost Boundaries; Simplicity and Provider Isolation
- Added sections: Approved Technical Constraints; Development and Review Workflow
- Removed sections: none
- Templates: ✅ .specify/templates/plan-template.md; ✅ .specify/templates/spec-template.md; ✅ .specify/templates/tasks-template.md
- Follow-up TODOs: none
-->
# Financial Evidence Lab Constitution

## Core Principles

### I. Evidence and Temporal Integrity
Every factual claim, extracted value, assumption, calculation, and forecast MUST retain stable provenance to immutable source data. Every query and backtest MUST enforce publication-time cutoffs. A temporal violation, unsupported factual conclusion, or cross-tenant evidence leak is a release blocker.

### II. Deterministic Financial Computation
Authoritative monetary calculations MUST use decimal arithmetic, typed units, explicit fiscal periods, and deterministic formulas. Language models MAY propose or explain assumptions but MUST NOT execute authoritative financial math. Reported, derived, user-supplied, and forecast values MUST remain distinguishable.

### III. Test-First Quality Gates
Behavior changes MUST begin with failing unit, contract, integration, property, accessibility, or evaluation tests appropriate to the risk. The numeric release gates in `SPEC.md` Section 19.6 are mandatory. No task is complete until its tests, telemetry, documentation, and acceptance evidence pass.

### IV. Security and Cost Boundaries
Tenant isolation, least-privilege access, immutable audit events, secret protection, prompt-injection defenses, and hard cost limits are non-negotiable. Credentials MUST enter only through approved secret-management flows and MUST never be committed, logged, or copied into prompts. Billable work MUST stop at configured hard limits.

### V. Simplicity and Provider Isolation
The MVP MUST use the smallest architecture that satisfies measured requirements: a Next.js frontend, FastAPI modular monolith, one Python worker, Supabase state services, and PostgreSQL jobs. External services MUST sit behind narrow interfaces. Microservices, Redis/Celery/Kafka, DuckDB-Wasm, additional AI providers, and full OpenTelemetry infrastructure require benchmark evidence and an approved ADR.

## Approved Technical Constraints

- Frontend: Next.js App Router, TypeScript, ECharts, React Flow, and deck.gl.
- Backend: FastAPI, Pydantic, Polars/PyArrow, and Python decimal arithmetic.
- State: Supabase Postgres/pgvector, Auth, RLS, and Storage.
- AI/data: OpenAI generation and embeddings, Alpha Vantage market data, direct SEC and FRED sources.
- Runtime: Railway web/API/worker services; GitHub Actions gates; Sentry and structured JSON logs.
- Local development: direct Node/Python processes with mocks and hosted Supabase; Docker is optional.
- Credentials are requested only when an integration test requires them.

## Development and Review Workflow

- `SPEC.md`, `PLAN.md`, and `TASKS.md` remain canonical and are mirrored into the active Spec Kit feature directory.
- Work proceeds by Spec Kit phase and dependency order. Parallel agents MUST own disjoint files or modules.
- Context7 and primary documentation MUST be consulted for version-sensitive framework behavior.
- Each logical change is reviewed against this constitution, the active feature spec, and its acceptance tests.
- GitHub `main` is protected conceptually: implementation work uses an `agent/*` branch and a reviewable pull request unless the user explicitly authorizes a direct update.

## Governance

This constitution supersedes conflicting implementation practices. Amendments require a documented rationale, impact assessment, user approval, semantic version bump, and propagation to dependent templates and active feature artifacts. Every pull request MUST include a constitution check. Unjustified complexity or a failed mandatory gate blocks merge.

**Version**: 1.0.0 | **Ratified**: 2026-07-11 | **Last Amended**: 2026-07-11
