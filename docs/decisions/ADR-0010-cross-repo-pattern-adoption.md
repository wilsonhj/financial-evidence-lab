# ADR-0010: Cross-repo pattern adoption from avalanche and predict-rlm

**Status:** Proposed
**Date:** 2026-08-06

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
