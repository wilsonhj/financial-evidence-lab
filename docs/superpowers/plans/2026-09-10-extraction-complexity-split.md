# Issue 196 Extraction Split Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task under the lead's dispatch. This document authorizes no additional agent dispatch and contains no implementation changes.

**Goal:** Mechanically separate extraction control, stage bodies, checkpoint handling and stores while preserving the unchanged test suite, persisted outputs, hashes and execution ordering.

**Architecture:** Retain `workflow.py` as the control and compatibility module, and retain `persist.py` as the Postgres proposal/run store and compatibility module. Move existing bodies into small one-way dependency modules, without new behavior or a generic dispatch framework.

**Tech Stack:** Existing Python 3.11, dataclasses, psycopg and current package dependencies only.

**Spec:** GitHub issue https://github.com/wilsonhj/financial-evidence-lab/issues/196 (current body fetched September 10, 2026), repository `AGENTS.md`, `.specify/memory/constitution.md`, canonical `specs/001-financial-evidence-lab/{spec,plan,tasks}.md`, `docs/handoff/{README.md,workstreams.yaml}`, and accepted ADR-0019 / ADR-0022.

## Baseline and dispatch boundary

This read-only design inspected `/private/tmp/fel-impl-154` at `29fccf2`, the supplied final #154 source revision. It did not modify that worktree or the dirty primary checkout. Source correctness/CI and the actual #154 merge remain lead gates; this design is not a merge claim.

After #154 merges, create the #196 worktree from current main containing its final reviewed changes. The registered branch is `agent/arch-complexity-split`. The wave 6 control PR registers this bounded extraction-only dispatch under ADR-0017. Its exact path list excludes active #191. Dispatch base is merged #154 at `3fbc8ac`; the earlier design snapshot differs only in integration history.

Do not touch API retrieval until #191 has merged and its final API head is the base. Extraction completion is only part of #196. The API half needs its own post-#191 inventory and independent review; do not close #196 after this extraction split.

Issue acceptance says “No source file over ~500 lines in these two areas” and “Test suite and goldens unchanged.” The extraction inventory at this revision is:

| File | Lines | Handling |
| --- | ---: | --- |
| `extraction/workflow.py` | 1,111 | Split below |
| `extraction/persist.py` | 1,028 | Required bounded split below, not an omitted residual |
| `extraction/validate/accounting.py` | 510 | Existing near-500 file; explicitly report as within the issue's approximate threshold. Do not modify financial logic or trim comments to manufacture compliance. If the lead requires a strict 500-line cap across the entire subtree, this remains a separately registered mechanical extraction, and strict completion must not be claimed. |
| `extraction/handler.py` | 422 | Unchanged |

`ingestion/company_facts.py` is mentioned in the finding but lies outside both proposed refactor areas and the extraction allowed paths; it is not part of this dispatch.

## Global constraints

- No financial logic, SQL text/parameters, normalization, citation grading, error taxonomy, redaction, conflict identity or namespace changes.
- No dependency/lock/config changes, database migrations, contracts, version bumps, provider changes or root/shared files.
- Preserve `WORKFLOW_VERSION=extraction-workflow/v3`, `NORMALIZER_VERSION=normalize/v2`, `VALIDATOR_VERSION=validate/v3`, `RANGE_POLICY_VERSION=guidance-range-order/v1`, and existing `UNIT_POLICY_VERSION=unit-comparison/v1` and their hashing boundaries.
- Preserve stage ordering, mode skipping, function signatures, constructor field ordering/defaults, dataclass identity through re-exports, and all existing test imports/patch targets.
- Do not rewrite tests to follow moved internals. No golden regeneration, new fixture expectations, deleted/renamed tests or weakened assertions. Existing tests are the regression contract.
- `hashing.py`, `serialize.py`, `types.py`, `normalize/**`, `validate/**`, `roles/**`, prompts, schemas and vendored contracts stay byte-identical in this dispatch.

## Exact implementation paths

All paths below are relative to `workers/src/fel_workers/extraction/`. Modify only:

- `workflow.py`
- `persist.py`

Create only:

- `workflow_context.py`
- `workflow_checkpoint.py`
- `workflow_codec.py`
- `stages/__init__.py`
- `stages/validate_request.py`
- `stages/assemble_evidence.py`
- `stages/model.py`
- `stages/normalize.py`
- `stages/validate.py`
- `stages/verify_citations.py`
- `stages/detect_conflicts.py`
- `stages/persist_proposals.py`
- `persist_types.py`
- `persist_memory.py`
- `persist_checkpoint.py`
- `persist_events.py`
- `persist_reads.py`

Tests remain read-only, including every file under `workers/tests/**`. No changes to `handler.py`, `consumer.py` or package `__init__.py` are needed because the compatibility imports remain valid. New subpackages are already discovered by the existing setuptools configuration.

## Task 1: Extract stage bodies and dependencies, retaining original seams

- [ ] Record the actual merged base and run the baseline checks below before editing.
- [ ] Move `CheckpointStore`, `EventStore`, `PersistStore`, `WorkflowDeps`, `_ModelStepAudit` and `_ExecCtx` verbatim from workflow into `workflow_context.py`. Keep default factories and field ordering unchanged. Re-export the exact class objects from workflow, using explicit `as SameName` imports for static tooling.
- [ ] Move `_stage_validate_request`, `_stage_assemble_evidence`, `_stage_normalize`, `_stage_validate`, `_stage_verify_citations`, `_stage_detect_conflicts` and `_stage_persist` into their corresponding stage files with their existing signatures. The file name `persist_proposals.py` does not rename `_stage_persist`.
- [ ] Move `_stage_model` and `_evidence_dicts` together to `stages/model.py`. The five role stages already share this one implementation; retain that sharing. Do not duplicate the body into five role modules or add a new registry. Preserve exact role selection in workflow's existing `_dispatch_stage` chain.
- [ ] Move `_restore_output` and `evidence_map` to `workflow_codec.py`; re-export both in workflow. Stage validation/citation modules import `evidence_map` from the codec. Restore must still call `validate_proposals` exactly as before, including its existing default-ontology behavior; passing `ctx.ontology` on restore would be an unrelated behavior change.
- [ ] Move `_is_recoverable`, `_reject_checkpoint`, `_commit_stage`, `_record_stage_failure` and `_record_usage` to `workflow_checkpoint.py`, preserving existing signatures and bodies. Both workflow and `stages/model.py` import the same `_record_usage` function from this module.
- [ ] Explicitly re-export every moved workflow-defined function/class at its old name. Preserve workflow's existing `__all__` content. Keep `_dispatch_stage`, `_run_stage`, `_stage_input_payload`, `_mark_skipped`, `_boundary`, `_commit_fence`, `_should_skip_mode_stage`, `_normalize_blocked_count`, `_finalize_success` and `run_extraction_workflow` physically defined in workflow.

Retained control bodies total roughly 366 lines before imports/spacing; workflow should finish around 450–490 lines without shortening its safety comments. The context/codec/checkpoint modules are roughly 140/100/250 lines, and each stage module is comfortably below 150.

### Tested seams that determine this layout

| Existing seam | Existing coverage | Required preservation |
| --- | --- | --- |
| `workflow._dispatch_stage` and `workflow._commit_stage` | `test_postgres_crash_resume.py`, unit/range policy crash hooks | `_run_stage` remains in workflow and looks up both workflow globals on every call. An imported alias for `_commit_stage` is sufficient only because the caller remains here. |
| `workflow.UNIT_POLICY_VERSION`, `RANGE_POLICY_VERSION`, `NORMALIZER_VERSION`, `VALIDATOR_VERSION` | `test_workflow.py` policy/component hashing tests | `_stage_input_payload` and those global bindings remain in workflow. Do not capture them in helper defaults or move hash payload construction behind a re-export. |
| `_restore_output` direct import | `test_resume_evidence_integrity.py` | Same function/signature exported from workflow. |
| `_stage_verify_citations` direct import | `test_citation_status_integrity.py` | Same function/signature exported from workflow. |
| `WorkflowDeps`, `_ExecCtx`, `_stage_persist` direct import | `test_persist_stage_is_atomic.py` | Same constructors and callable exported from workflow. |
| Existing handler/package imports | `handler.py`, extraction `__init__.py`, consumer integration suites | Keep public surface unchanged; no importer migration. |

Do not move `_run_stage` to a helper then leave only a re-export: its global resolution would silently bypass the existing crash hooks. Do not repair the resulting test failures by changing patch paths.

### State/hash and ordering invariants

`hashing.py` remains the sole hash primitive implementation. Workflow retains all stage input payload construction and `stage_input_hash` calls, including skipped stages. `_run_stage` must hash the exact `serialize_stage_output(output)` value it stores. Stage modules emit no independently constructed stage keys. The codec only restores state; it does not salt hashes or repin versions.

Preserve these sequences literally:

1. Load carried usage and emit start; reject unsupported workflow version before any checkpoint load.
2. Stage boundary: lease, cancellation, wall cap; skipped-stage identity and ordering unchanged.
3. Checkpoint recovery verifies serialized-output hash; rejection records the same reason/action and invokes the same optional `reject_loaded` hook before rerun.
4. New stage starts, clears model audit, dispatches, records failures under the same `BaseException` boundary, serializes/hashes, re-fences lease/cancel, commits, then increments/injects crash.
5. Model usage deltas/attempts/accepted response ID and per-attempt request hashes stay unchanged; usage is recorded at the same call boundary.
6. The usage `finally` occurs before terminal status writes and only while leased. Typed failures/cancellation append their event before terminal status. Untyped errors retain their re-raise. `waiting_review` remains non-terminal and retains its existing status-then-event sequence.
7. Proposal persistence keeps its extra lease check and one atomic proposals/evidence/conflicts/event transaction; the `needs_review` assertion stays inside the Postgres transaction as well as the stage's existing assertion.

## Task 2: Bound persistence without breaking ownership patching

A wholesale `persist.py` re-export of a moved Postgres class is unsafe: `test_review_fixes.py` and `test_conflict_resolution_reuse.py` patch `fel_workers.extraction.persist.assert_workspace_ownership`. Its method globals must still resolve that binding.

- [ ] Keep `PostgresPersistStore`, `assert_workspace_ownership`, `persist_proposals`, `persist_conflicts` and `persist_outputs_atomic` in `persist.py`. Keep `persist_proposals` and `persist_conflicts` calling the module-global ownership function, not a captured callable or a separately imported helper.
- [ ] Move `UsageSnapshot`, `RunPins`, `SpanPin`, `TERMINAL_RUN_STATUSES`, `RunAlreadyTerminal` and `_ensure_needs_review` to `persist_types.py`, retaining class fields, exception code/message and identity. Re-export their existing names from persist.
- [ ] Move the complete `MemoryPersistStore`, `PostgresCheckpointStore` and `PostgresEventStore` classes, each without internal rewrites, into `persist_memory.py`, `persist_checkpoint.py` and `persist_events.py`. Re-export the exact class objects from persist; preserve its original `__all__`.
- [ ] To keep persist below 500 even with compatibility imports, extract just the two read bodies `load_run_pins` and `load_span_pins` into `persist_reads.py` as `load_run_pins(conn, *, run_id, org_id)` and `load_span_pins(conn, span_ids)`. Keep methods with their old signatures on `PostgresPersistStore` that delegate with `self.conn`. The helpers return the existing `RunPins | None` and `dict[str, SpanPin]`. Move their SQL literals, argument order and conversions verbatim, replacing only `self.conn` with `conn`.
- [ ] Keep `_load_wall_seconds`, run status and usage methods in the public Postgres class; do not introduce mixins, dynamic method attachment or a generic store abstraction.

The original Postgres class is 452 lines; extracting the two read bodies removes about 65 net lines. After imports, compatibility exports and ownership helper, persist should be below 480. The checkpoint class is 289 lines; other new store files remain below 170.

The checkpoint `_loaded`/`_rejected` identity bookkeeping, owner-preserving `(id, xmin)` compare-and-swap, failed-attempt allocation, `checkpoint_superseded` exceptions, transaction boundaries and cache reset timing must move together unchanged. `PostgresEventStore` must preserve its current memory append followed by SQL insert and the exact redaction call. Do not improve either sequence during the refactor.

## Module graph and cycle check

The dependency direction is:

- `workflow` → context, checkpoint helpers, codec, stages, existing hashing/serialization/types/errors.
- `stages.model` → context + checkpoint helpers + existing role/runner modules.
- Other stages → context/types + codec as required + existing normalize/validate modules.
- `workflow_checkpoint` → context + existing hashing/serialization/telemetry/errors; it imports no workflow or stages.
- `workflow_codec` → existing types/hashing/validate; it imports no workflow, context or stage module.
- `workflow_context` → existing budget/providers/ontology + default memory stores through persist/checkpoint/events; it imports no workflow/helper/stage module.
- `persist` → persist types/reads/memory/checkpoint/events; these leaves depend on existing types/errors/events/checkpoint/hashing and never import persist or workflow/context/stages.

There is no back edge to a facade and no module import of workflow from a stage. Keep `stages/__init__.py` minimal. Do not use local imports or `sys.modules` lookups merely to conceal a circular dependency. Public re-exports preserve shared class identity (`is`, subclassing and class-method monkeypatches), rather than constructing wrapper classes.

## Baseline and verification commands

Run from the isolated worktree. Reuse `/private/tmp/fel203-dev/bin/python` (observed Python 3.11.16) or the original project's Python 3.11 venv; do not reinstall or alter root dependencies. Capture the actual base SHA before edits with `git rev-parse HEAD` and use that value as `BASE` for subsequent diff checks.

Design-time check executed on unmodified `29fccf2`:

```sh
PYTHONDONTWRITEBYTECODE=1 /private/tmp/fel203-dev/bin/python -m pytest -p no:cacheprovider workers/tests/extraction/test_workflow.py workers/tests/extraction/test_resume_evidence_integrity.py workers/tests/extraction/test_citation_status_integrity.py workers/tests/extraction/test_persist_stage_is_atomic.py workers/tests/extraction/test_review_fixes.py workers/tests/extraction/test_conflict_resolution_reuse.py
```

Result: **37 passed in 0.05s**. This is a seam/import baseline only, not PostgreSQL acceptance. No database test was executed by this read-only design task.

Before and after each extraction step, run the same complete extraction suite with the same already provisioned disposable migrated PostgreSQL. The test fixtures create their extraction test database; never point this at a hosted production database. Use an inherited `TEST_DATABASE_URL`, without printing it:

```sh
: "${TEST_DATABASE_URL:?A disposable migrated PostgreSQL is required}"
FEL_REQUIRE_DB=1 /private/tmp/fel203-dev/bin/python -m pytest workers/tests/extraction packages/ontology/tests
```

Record passed/failed/skipped counts and investigate any change; a no-DB run with skips is not a replacement. This includes durability, concurrent repair, corrupt checkpoints, atomic rollback, terminal event order, budget carryover, lease/cancel fencing, v1/v2 rejection, v3 range crash-resume, redaction, ownership and conflict reuse.

After the complete split, broaden once to existing whole worker and cross-package checks:

```sh
FEL_REQUIRE_DB=1 /private/tmp/fel203-dev/bin/python -m pytest workers/tests packages/ontology/tests packages/providers/tests
/private/tmp/fel203-dev/bin/python -m ruff check workers/src/fel_workers/extraction
/private/tmp/fel203-dev/bin/python -m black --check workers/src/fel_workers/extraction
/private/tmp/fel203-dev/bin/python -m mypy workers/src/fel_workers
```

Run current required CI on the final PR head, including full Python coverage, security lint, migrations and runtime packaging checks. The original CI commands live in `.github/workflows/ci.yml`; do not edit them or lower coverage thresholds for the refactor. Check package installation/imports through that existing runtime job, since new Python modules must ship in the worker wheel.

Review the diff mechanically and enforce untouched tests/financial modules:

```sh
git diff --check
git diff --stat "$BASE"
git diff --exit-code "$BASE" -- workers/tests apps/api/tests packages/ontology/tests packages/providers/tests evals/tests workers/src/fel_workers/extraction/types.py workers/src/fel_workers/extraction/hashing.py workers/src/fel_workers/extraction/serialize.py workers/src/fel_workers/extraction/normalize workers/src/fel_workers/extraction/validate workers/src/fel_workers/extraction/roles workers/src/fel_workers/extraction/prompts workers/src/fel_workers/extraction/schemas workers/src/fel_workers/extraction/contracts
git diff --color-moved=zebra --color-moved-ws=allow-indentation-change "$BASE" -- workers/src/fel_workers/extraction
/private/tmp/fel203-dev/bin/python - <<'PY'
from pathlib import Path
for p in sorted(Path('workers/src/fel_workers/extraction').rglob('*.py')):
    count = len(p.read_text().splitlines())
    if count > 500:
        print(f'{count}: {p}')
PY
```

Expected extraction size report: only the unchanged 510-line `validate/accounting.py`, explicitly recorded under the issue's approximate threshold. Review all newly created files as well as tracked diff output before commit; ensure only the exact allowlist changed. Confirm moved SQL string constants and parameter tuples are unchanged and move-only function bodies differ only in import binding or the two stated `self.conn` substitutions.

## Review and completion evidence

- [ ] Source reviewer confirms original public/private test imports and monkeypatch behavior, no import cycles, centralized stage hashes and exact SQL/ordering preservation.
- [ ] All existing tests/goldens remain byte-identical; baseline/final counts and DB-enabled evidence are reported.
- [ ] Final diff touches only the listed extraction files, all new files are included, and final head CI passes.
- [ ] PR explicitly says “extraction portion of #196”; report the untouched 510-line accounting file and API/#191 sequencing. Do not use an automatic closing reference for #196 until the API portion also meets its acceptance.
- [ ] Lead registers/merges the bounded extraction work and schedules the API refactor only after #191's reviewed merge. No task ledger completion or live provider readiness is implied.
