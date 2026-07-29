<!--
Sync Impact Report
- Version change: 1.0.0 -> 1.1.0
- Modified principles: Simplicity and Provider Isolation (stack now referenced via ADR-0002, not restated); Test-First Quality Gates (gate reference updated to the canonical feature-directory spec)
- Modified sections: Approved Technical Constraints (now references docs/decisions/ADR-0002-mvp-stack.md; deck.gl removed with the deferred Embedding Atlas); Development and Review Workflow (specs/001-financial-evidence-lab/ is canonical; root SPEC.md/PLAN.md/TASKS.md are pointer stubs, no mirroring)
- Added principles: none (all five principle names retained)
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
Behavior changes MUST begin with failing unit, contract, integration, property, accessibility, or evaluation tests appropriate to the risk. The numeric release gates in `specs/001-financial-evidence-lab/spec.md` Section 19.6 are mandatory. No task is complete until its tests, telemetry, documentation, and acceptance evidence pass.

### IV. Security and Cost Boundaries
Tenant isolation, least-privilege access, immutable audit events, secret protection, prompt-injection defenses, and hard cost limits are non-negotiable. Credentials MUST enter only through approved secret-management flows and MUST never be committed, logged, or copied into prompts. Billable work MUST stop at configured hard limits.

### V. Simplicity and Provider Isolation
The MVP MUST use the smallest architecture that satisfies measured requirements. The locked MVP stack is recorded in `docs/decisions/ADR-0002-mvp-stack.md` and MUST NOT be restated elsewhere. External services MUST sit behind narrow interfaces. Any stack addition or substitution — including microservices, Redis/Celery/Kafka, DuckDB-Wasm, additional AI providers, and full OpenTelemetry infrastructure — requires benchmark evidence and an approved ADR, per the change rule in ADR-0002.

## Approved Technical Constraints

- The approved stack (frontend, backend, state, AI/data providers, runtime, and revisit triggers) is defined in `docs/decisions/ADR-0002-mvp-stack.md` (Status: Accepted).
- ECharts and React Flow remain the approved charting and graph-editor libraries. deck.gl is no longer an MVP constraint; it returns with the post-MVP Embedding Atlas.
- Local development: direct Node/Python processes with mocks and hosted Supabase; Docker is optional.
- Credentials are requested only when an integration test requires them.

## Development and Review Workflow

- The active Spec Kit feature directory, `specs/001-financial-evidence-lab/`, holds the sole canonical `spec.md`, `plan.md`, and `tasks.md`. Root `SPEC.md`, `PLAN.md`, and `TASKS.md` are pointer stubs only; nothing is mirrored.
- Work proceeds by Spec Kit phase and dependency order. Parallel agents MUST own disjoint files or modules.
- Context7 and primary documentation MUST be consulted for version-sensitive framework behavior.
- Each logical change is reviewed against this constitution, the active feature spec, and its acceptance tests.
- GitHub `main` is protected conceptually: implementation work uses an `agent/*` branch and a reviewable pull request unless the user explicitly authorizes a direct update.

## Governance

This constitution supersedes conflicting implementation practices. Amendments require a documented rationale, impact assessment, user approval, semantic version bump, and propagation to dependent templates and active feature artifacts. Every pull request MUST include a constitution check. Unjustified complexity or a failed mandatory gate blocks merge.

**Version**: 1.1.0 | **Ratified**: 2026-07-11 | **Last Amended**: 2026-07-12
