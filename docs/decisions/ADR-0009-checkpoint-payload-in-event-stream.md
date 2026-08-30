# ADR-0009: `step_completed.stage_output` carries evidence text, and the event stream is not metadata-only

Status: Superseded by ADR-0011
Date: 2026-07-29
Revised: 2026-08-03 — four corrections required by the integration-lead review of
PR #145 (`7f11bab..a08ba50`). See "Revision history".
Superseded: 2026-08-30 by integration lead on PR #175
Occasioned by: M3-EXTRACTION-CORE (#60), PR #145 review finding P1-8.2
Amends: the event-payload guarantee in `specs/003-agentic-extraction/data-model.md`,
`specs/003-agentic-extraction/contracts/extraction-api.yaml`,
`specs/003-agentic-extraction/spec.md`, **and `packages/contracts/**`** — see
"Contract-version question".

## Context

The metadata-only guarantee is stated in **six** places across two governance
tiers. The first three are internal spec text; the last three are the **frozen,
published contract**, which the first draft of this ADR missed:

- `data-model.md:23` — "Payload contains IDs/counts/status, **never evidence or prompt text**."
- `contracts/extraction-api.yaml:180` — "IDs, counts, states and redacted errors only; **no source or prompt text**."
- `spec.md:180` — "No source text or secrets in logs; prompts and raw provider outputs are stored only in approved encrypted/object storage or hashed/redacted fields."
- `packages/contracts/openapi/openapi.yaml:2012` — "IDs, counts, states and redacted errors only; no source or prompt text."
- `packages/contracts/schemas/extraction-event.schema.json:36` — the same sentence, on the `payload` property.
- `packages/contracts/src/generated/api.ts:1070` — the same sentence again, in the **shipped generated client**, so it is already in consumers' hands.

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

## Contract-version question (open; must be answered by the amending PR)

`packages/contracts` is at **0.4.0**, and `VERSIONING.md:21-22` classifies
"changing the meaning of an existing field (including unit/scale/temporal
semantics)" as a **breaking change (major bump)**. Restating `payload` from "no
source text" to "source text on `step_completed`" changes what an existing field
is guaranteed to contain for a consumer who wrote code against the shipped
client.

This ADR does not resolve major-vs-minor; it records that the question exists and
belongs to whoever lands the amendment. Two defensible readings:

- **Minor (0.5.0)** — the sentence is prose, not schema. No type, format,
  `required` set, or enum changes; a conforming consumer's parsing is unaffected.
- **Major (1.0.0)** — the sentence *is* the guarantee. A consumer who provisioned
  the event stream as a low-sensitivity metadata feed on the strength of it now
  has a materially different object, and no schema diff would warn them.

Recorded for the amending PR to argue with rather than inherit: the integration
lead's view is **minor, with a mandatory changelog callout** — the
machine-readable contract is unchanged, and a major bump for every prose
correction makes the version number stop carrying information. The callout is not
optional, because a consumer diffing schemas gets no other signal.

## Decision

Accept that a `step_completed` event's `stage_output` carries pinned span text and
stage payloads **verbatim**, and amend the six documents above to describe the
actual, bounded guarantee:

1. **The exemption is total inside `stage_output`, and positional.** No key-based
   rule applies within that subtree — not truncation, and not substitution. This
   is narrower than the first draft of this ADR claimed, and deliberately so: two
   successive attempts to scope the carve-out by field name both corrupted the
   checkpoint. First only `text` was exempt, so `definition` / `description` prose
   was still truncated; then truncation was suppressed wholesale but substitution
   was not, so a `qualifiers` or `dimensions` key an issuer happened to name
   `token`, or a payload field named `raw`, was replaced with `"[redacted]"` and
   broke `raw_payload_hash` (PR #145 review M4). `dimensions` and `qualifiers`
   carry issuer-supplied keys with arbitrary names, so no per-key rule can be
   made correct here — the check has to be *where the data sits*, not *what it is
   called*.

   This costs nothing in secret exposure. `serialize_stage_output` serializes one
   stage's return value: evidence blocks, classification, candidates, normalized
   payloads. Provider credentials and prompts are never part of a stage's return —
   they live on the provider call — and `model_step`, which does carry per-attempt
   request hashes, is a **sibling** of `stage_output`, not inside it, so it is
   still redacted normally. **Prompts, provider messages, and secrets outside that
   one subtree are stripped everywhere, unconditionally.**
2. **The exemption is enforced by event type, not inferred from a key name.**
   `redact_event_payload(payload, *, event_type)` grants it only when
   `event_type == "step_completed"`, and only to the top-level `stage_output` key —
   the sole place `workflow` writes it. The first draft asserted this scoping while
   the code keyed on the string `"stage_output"` alone and was event-type-agnostic;
   the code now matches the claim, verified by
   `test_stage_output_exemption_is_scoped_to_step_completed`.
3. **Event and log redaction are separate functions, so the log sink cannot
   inherit the exemption.** The justification above rests on properties a log line
   does not have: an org-scoped, RLS-protected durable row that a resume reads
   back and re-hashes. Process stdout is neither tenant-scoped nor rehydrated, so
   the same text there would be a real leak rather than a bounded false guarantee
   (`spec.md:180`, `workers/src/fel_workers/extraction/OPERATOR.md:16`). `telemetry.emit` therefore
   calls `redact_log_payload`, which has no exemption and takes no parameter that
   could grant one. Previously both sinks shared one function and telemetry was a
   single `stage_output` field away from logging filing text.
4. Every other event payload remains IDs, counts, states and redacted errors.

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
- **Truncate and re-fetch on resume.** Rejected, but **not** for the reason the
  first draft gave. That draft said extraction "never queries `source_spans`
  today" — which was already false at the commit this ADR ships on:
  `handler.py:263-304` verifies supplied evidence against the canonical
  `source_spans` rows before the first write, `persist.py:82` loads those rows, and
  a full re-fetch path exists in `apps/api/app/reader.py`. The binding this
  alternative was said to be waiting on already exists.

  The decision survives the correction, on the narrower ground that actually
  holds: only **pinned span text** is re-fetchable. `stage_output` also carries
  `state.classification`, `state.candidates`, `state.raw_proposals` and
  `state.normalized` — model-derived output with no canonical row to read back.
  Re-fetching would restore the evidence and lose the extraction, so the resume
  would have to re-run the model calls `spec.md:61` exists to avoid paying twice.
  A hybrid (re-fetch spans, keep model output verbatim) is real but only shrinks
  the exempt subtree; it does not remove it, so it does not restore the
  metadata-only guarantee and is not worth the second code path today.

## Revisit triggers

- **Any non-public document source is ingested** (upload, private-document, or a
  non-EDGAR corpus producer). The bounded-exposure argument in Consequences rests
  entirely on every corpus byte being public SEC filing text. This trigger is
  mandatory, not advisory.
- **#61 exposes the SSE surface.** Today no API reads `extraction_run_events`; the
  moment a consumer is wired to the stream, the false published guarantee becomes
  a guarantee someone is relying on. The amendment must land before that PR does.
- **A `steps.output` column is added** (the follow-up this ADR names as the
  correct fix). That restores the original guarantee outright and retires this ADR
  rather than amending it.
- **The redaction helpers are merged back into one**, or `redact_log_payload`
  acquires a parameter that can grant the exemption. Decision point 3 is the only
  thing keeping filing text out of unRLS'd logs.

## Revision history

- **2026-07-29** — first draft, Proposed.
- **2026-08-03** — four corrections required by the integration-lead review of PR
  #145 before ratification: (1) `Amends:` extended to `packages/contracts/**`,
  where the same guarantee ships in the generated client, with the
  major-vs-minor question posed rather than assumed; (2) Decision point 1
  rewritten — the exemption is total and positional inside `stage_output`, which
  is what the code now does after review finding M4, where the draft claimed
  key-based redaction still applied there; (3) Decision point 2's event-type
  scoping made true in code rather than asserted, and the event/log helpers split
  so telemetry cannot inherit the carve-out; (4) the "truncate and re-fetch"
  rejection re-argued, since its stated premise (extraction never queries
  `source_spans`) was false at the commit it shipped on. Added named revisit
  triggers per the ADR-0006/0008 convention.

## Notes

The trade was already implemented and documented in code comments
(`events.py:1-8`, `events.py:53-81`, `persist.py:536-552`) but never reconciled with
the specification. Before this ADR, `grep -rn 'stage_output' specs/ docs/ db/`
returned nothing — but that grep omitted `packages/`, which is how the three
published-contract locations above were missed on the first pass. Per
`AGENTS.md`, amending `specs/**` and `packages/contracts/**` requires a
`contract-change` label and an accepted ADR, so **this ADR proposes the change and
does not make it.** No specification or contract file is edited by PR #145.
