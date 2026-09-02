"""Golden checkpoint hashes for a pinned fixture run (issue #196).

The checkpoint is content-addressed: a stage is resumed from the row keyed
``(run_id, step_name, input_hash, workflow_version)``, and ``output_hash`` is
what a resume re-verifies the restored payload against
(``workflow._is_recoverable``). Both digests are derived from code — the payload
``stages.io.stage_input_payload`` builds, and the value
``serialize.serialize_stage_output`` produces — so an innocuous-looking edit to
either can silently move every key. Nothing else fails when that happens: the
run simply re-executes every stage from scratch, at full model cost, and every
checkpoint already written for in-flight runs is orphaned. The old rows cannot
be repaired either — 0004 forbids UPDATE on a terminal run and DELETE outright.

So the digests are pinned here, byte for byte, for one fully deterministic
fixture run through the mock provider on memory stores. The values below were
captured before the ``extraction/stages/`` split and must not change with any
behaviour-preserving refactor.

Moving them is a deliberate act with a migration cost, not a side effect. If a
change genuinely must alter what a stage contributes to its input hash or what
it stores as output, bump ``WORKFLOW_VERSION`` — the version is part of the key,
so a bump partitions old rows from new ones instead of colliding with them — and
update this file in the same commit, with the reason in the message.
"""

from __future__ import annotations

from typing import Any

import pytest

from fel_providers.mocks import MockStructuredLLMProvider
from fel_workers.extraction.handler import handle_extraction_run
from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.types import STAGE_ORDER, WORKFLOW_VERSION, WorkflowState

# Every id is pinned: `run_id` is hashed into every stage's input hash, so a
# `uuid4()` fixture would make these digests unreproducible.
_RUN_ID = "aaaaaaaa-0000-4000-8000-000000000001"
_ORG_ID = "aaaaaaaa-0000-4000-8000-000000000002"
_WORKSPACE_ID = "aaaaaaaa-0000-4000-8000-000000000003"
_POLICY_ID = "aaaaaaaa-0000-4000-8000-000000000004"
_CORPUS_VERSION_ID = "aaaaaaaa-0000-4000-8000-000000000005"
_ENTITY_ID = "11111111-1111-4111-8111-111111111111"
_SPAN_ID = "22222222-2222-4222-8222-222222222222"
_DOC_VERSION_ID = "33333333-3333-4333-8333-333333333333"
_TEXT = "ARR was $100 million as of June 30, 2026."

# step_name -> (status, input_hash, output_hash)
GOLDEN_STAGE_HASHES: dict[str, tuple[str, str, str | None]] = {
    "validate_request": (
        "succeeded",
        "sha256:38938fa9cc4cda526de965a8150e695b94d45f110c1c9d2f36208765f5f7ef61",
        "sha256:5374ffeb4574a68829ca367e688949a33d5c3cf800416d9f82da6d63a5ec8564",
    ),
    "assemble_evidence": (
        "succeeded",
        "sha256:7dfb914d1eacf39f9889887808e7ae47983a4508ff1263cc7ba7da9ccdb3e580",
        "sha256:e39367edbad570c3816ca3110897b434bd3f14df5a8c8466122e45aefcc77b1a",
    ),
    "classify": (
        "succeeded",
        "sha256:544fe3b130a311a21e403c81609d929585f99c920ebd8d4bb7a77ef1021fd8ed",
        "sha256:431df380f42f19ac6e278ac14af5d0efd456476ae829a34721d4d151ce329761",
    ),
    "collect_candidates": (
        "succeeded",
        "sha256:1572fa41feb0713fc02a9a1cc68ada6ae6438e4df234482ae94b94fc34e6480f",
        "sha256:335bc1e8a26c2f95ab481e5dac106f41ac82fb321533262ab461ee1e23dcf51d",
    ),
    "extract_kpi": (
        "succeeded",
        "sha256:a5fdb245f852a51356abb4f5e32f001ff7f184864cea060ad708836c83f31ad3",
        "sha256:bc76bde8ad19a56880e39e93365e7c3bc1f60c3214d052d444a158023dbe99fd",
    ),
    # Not in `modes`: skipped stages still get a stable input hash, and it is
    # keyed on the same tuple, so it is pinned like the rest.
    "extract_guidance": (
        "skipped",
        "sha256:20ef63db22f07f19b27352be364e1a756bb522e706aea45325f5afed93ae00b2",
        None,
    ),
    "extract_revenue_driver": (
        "skipped",
        "sha256:fc24356f0924495bcc77a7dbb52bb2f3c868f661030d3639edcb1c1e9dd51fb4",
        None,
    ),
    "normalize": (
        "succeeded",
        "sha256:62bcd71ebe977678075405c53952acc2f8e5bfd1421611d3193af7f645aca467",
        "sha256:b3dd223919cd1383af5e7ad29d06bfb5b157b6ebaa5df3bc2c53427970e61b50",
    ),
    "validate": (
        "succeeded",
        "sha256:1744f85ebc09c49ef117ea32d3455a0bd6fe3ced5481bbfe917236981b203994",
        "sha256:92921b1bd53a62618f19d6222c50c1119d0eaf84a3cdc29a42f6c382b515f24a",
    ),
    "verify_citations": (
        "succeeded",
        "sha256:b038750cad130b4d8391a43d205ff59d76b464a59c49232864256123665399f7",
        "sha256:41df693aa4cbb32329a4c93f8cc2e73c4e1d9faafe43c3a0be65d054ad3ea2df",
    ),
    "detect_conflicts": (
        "succeeded",
        "sha256:89fa4ac09f8b406d84f669e43808b8433f85875c9bfd430a5afd6c875c8fae30",
        "sha256:91bc3064296baeee9d1db676f5b0b527ca7a8a50d041832b651c5022cec9233e",
    ),
    "persist_proposals": (
        "succeeded",
        "sha256:cba3799581c2401c75464b1629123513fff59a0d409a9394314f99259095febc",
        "sha256:da198a79a7b52f454a69324c83b5577c7129fe18313961fef217df51ce6d4a95",
    ),
}


def golden_payload() -> dict[str, Any]:
    """The pinned fixture run. Every value here is part of the golden digests."""
    return {
        "run_id": _RUN_ID,
        "org_id": _ORG_ID,
        "workspace_id": _WORKSPACE_ID,
        "entity_id": _ENTITY_ID,
        "policy_id": _POLICY_ID,
        "corpus_version_id": _CORPUS_VERSION_ID,
        "modes": ["kpi"],
        "as_of": "2026-07-01T00:00:00+00:00",
        "ontology_version": "saas-metrics/v1",
        "workflow_version": WORKFLOW_VERSION,
        "provider": "mock",
        "model": "mock-structured-v1",
        "input_manifest": {"source_span_ids": [_SPAN_ID]},
        "issuer_label": "Example SaaS",
        "evidence": [
            {
                "source_span_id": _SPAN_ID,
                "document_version_id": _DOC_VERSION_ID,
                "text": _TEXT,
                "text_hash": sha256_hex(_TEXT),
                "published_at": "2026-06-30T00:00:00+00:00",
            }
        ],
    }


@pytest.fixture()
def golden_run() -> WorkflowState:
    """One full mock run on memory stores — no database, no network."""
    state = handle_extraction_run(
        None,
        MockStructuredLLMProvider(),
        golden_payload(),
        use_memory_stores=True,
    )
    assert state.error is None, state.error
    return state


def test_workflow_version_is_pinned() -> None:
    """The version is part of the checkpoint key; bumping it invalidates the goldens."""
    assert WORKFLOW_VERSION == "extraction-workflow/v1"


def test_stage_order_is_pinned() -> None:
    """A reordered or renamed stage changes which key a resume looks under."""
    assert STAGE_ORDER == (
        "validate_request",
        "assemble_evidence",
        "classify",
        "collect_candidates",
        "extract_kpi",
        "extract_guidance",
        "extract_revenue_driver",
        "normalize",
        "validate",
        "verify_citations",
        "detect_conflicts",
        "persist_proposals",
    )
    assert set(GOLDEN_STAGE_HASHES) == set(STAGE_ORDER)


def test_golden_run_reaches_waiting_review(golden_run: WorkflowState) -> None:
    """The goldens describe a run that got all the way through, not a truncated one."""
    assert golden_run.status == "waiting_review"
    assert golden_run.validated
    assert list(golden_run.stages) == list(STAGE_ORDER)


@pytest.mark.parametrize("step_name", list(STAGE_ORDER))
def test_stage_hashes_match_the_golden(golden_run: WorkflowState, step_name: str) -> None:
    """Every stage's checkpoint key and output digest, byte for byte."""
    status, input_hash, output_hash = GOLDEN_STAGE_HASHES[step_name]
    record = golden_run.stages[step_name]
    assert record.status == status
    assert record.input_hash == input_hash, (
        f"{step_name} input_hash moved: the checkpoint key "
        f"(run_id, step_name, input_hash, workflow_version) no longer matches any "
        f"row written by an earlier version. See this module's docstring."
    )
    assert record.output_hash == output_hash, (
        f"{step_name} output_hash moved: a resume would reject every checkpoint "
        f"written by an earlier version. See this module's docstring."
    )


def test_hashes_are_reproducible_across_runs() -> None:
    """Two runs of the same fixture agree — the goldens pin code, not one execution."""
    first = handle_extraction_run(
        None, MockStructuredLLMProvider(), golden_payload(), use_memory_stores=True
    )
    second = handle_extraction_run(
        None, MockStructuredLLMProvider(), golden_payload(), use_memory_stores=True
    )
    assert {n: (r.input_hash, r.output_hash) for n, r in first.stages.items()} == {
        n: (r.input_hash, r.output_hash) for n, r in second.stages.items()
    }
