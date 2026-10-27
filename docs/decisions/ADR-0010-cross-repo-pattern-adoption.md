# ADR-0010: Cross-repo pattern adoption from avalanche and predict-rlm

**Status:** Proposed
**Date:** 2026-08-06
**Amendment 1:** 2026-10-27 — refreshes factual premises and citations against `main`
at `59bbf7e`; changes no decision and ratifies nothing. See the end of this file.

## Context

A review of two external repositories — Trampoline AI's `avalanche` (a typed-DAG
agent workflow runtime with an operator control plane) and `predict-rlm` (a
DSPy-based recursive-LM framework with the GEPA text-component optimizer) —
identified transferable engineering patterns. This ADR proposes adopting the
patterns that fit measured gaps in this repo without violating ADR-0007's
rejection of workflow frameworks. External code is cited by repo and module path
only; no external line numbers are load-bearing.

The gaps, verified locally:

- Model-facing surfaces are mock-only and fail closed. The only providers are
  the deterministic mocks (`packages/providers/fel_providers/mocks.py`), and
  `_resolve_generation_provider` (`apps/api/app/retrieval.py:160-163`) raises on
  any pin other than `mock`. Nothing that consumes model output has been
  exercised against a live model.
- The five extraction prompts total 30 lines
  (`workers/src/fel_workers/extraction/prompts/*.v1.txt`: classifier 5,
  fact_table 4, guidance 8, kpi 8, revenue_driver 5). There is very little
  prompt text to optimize.
- `RoleSpec` already hashes instructions into checkpoint identity:
  `instructions_hash` (`workers/src/fel_workers/extraction/roles/base.py:50-51`)
  flows into the step request hash, so a changed prompt cannot silently reuse a
  checkpoint written under the old one.
- The eval gate exists but scores perfect on the controlled corpus. The smoke
  gate (`apps/api/tests/test_smoke_gate.py:5-7`) states that every gate metric
  is perfect on the seeded corpus; `SMOKE_THRESHOLDS`
  (`packages/retrieval-evals/fel_retrieval_evals/metrics.py:53-59`) therefore
  discriminates nothing yet.
- The benchmark seed is a research draft with three blocking promotion gates —
  temporal eligibility, reproducible provenance, absence coverage
  (`evals/datasets/benchmark-seed/README.md:3,118-127`).
- The extraction FSM's stage graph is stringly-typed across four hand-maintained
  structures that must agree by convention: `_dispatch_stage`
  (`workers/src/fel_workers/extraction/workflow.py:660-686`),
  `_stage_input_payload` (`workflow.py:560-590`), `_restore_output`
  (`workflow.py:593-657`), and `STAGE_ORDER`
  (`workers/src/fel_workers/extraction/types.py:29-42`), with
  `StageRecord.output: Any` (`types.py:114`) erasing every stage's output type.
- Live SSE is a replay of committed `extraction_run_events` rows; the live
  same-origin SSE proxy is deferred to issue #135.

## Decision

1. Adopt a failure taxonomy with a fixed precedence order for eval and
   extraction-run failure classification (pattern source: predict-rlm
   `telemetry.py` — twelve classes, harness failures ranked above model
   failures). Every failure is classified into exactly one class before any
   failure evidence reaches an eval report or a future optimizer, so a broken
   harness cannot be scored as a model regression. Map the taxonomy onto the
   existing typed exceptions in
   `workers/src/fel_workers/extraction/errors.py` (`BudgetExceeded`,
   `Cancelled`, `LeaseLost`, `ProviderRefused`, `ProviderError`,
   `SchemaInvalid`, `IntegrityError`, `CutoffViolation`); do not invent a
   parallel hierarchy.
2. Adopt a metric-result validation contract for eval harnesses (pattern
   source: predict-rlm `rlm_gepa/schema.py`, `validate_example_result`): every
   per-example result must carry a finite score; non-empty feedback is required
   whenever score < 1.0; errors are recorded in an explicit error field, never
   encoded as a score. Applies to `packages/retrieval-evals` and
   `evals/graders/`.
3. Adopt soft/hard dual acceptance with an exact two-sided sign test for
   release-gate comparisons once the live 65-question gate (issue #132) runs
   (pattern source: predict-rlm `rlm_gepa/runtime/acceptance.py`). Accept a
   candidate on dense-score improvement; otherwise require all of: bounded
   dense regression, net hard 0→1 flips, and sign-test p ≤ threshold. The
   acceptance function is roughly 60 dependency-free lines; reimplement it
   locally rather than importing it.
4. Refactor the extraction FSM's stage dispatch to typed stage ports: each
   stage declares its input/output dataclass and its `WorkflowState` field
   bindings once, and `_dispatch_stage`, `_stage_input_payload`, and
   `_restore_output` become tables derived from those declarations instead of
   four parallel if/elif chains. Internal refactor only. It MUST preserve:
   checkpoint identity `(run_id, step_name, input_hash, workflow_version)`
   (`workflow.py:477-489`), event-payload output carriage per ADR-0009
   (`workflow.py:528-534`), double fencing (`_boundary` at `workflow.py:334-340`
   and `_commit_fence` at `workflow.py:343-361`), and
   terminal-event-before-terminal-status ordering (`workflow.py:218-227`). No
   migration change, no contract change.
5. Adopt the descriptor/body split with explicit epochs for the future live SSE
   producer (issue #135) (pattern source: avalanche's operator gRPC contract).
   Event lists carry sequence numbers plus a body token; bodies are fetched
   separately; every response carries an instance epoch; a stale cursor or
   producer restart yields an explicit reset signal, never silent divergence.
   This is design guidance binding on the #135 implementation, not new work
   now.
6. Sequence any GEPA-style prompt optimization strictly behind three gates:
   (a) a live structured-output provider (issue #62), (b) an adjudicated
   benchmark promoted past the blocking gates in
   `evals/datasets/benchmark-seed/README.md`, and (c) prompts long enough to
   optimize. Optimized instructions must land as new versioned prompt files
   flowing through `instructions_hash` — never runtime-swapped. Constitution
   Principle II (`.specify/memory/constitution.md:18-19`) restated as the
   boundary: deterministic normalization, validation, conflict, and citation
   code is not a candidate for learned components; only role instructions are.
7. Add a design-methodology skill under `.agents/skills/` encoding a
   smallest-extension-point ladder for this repo (pattern source: both external
   repos' `.agents/skills/` methodology files): prefer, in order, a versioned
   data file, a function in an existing module, a new module in an existing
   package, and only last a new package or process.

## Consequences

- Item 1 makes failure evidence trustworthy before anything consumes it in
  aggregate; item 2 makes every eval result auditable; item 3 replaces a single
  threshold comparison with an acceptance rule that distinguishes noise from
  regression. All three, and item 7, are self-contained and need no contract
  change.
- Item 4 removes the four-way agree-by-convention coupling and gives each
  stage's output a type. It touches only `workers/src/fel_workers/extraction/`
  internals but must keep the full crash-resume and fencing suite green
  (`workers/tests/extraction/test_checkpoint_resume.py`,
  `test_resume_evidence_integrity.py`, `test_checkpoint_payload_fidelity.py`,
  `test_stage_audit_fencing.py`, `test_step_failure_record.py`).
- Item 5 costs nothing today; it binds the #135 implementation so the live SSE
  surface cannot silently diverge from the durable event rows.
- Item 6 is a sequencing gate, not new work. It prevents fitting prompts to the
  deterministic mock or to an unadjudicated draft dataset.
- No new dependency, service, or runtime framework is introduced by any item.

## Rejected alternatives

- Adopting avalanche as the extraction pipeline owner. Reaffirms ADR-0007's
  rejection of workflow frameworks: no measured need; avalanche has no
  node-level retry/resume, so the 0004 checkpoint semantics would have to be
  rebuilt on top of it; its node identity scheme conflicts with the 0004
  checkpoint index keyed on `(run_id, step_name, input_hash,
  workflow_version)`; and its default executor is sequential, so it buys no
  concurrency either.
- Depending on `rlm_gepa`/predict-rlm/DSPy as packages. predict-rlm couples
  deeply to DSPy private API under a `<3.3` pin; importing it imports that
  fragility. The acceptance function is ~60 dependency-free lines; reimplement
  it locally (decision 3).
- Running prompt optimization now, against the mock provider or the draft
  dataset. The mock returns fixtures, so the optimizer would fit prompt text to
  fixture-matching; the draft dataset has unresolved look-ahead and provenance
  gates, so gains against it are not evidence. This is fitting to fixtures,
  rejected outright (decision 6 encodes the gates).

## Verification

- Item 1: unit tests asserting every `errors.py` exception maps to exactly one
  taxonomy class and that precedence is total and deterministic.
- Item 2: unit tests over `packages/retrieval-evals` and `evals/graders/`
  asserting non-finite scores, empty feedback below 1.0, and error-as-score
  results are rejected.
- Item 3: a dedicated unit suite for the locally reimplemented acceptance
  function (sign-test exactness, boundary regressions, flip counting); first
  live use is the #132 gate.
- Item 4: the existing crash-resume and fencing suites named in Consequences
  pass unmodified, plus a test asserting the derived tables cover exactly
  `STAGE_ORDER`.
- Item 5: verified at #135 implementation time against the reset-signal and
  epoch requirements stated in decision 5.
- Item 6: enforced by review; any optimization PR must show all three gates
  cleared and must change only versioned prompt files.

## Amendment 1 — premises and citations refreshed against `main` (2026-10-27)

This ADR was written at `a25bf7c`. `main` has since moved by about seventy commits, and
several statements above no longer hold. **No decision is changed, added or withdrawn, and the
Status remains Proposed.** This amendment corrects the record so that a reader weighing the
seven decisions is not weighing stale evidence. Every claim below was re-read from `main`.

### Corrections

1. **The eval gate no longer only "scores perfect."** The Context bullet is still true of
   `apps/api/tests/test_smoke_gate.py`, but a second, discriminating gate has since merged
   (ARCH-RETRIEVAL-GATE, #201): `make eval-retrieval-gate` grades the benchmark seed through
   the retrieval pipeline. Its recorded run
   (`evals/reports/retrieval-gate/2026-09-01-synthetic-seed.json`) **fails**: `recall_at_10`
   `0.4692` against the `0.90` threshold, with `temporal_validity` at `1.0`. The cause is
   hash-based mock embeddings, which carry little semantic signal. Decision 3 therefore
   has a gate to apply to, and the acceptance rule is still gated on a live embedder (#132):
   until then CI enforces byte-identity against the committed golden, not the threshold.
2. **Decision 4's first invariant is superseded.** It tells the implementer to preserve
   "event-payload output carriage per ADR-0009". ADR-0009 is **Superseded by ADR-0011**
   (Accepted 2026-08-30). Stage output now lives on `extraction_run_steps.output`
   (migration 0006) and is read back in `persist_checkpoint.py`; the hash and the hashed
   value are written in the same `INSERT`. The invariant to preserve is now: stage output
   is carried on the step row, written atomically with its `output_hash`, and
   `(run_id, step_name, input_hash, workflow_version) WHERE status = 'succeeded'` stays the
   resume key. The other three invariants in decision 4 are unchanged.
3. **Citations moved.** Re-resolve before relying on any `file:line` in this ADR:

   | Cited above | Now |
   | --- | --- |
   | `_dispatch_stage` (`workflow.py:660-686`) | `workflow.py:382` |
   | `_stage_input_payload` (`workflow.py:560-590`) | `workflow.py:339` |
   | `_restore_output` (`workflow.py:593-657`) | `workflow_codec.py:23` |
   | `_boundary` / `_commit_fence` (`workflow.py:334-361`) | `workflow.py:213` / `workflow.py:222` |
   | `STAGE_ORDER` (`types.py:29-42`) | `types.py:55` |
   | `StageRecord.output: Any` (`types.py:114`) | `types.py:140` |

4. **Decision 5's premise is partly overtaken.** A live extraction event stream now exists
   (`apps/api/app/extraction/routes_events.py`): it resumes from a `Last-Event-ID` cursor and
   polls committed rows. It has no instance epoch, no reset signal and no descriptor/body
   split, so the decision stands as design guidance for any change to that stream; the
   replay-only description of retrieval-run events in the Context is unchanged.
5. **Decision 6's gates have moved unevenly.**
   - (a) Explicit-key OpenAI structured-generation and embeddings adapters merged
     (#328, #329), but the provider decision (#195, ADR-0012) is still Proposed, there is no
     live smoke, and M3-CONFIDENCE-GATE (#62) still depends on M3-REVIEW and
     RELEASE-LIVE-CUTOVER. This gate is **partly** open, not cleared.
   - (b) The benchmark seed is unchanged: all 65 records are `draft`.
   - (c) The five prompts still total 30 lines.

   The decision's conclusion, that no optimization runs until all three clear, is unaffected.

### Unchanged since the original text

Decisions 1, 2 and 7 have no implementation on `main`: `errors.py` still defines the same
ten classes (`ExtractionError`, `StepFailed` and the eight below it), `evals/graders/` still
holds only `exact_match.py`, and `.agents/skills/` holds the ten `speckit-*` skills. Decision 4's
four-way structure also stands: `STAGE_ORDER`, `_dispatch_stage`, `_stage_input_payload` and
`_restore_output` remain separate hand-maintained structures.

### Registration

Decisions 1, 2, 4 and 7 need no contract change and no external dependency. They are
candidates for work packages, but `docs/handoff/workstreams.yaml` is integration-lead
owned and this amendment does not edit it. Registering them, or rejecting them, is a lead
decision.
