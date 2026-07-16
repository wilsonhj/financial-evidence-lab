# ADR-0007: Bounded agentic-extraction contract and persistence

**Status:** Proposed  
**Date:** 2026-07-16

## Context

M3 needs durable typed workflows, review commands, immutable approved versions, and extraction API/client contracts. Current `main` has the approved PostgreSQL queue and free-text `LLMProvider`, but no extraction tables/contracts or structured provider usage metadata. These are frozen/shared paths, so issues #60–#62 cannot safely invent them independently.

## Decision

1. Use one finite extraction state machine in the existing Python worker and PostgreSQL queue. Checkpoint stages in tenant-scoped PostgreSQL tables; retain existing claim-short, heartbeat, reaper, retry, and lease-fencing semantics.
2. Add migration `0003_extraction_core.sql` for policies, runs, steps, events, proposals/evidence/conflicts, append-only reviews, immutable approved versions/head pointers, and calibrator artifacts with RLS/grants.
3. Add extraction JSON schemas, fixtures, OpenAPI endpoints, and generated TypeScript client as contract v0.4.0 (additive minor after M2 v0.3.0).
4. Add an additive `StructuredLLMProvider` protocol/result and deterministic mock. The OpenAI adapter uses JSON Schema Structured Outputs and records provider/model/response/usage/refusal metadata. Existing `LLMProvider` remains unchanged.
5. Fix the workflow roles and tools in versioned code. No agent-to-agent conversation or model-defined tools.
6. Use deterministic Decimal normalization, source hash verification, validation, conflict detection, and `isotonic-v1` calibration.
7. M3 is manual-approval-only. Confidence thresholds rank/block review; no proposal auto-approves.
8. Contradiction detection remains M2-owned; M3 consumes contradictory evidence and adds extraction-level conflict handling.

Default caps: 10 model calls, 100k input tokens, 20k output tokens, USD 2.00, 600 seconds; two attempts per model stage including one repair.

## Consequences

- No new infrastructure service or runtime framework.
- Contract/migration PR must merge before #60–#62 rebase.
- #60 ownership expands to provider interface/implementation and narrow worker consumer wiring.
- #61 implements API/web against generated contracts; #62 owns calibration/evals.
- Live acceptance eventually requires `FEL_OPENAI_API_KEY`; CI remains mock-only.
- Introducing auto-approval, another orchestrator/queue, new model provider semantics, or changing closed states requires a later ADR/contract review.

## Rejected alternatives

- Temporal/Celery/LangGraph/Kafka: no measured need; violates smallest-architecture rule.
- Free-text-only provider parsing: cannot guarantee schema or record required model/usage metadata.
- Mutable approved rows: loses correction history and reproducibility.
- LLM normalization/calculation/conflict collapse: violates deterministic finance/provenance principles.

## Verification

Contract/client drift, migration/RLS, queue crash-resume/idempotency, cutoff/source hash, budgets, prompt injection, review concurrency/immutability, exact numeric evaluation, and live structured-output smoke must pass as specified in `specs/003-agentic-extraction/`.
