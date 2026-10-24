# Financial Evidence Lab

**Author:** [Hirokazu J Wilson](https://github.com/wilsonhj)

[![CI](https://github.com/wilsonhj/financial-evidence-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/wilsonhj/financial-evidence-lab/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

Financial Evidence Lab is an evidence-first workspace for researching public
companies. It connects SEC filing ingestion, point-in-time hybrid search,
verifiable claims, durable agentic extraction, human conflict review, and
deterministic financial modeling without ever losing the exact source span
behind a number or conclusion.

The project is deliberately **mock-first**. You can explore the Evidence Reader,
Earnings Update Desk (with interactive 3D/2D lineage graphics), Search
Observatory, and Extraction Review Queue locally without credentials or a
database, then enable PostgreSQL 17 (`pgvector`) and live providers when you
need the full persistence and ingestion stack.

![Financial Evidence Lab — System Architecture & Trust Boundaries](./docs/architecture/assets/system-overview.svg)

---

## Try the UI in five minutes

You need **Node.js 24.20.0** (`.node-version` / `.nvmrc`) and **Corepack**.
Fixture mode runs completely offline and does not require Python, PostgreSQL,
or API keys:

```sh
corepack enable
corepack pnpm install --frozen-lockfile
FEL_DEPLOYMENT_MODE=fixture FEL_API_BEARER_TOKEN= FEL_EVIDENCE_SOURCE=fixture corepack pnpm --filter @fel/web dev
```

Open these interactive workspaces in your browser:

| Route | Workspace | What you can explore |
| :--- | :--- | :--- |
| <http://localhost:3000> | **Filings & Evidence Reader** (`/reader/[documentId]`) | Version-pinned SEC filings, global character-offset highlighting, SHA-256 span verification, duplicate/restatement detection, and amendment chains (`10-Q` → `10-Q/A`). |
| <http://localhost:3000/desk> | **Earnings Update Desk** (`/desk`) | Interactive **3D Evidence & Calculation Lineage Constellation**, Base/Bull/Bear scenario waterfall & sensitivity charts, point-in-time cutoff scrubber, NRR conflict resolution (`108%` vs `109%`), and guidance approval gates. |
| <http://localhost:3000/observatory> | **Search Observatory** (`/observatory`) | Interactive **4-Lane RRF Fusion Flow (`k=60`) & Budget Visualizer**, candidate rank/score inspection across Dense/Lexical/Fact/Table lanes, rejection timelines, claim entailment status, and run comparison (`/observatory/compare`). |
| <http://localhost:3000/extractions> | **Extraction Review Queue** (`/extractions`) | Atomic batch review (`accept`, `edit`, `merge`, `reject`), ontology conflict resolution with ETag preconditions, live SSE run event streams (`/extraction-runs`), and immutable version history (`/approved-extractions`). |

Fixture mode is explicit by design (`FEL_DEPLOYMENT_MODE=fixture`); there is no
silent production fallback. In public deployment mode without request-scoped
sessions, business routes fail closed with HTTP `503`. For a database-backed
setup, see [`docs/development/local.md`](./docs/development/local.md).

---

## What works today

| Area | State | What is implemented on `main` |
| :--- | :--- | :--- |
| **Platform foundation (M0)** | Implemented | Workspace APIs, Supabase JWKS + mock authentication (`apps/api/app/supabase_auth.py`), tenant-scoped RLS (`fel_app`) and worker RLS (`fel_worker`), durable per-org query budgets and rate limiting, offline BYOK credential encryption (`credential_cipher.py`), checksummed migration applier (`scripts/db/migrate.py`, migrations `0001`–`0011`), and public deployment guard. |
| **Evidence ingestion & reader (M1)** | Implemented (live gates open) | SEC discovery/fetch/XBRL ingestion, immutable document versions, canonical spans/facts, composite reader API, Next.js Evidence Reader with WCAG 2.2 AA contrast verification, and local production-build Chromium smoke. Dedicated hosted Railway smoke (#108) and the 20-issuer live SEC gate (#56/#81) remain open. |
| **Hybrid retrieval & claims (M2)** | Implemented (mock-first + OpenAI adapters) | Dense (512-dim), lexical, fact, and table lanes, deterministic planning and RRF (`k=60`), byte-stable replayable traces, non-identity atomic claim decomposition and numeric verification, explicit-key OpenAI embedding/structured adapters, 65-question benchmark gate harness, and Search Observatory UI. |
| **Agentic extraction & review (M3)** | Implemented (mock-first + full review stack) | `packages/ontology` (`saas-metrics/v1`: 9 families, 14 KPIs), 5 typed read-only extraction roles, 10-stage checkpointed worker FSM (`extraction_run_steps.output`), Decimal normalizer, deterministic accounting validators, hard budget caps, batched atomic review API/UI (`/extractions`), live SSE events, and offline isotonic calibration primitives. |
| **Financial modeling (M4) & forecasting (M5)** | M4 calc engine & Desk UI implemented; M4 DB & M5 planned | `packages/calculation-engine` (`fel_calculation_engine`) implements all 9 typed node kinds, 34-digit IEEE Decimal arithmetic, closed unit algebra, `fel-formula/v1` expression ASTs, exact-SCC Jacobi fixed-point iteration, Base/Bull/Bear scenario overrides, and a 5,000-node recalculation benchmark (~43 ms). M4 Postgres persistence and M5 forecasting remain roadmap work. |

The authoritative product requirements live in
[`specs/001-financial-evidence-lab/`](./specs/001-financial-evidence-lab/).
GitHub issues, pull requests, and [`docs/handoff/STATUS.md`](./docs/handoff/STATUS.md)
track delivery and verification state.

---

## System design diagrams (editable `.svg` for Miro & Figma)

All diagrams in [`docs/architecture/assets/`](./docs/architecture/assets/) are
authored as clean, layered, editable `.svg` files using semantic `<g id="...">`
groups and vector primitives. You can drag-and-drop them directly onto any
**Miro board** or **Figma canvas** to ungroup and edit individual nodes,
connectors, and labels.

### 1. End-to-End Epistemic Lineage (M1 → M4)

![End-to-End Epistemic Lineage Pipeline](./docs/architecture/assets/evidence-to-model-pipeline.svg)

Three non-negotiable rules govern the architecture:

1. **Point-in-time by default (`published_at <= effective_as_of`).** Every query,
   direct document read, extraction pin, and calculation leaf enforces an
   effective temporal cutoff so future information can never leak into a
   historical analysis.
2. **Immutable evidence & cryptographic lineage.** Document versions, global
   character spans (`start_char..end_char`), SHA-256 text hashes, retrieval
   traces, approved extraction versions, and calculation snapshots (`snapshot_id`,
   `result_id`) are content-addressed and superseded rather than overwritten.
3. **Fail closed.** Missing credentials, ambiguous deployment modes, unverified
   span hashes, undeclared formula cycles, or exceeded token/cost budgets halt
   explicitly rather than returning plausible-looking numbers.

### 2. Observable Hybrid Retrieval (M2) & Durable Extraction FSM (M3)

![Observable Hybrid Retrieval and Durable Extraction State Machine](./docs/architecture/assets/hybrid-retrieval-and-extraction-fsm.svg)

### 3. Deterministic Decimal Calculation DAG & Four-Way Provenance (M4)

![Deterministic Calculation DAG and Four-Way Provenance](./docs/architecture/assets/calculation-dag-and-provenance.svg)

Read the [architecture overview](./docs/architecture/overview.md) for component
boundaries, the [system design guide](./docs/architecture/system-design.md) for
data flow and failure semantics, and the
[visualization & 3D interactive design guide](./docs/architecture/visualization-roadmap.md)
for how financial evidence and calculation graphs are rendered interactively.

---

## Repository map

```text
apps/api/                    FastAPI service, Supabase/mock auth, RLS, reader/retrieval/extraction APIs
apps/web/                    Next.js 16 Evidence Reader, Update Desk (3D/2D viz), Search Observatory, Review UI
workers/                     Durable job consumer, SEC ingestion pipelines, 10-stage extraction runtime FSM
packages/contracts/          Versioned JSON Schema/OpenAPI contracts (v0.6.0) and generated TypeScript types
packages/calculation-engine/ Deterministic 34-digit Decimal DAG, formula ASTs, Jacobi SCC solver, scenarios
packages/ontology/           SaaS metric ontology (saas-metrics/v1: 9 families, 14 metrics) & comparability keys
packages/providers/          Provider protocols, deterministic mocks, OpenAI adapters, BYOK credential cipher
packages/retrieval/          Chunking, 4-lane hybrid retrieval, RRF k=60 fusion, traces, claim entailment
packages/retrieval-evals/    Retrieval benchmark compiler, oracle, and evaluation metrics
db/migrations/               Append-only PostgreSQL migrations (0001..0011) and SQL test harnesses
evals/                       Cross-stack harnesses, SEC fixtures, retrieval gates, deterministic SVG/MD reports
infra/                       Railway service definitions for API, worker, and web
scripts/                     Migration applier (scripts/db/migrate.py), CI guards, and audit tooling
specs/                       Canonical Spec Kit product/specification packages (001..005)
docs/architecture/           System overview, system design, visualization roadmap, and editable SVG diagrams
docs/decisions/              Architecture Decision Records (ADR-0001..ADR-0028)
docs/development/            Local setup, testing matrix, and quality gates
docs/handoff/                Multi-agent orchestration queue and verification checkpoints
docs/runbooks/               Operator runbooks (extraction worker, unit/guidance policy migrations)
```

---

## Development setup

Supported toolchain:

- **Node.js 24.20.0** (`.node-version` for CI, `.nvmrc` for nvm)
- **pnpm 10.33** through Corepack (`packageManager` in `package.json`)
- **Python 3.11** (`.python-version`)
- **PostgreSQL 16/17 with `pgvector`** for database-backed tests and services

```sh
corepack enable
corepack pnpm install --frozen-lockfile

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

If `python3.11` is not on your `PATH`, use `uv venv --python 3.11 --seed .venv`
as documented in [`docs/development/local.md`](./docs/development/local.md).

Run the fast, database-independent test and quality suites:

```sh
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
corepack pnpm run test
.venv/bin/pytest
```

Database-gated Python suites skip automatically when `TEST_DATABASE_URL` is
absent and run against PostgreSQL 17 + `pgvector` in CI. To apply migrations to
a local PostgreSQL instance, use the checksummed migration applier
(`python3.11 scripts/db/migrate.py`). See the
[local development guide](./docs/development/local.md) and
[testing guide](./docs/development/testing.md) for the complete matrix.

---

## API and runtime modes

The web application (`apps/web`) enforces an explicit deployment mode guard
(`FEL_DEPLOYMENT_MODE` in [`apps/web/src/lib/deployment-mode.ts`](./apps/web/src/lib/deployment-mode.ts)):

- `FEL_DEPLOYMENT_MODE=fixture` with `FEL_EVIDENCE_SOURCE=fixture` — deterministic local UI exploration with zero upstream API calls.
- `FEL_DEPLOYMENT_MODE=synthetic-http` or `reader-smoke` with `FEL_EVIDENCE_SOURCE=http` — dedicated local/CI cross-stack integration against FastAPI and PostgreSQL.
- `FEL_DEPLOYMENT_MODE=public` (default when unset) — fails closed with HTTP `503` on business routes until per-user request-scoped session custody is enabled, preventing shared deployment-bearer leakage.

Server tokens (`FEL_API_BEARER_TOKEN`) are isolated to server-only modules and
are never exposed to client components.

---

## Current critical path & open release gates

Per [`docs/handoff/STATUS.md`](./docs/handoff/STATUS.md), the core M0–M4 code
foundations are merged on `main`. The remaining items before live production
cutover are:

1. **Public session custody & user-funded BYOK admission (#324 / ADR-0026 / ADR-0027):**
   connect the merged Supabase verifier (`supabase_auth.py`), offline credential
   cipher (`credential_cipher.py`), and OpenAI adapters (`openai_structured.py`,
   `openai_embeddings.py`) to request-scoped browser sessions and durable
   user-funded admission.
2. **Dedicated load & hosted smoke targets (#61 / #108):** run the 25-concurrent-user
   extraction review benchmark (#61) and the hosted Railway ingestion-to-reader
   smoke (#108) against dedicated database/compute targets rather than a shared
   local Docker VM.
3. **Live corpus & benchmark cutover (#56 / #81 / #132 / #177):** execute the
   20-issuer SEC ingestion gate and the 65-question live retrieval/claim
   evaluation once user-funded credentials and provider ADRs (#195) are ratified.
4. **M4 database persistence & M5 forecasting:** add PostgreSQL persistence
   tables for `fel_calculation_engine` snapshots/scenarios (#197) and implement
   M5 statistical/ML forecast workflows.

---

## Contributing

1. Read [`AGENTS.md`](./AGENTS.md) and the
   [contributor operating model](./docs/handoff/README.md).
2. Start from `main` and claim one GitHub issue/work package.
3. Keep path ownership non-overlapping. Shared contract, migration, lockfile,
   ADR, and handoff files require the repository's `contract-change` process.
4. Add deterministic tests for behavior changes and verify local gates before
   opening or updating a pull request.

## Further reading

- [Architecture overview](./docs/architecture/overview.md)
- [System design](./docs/architecture/system-design.md)
- [Visualization & 3D interactive design roadmap](./docs/architecture/visualization-roadmap.md)
- [Calculation engine documentation](./packages/calculation-engine/README.md)
- [Local development](./docs/development/local.md)
- [Testing guide](./docs/development/testing.md)
- [Extraction worker runbook](./docs/runbooks/extraction-worker.md)
- [Canonical specification](./specs/001-financial-evidence-lab/spec.md)

## License

Apache-2.0. See [`LICENSE`](./LICENSE) and [`NOTICE`](./NOTICE).
