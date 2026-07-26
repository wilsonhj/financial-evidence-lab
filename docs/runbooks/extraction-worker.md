# Extraction worker operator runbook (M3-107)

## Job kind

Enqueue `extraction_run` jobs (queue name `extraction` recommended; default
worker queue is `ingestion` and also accepts the kind).

## Payload

Required pins: `run_id`, `org_id`, `workspace_id`, `entity_id`, `modes`,
`as_of`, `input_hash` (or `input_manifest`), `provider`, `model`.

For mock CI / smoke without seeding corpus spans, include inline `evidence`
(or `spans`) blocks with `source_span_id`, `text`, and optional `text_hash`.
Inline evidence forces in-memory stores so workspace ownership is not required.

## Budgets

Default ADR-0007 caps: 10 calls, 100k input tokens, 20k output tokens,
USD 2.00, 600s wall. Hard stops raise typed `BudgetExceeded`.

## Review semantics

Every proposal is persisted as `needs_review`. There is no auto-approve path.
Zero-proposal abstention succeeds the run; provider refusal / schema / budget
failures mark the run `failed`.

## Telemetry

`fel_workers.extraction.telemetry` redacts prompts, messages, source text, and
secrets. Event payloads never include filing content.
