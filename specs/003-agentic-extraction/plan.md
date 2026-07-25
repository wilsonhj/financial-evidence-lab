# M3 Agentic Extraction — Implementation Plan

**Parent:** `specs/001-financial-evidence-lab/`  
**ADR:** `docs/decisions/ADR-0007-agentic-extraction-contract.md` (Accepted)  
**Contracts on main:** `@fel/contracts@0.4.0`, migration `0004_extraction_core.sql`

## 1. Strategy

Implement against the frozen contract on `main`. Do not invent shared
contracts/migrations in package PRs. Detail design lives in `research.md`,
`data-model.md`, and `clarify-analyse.md`.

## 2. Package slices (dispatch)

| Package | Issue | Spec Kit tasks | Notes |
|---------|-------|----------------|-------|
| M3-EXTRACTION-CORE | #60 | T0301–T0305 / M3-100–M3-107 | Ontology, FSM, roles, normalize, validate, mock E2E |
| M3-REVIEW | #61 | T0308–T0309 / M3-200–M3-204 | APIs, SSE, review UI |
| M3-CONFIDENCE-GATE | #62 | T0306–T0307, T0310 / M3-300–M3-304 | Calibration, evals, live smoke |

## 3. #60 PR checkpoints

1. Ontology package (`packages/ontology`) + goldens
2. Runtime + normalize + validators (pure)
3. Five typed roles + mock structured envelopes
4. `extraction_run` consumer wiring + mock E2E last

## 4. Source of truth

Runtime schemas/OpenAPI: **`packages/contracts`** (not copies under `specs/003/contracts/`).  
Acceptance for #60: worker/DB mock path — not `apps/api`/`apps/web` quickstart.
