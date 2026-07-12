# Financial Evidence Lab

Implementation specification for a highly visual, evidence-first financial research application combining hybrid retrieval, agentic extraction, forecasting, and interactive revenue modeling.

## Documents

- [`specs/001-financial-evidence-lab/`](./specs/001-financial-evidence-lab/) — **canonical** `spec.md`, `plan.md`, and `tasks.md` (the Spec Kit feature directory).
- [`SPEC.md`](./SPEC.md), [`PLAN.md`](./PLAN.md), [`TASKS.md`](./TASKS.md) — root pointer stubs to the canonical documents above.
- [`docs/decisions/`](./docs/decisions/) — ADRs, including [`ADR-0002-mvp-stack.md`](./docs/decisions/ADR-0002-mvp-stack.md), the single source of truth for the locked MVP stack.
- [`AGENTS.md`](./AGENTS.md) — operating contract for internal and external coding agents.
- [`docs/handoff/`](./docs/handoff/) — resumable Claude Code/Fable orchestration state and work queue.
- [`.specify/`](./.specify/) — GitHub Spec Kit configuration, constitution, scripts, and templates.

## Product thesis

Financial analysis should not force users to choose between conversational AI, document search, and spreadsheet modeling. Financial Evidence Lab connects them in one auditable workspace: every generated claim, extracted fact, forecast, and model output remains linked to its source evidence and calculation lineage.

## Proposed MVP

1. Select a public company and point-in-time cutoff.
2. Ingest its SEC filings and normalized XBRL facts.
3. Ask a financial question using visible hybrid retrieval.
4. Review agent-extracted revenue drivers and citations.
5. Build bull/base/bear scenarios in a visual driver graph.
6. Inspect forecast ranges, sensitivities, and provenance.
7. Export an evidence-backed research brief.

## Status

Specification v1.2 (2026-07-12) restructures the documents around a single source of truth: `specs/001-financial-evidence-lab/` is canonical and the root files are pointer stubs. The Embedding Atlas is deferred to P1 (post-MVP), and the locked MVP stack — Next.js 16/React 19, FastAPI, Supabase, PostgreSQL jobs, OpenAI, Alpha Vantage, Railway — is recorded in [`ADR-0002-mvp-stack.md`](./docs/decisions/ADR-0002-mvp-stack.md). GitHub Spec Kit 0.12.11 is initialized in Codex skills mode. The monorepo scaffold was implemented on PR #50.
