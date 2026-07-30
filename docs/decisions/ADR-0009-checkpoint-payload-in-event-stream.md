# ADR-0009: `step_completed.stage_output` carries evidence text, and the event stream is not metadata-only

Status: Proposed
Date: 2026-07-29
Occasioned by: M3-EXTRACTION-CORE (#60), PR #145 review finding P1-8.2
Amends: the event-payload guarantee in `specs/003-agentic-extraction/data-model.md`,
`specs/003-agentic-extraction/contracts/extraction-api.yaml`, and
`specs/003-agentic-extraction/spec.md`

## Context

Three places state that extraction run events carry metadata only:

- `data-model.md:23` — "Payload contains IDs/counts/status, **never evidence or prompt text**."
- `contracts/extraction-api.yaml:180` — "IDs, counts, states and redacted errors only; **no source or prompt text**."
- `spec.md:180` — "No source text or secrets in logs; prompts and raw provider outputs are stored only in approved encrypted/object storage or hashed/redacted fields."

The implementation does not meet that guarantee, and cannot while migration
`0004` is frozen. `extraction_run_steps` has **no `output` column** (`0004:143-171`),
so the only durable carrier for a stage's result is the `step_completed` event
payload. `spec.md:61` simultaneously requires that "a crash after any completed
step resumes from the next incomplete step without duplicating proposals or model
calls already committed."

Those two requirements are not jointly satisfiable. Resume needs the stage output
to survive; the only surviving place is the event payload.

Truncating that payload is not an option: the same strings are hash inputs.
`hash_json(clean)` feeds `raw_payload_hash` → `proposal_id_for`
(`validate/pipeline.py:157,178-180`); `stage_input_hash` covers the same payloads
(`workflow.py:370-375`); and `_restore_output` re-checks `sha256_hex(text)` against
the pinned `text_hash` (`workflow.py:484`). An earlier truncation bug on this branch
resumed a 630-character filing span as 76 characters while its hash still described
the original — the run then re-extracted from a fragment under a hash that no longer
matched it.

## Decision

Accept that a `step_completed` event's `stage_output` carries pinned span text and
stage payloads **verbatim**, and amend the three documents above to describe the
actual, bounded guarantee:

1. **Prompts, provider messages, and secrets are stripped everywhere**, including
   inside `stage_output` (`events.py:89-95`). This part of the original guarantee
   holds unconditionally and is not weakened.
2. **`stage_output` on `step_completed` is exempt from source-text redaction**,
   because it is the durable checkpoint record, not telemetry. No other event type
   and no other key is exempt.
3. Every other event payload remains IDs, counts, states and redacted errors.

## Consequences

- The published API contract currently advertises a guarantee the implementation
  does not provide. Until the amendment lands, a consumer granted the
  "metadata-only" event stream in fact receives the full evidence corpus. That is
  the defect this ADR exists to close; the engineering trade itself is sound.
- Today the exposure is bounded: the only corpus producers are EDGAR
  (`sec_filing_fetch`, `sec_discovery`, `sec_company_facts`), so the event stream
  contains nothing beyond public SEC filing text plus model-derived numbers over
  it. There is no upload or private-document ingestion path in `apps/api/app`.
- RLS and grants are unchanged: `extraction_run_events` carries the same org-scoped
  policy as every other extraction table (`0004:692-695`) with only
  `GRANT SELECT, INSERT ... TO fel_app` (`0004:661`).
- **This becomes a genuine data-exposure finding the moment any non-public document
  source is ingested.** Whoever adds one must revisit this ADR first.
- The event stream is also an SSE surface (`data-model.md:23`, SSE `id:` equals the
  table id). Any consumer wired to it inherits the evidence text; the amendment must
  say so plainly rather than leaving integrators to infer it from behaviour.

## Alternatives rejected

- **Add a `steps.output` column.** The correct fix, and the one that would restore
  the original guarantee outright. It is a change to frozen migration `0004`, so it
  needs its own `contract-change` issue and ADR. Worth doing; out of scope for #60.
- **Store stage output in object storage and reference it by key.** Preserves the
  metadata-only event stream and scales better than JSONB. Introduces a second
  durability system on the resume path and a new failure mode (event committed,
  blob missing) that the current transaction boundary cannot cover.
- **Truncate and re-fetch on resume.** Would require reading canonical spans from
  `source_spans`, which the extraction package never queries today — the same gap
  as review finding P1-1. Viable only once that binding exists.

## Notes

The trade was already implemented and documented in code comments
(`events.py:1-8`, `events.py:53-81`, `persist.py:536-552`) but never reconciled with
the specification — before this ADR, `grep -rn 'stage_output' specs/ docs/ db/`
returned nothing at all. Per
`AGENTS.md`, amending `specs/**` and `packages/contracts/**` requires a
`contract-change` label and an accepted ADR, so **this ADR proposes the change and
does not make it.** No specification or contract file is edited by PR #145.
