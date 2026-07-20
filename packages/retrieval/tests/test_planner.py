from __future__ import annotations

import json
from pathlib import Path

import pytest

from fel_retrieval import (
    PlannerValidationError,
    QueryRequest,
    classify_intent,
    derive_budgets,
    expand_variants,
    plan_query,
)

INDEX = "c3d4e5f6-a7b8-9012-cdef-123456789012"
CORPUS = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
ENTITY = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
AS_OF = "2024-12-31T23:59:59Z"

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "schemas"
    / "query-plan.schema.json"
)


def _plan(request: QueryRequest, **overrides: object):
    kwargs: dict[str, object] = dict(
        index_version_id=INDEX,
        corpus_version_id=CORPUS,
        entity_ids=(ENTITY,),
        effective_as_of=AS_OF,
    )
    kwargs.update(overrides)
    return plan_query(request, **kwargs)  # type: ignore[arg-type]


# --- Structural conformance against the frozen JSON Schema ------------------
def _assert_conforms(plan: dict[str, object]) -> None:
    """Minimal, dependency-free structural check against query-plan/v1."""
    schema = json.loads(_SCHEMA_PATH.read_text())
    props = schema["properties"]

    for key in schema["required"]:
        assert key in plan, f"missing required key {key}"

    assert plan["schema_version"] == props["schema_version"]["const"]
    assert plan["intent"] in set(props["intent"]["enum"])

    entity_ids = plan["entity_ids"]
    assert isinstance(entity_ids, list) and len(entity_ids) >= 1

    lanes = plan["lanes"]
    assert isinstance(lanes, list)
    lane_enum = set(props["lanes"]["items"]["enum"])
    assert all(lane in lane_enum for lane in lanes)
    assert len(lanes) == len(set(lanes))  # uniqueItems

    variants = plan["variants"]
    assert isinstance(variants, list)
    assert props["variants"]["minItems"] <= len(variants) <= props["variants"]["maxItems"]
    assert all(isinstance(v, str) for v in variants)

    assert set(plan["filters"]).issubset({"forms", "periods"})  # additionalProperties false

    budgets = plan["budgets"]
    assert isinstance(budgets, dict)
    budget_props = props["budgets"]["properties"]
    for key in props["budgets"]["required"]:
        assert key in budgets
        value = budgets[key]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert budget_props[key]["minimum"] <= value <= budget_props[key]["maximum"]


def test_plan_conforms_to_schema() -> None:
    plan = _plan(
        QueryRequest(question="What was quarterly revenue?", forms=("10-K",), periods=("2024",))
    )
    _assert_conforms(plan.to_dict())


# --- Determinism ------------------------------------------------------------
def test_determinism_byte_identical() -> None:
    request = QueryRequest(
        question="Compare net income year over year", forms=("10-K",), periods=("2024",)
    )
    a = _plan(request)
    b = _plan(request)
    assert a.to_canonical_json() == b.to_canonical_json()


def test_different_question_changes_serialization() -> None:
    a = _plan(QueryRequest(question="What was revenue?"))
    b = _plan(QueryRequest(question="What was net income?"))
    assert a.to_canonical_json() != b.to_canonical_json()


# --- Intent classification --------------------------------------------------
@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Is there a contradiction between the filings?", "contradiction"),
        ("Why did revenue increase?", "driver_analysis"),
        ("Compare revenue year over year", "comparison"),
        ("What is the guidance for next year?", "guidance"),
        ("Show the breakdown of operating expenses in a table", "table_reasoning"),
        ("Summarize the risk factors section", "section_lookup"),
        ("What was net income in 2024?", "fact_lookup"),
        ("Tell me about the company", "general"),
    ],
)
def test_intent_classification(question: str, intent: str) -> None:
    assert classify_intent(question) == intent


def test_intent_partial_word_does_not_misfire() -> None:
    # "comparable" must not be classified as comparison via "compare".
    assert classify_intent("Describe the comparable store metrics") != "comparison"


# --- Synonym expansion / variants ------------------------------------------
def test_synonym_expansion_includes_original_and_rewrites() -> None:
    variants = expand_variants("quarterly revenue outlook")
    assert variants[0] == "quarterly revenue outlook"
    assert "quarterly net sales outlook" in variants


def test_variants_capped_at_four_and_deduped() -> None:
    variants = expand_variants("revenue net income guidance eps")
    assert 1 <= len(variants) <= 4
    assert len(variants) == len(set(variants))


def test_no_synonym_returns_only_original() -> None:
    assert expand_variants("describe the business overview") == ("describe the business overview",)


# --- Budgets ----------------------------------------------------------------
def test_budgets_default_top_k() -> None:
    b = derive_budgets(100)
    assert (b.lane_top_k, b.fused_top_k, b.context_items, b.timeout_ms) == (100, 100, 16, 15000)


def test_budgets_scale_down() -> None:
    b = derive_budgets(5)
    assert (b.lane_top_k, b.fused_top_k, b.context_items) == (5, 5, 5)


def test_budgets_context_capped() -> None:
    assert derive_budgets(50).context_items == 16


def test_budgets_minimum_one() -> None:
    b = derive_budgets(1)
    assert b.context_items == 1 and b.lane_top_k == 1


def test_top_k_omitted_defaults_to_100() -> None:
    plan = _plan(QueryRequest(question="What was revenue?"))
    assert plan.budgets.fused_top_k == 100


def test_lanes_default_to_all_four() -> None:
    plan = _plan(QueryRequest(question="What was revenue?"))
    assert plan.lanes == ("dense", "lexical", "facts", "tables")


# --- Fail-closed validation (each must actually raise) ----------------------
def _code(exc: pytest.ExceptionInfo[PlannerValidationError]) -> str:
    return exc.value.code


def test_reject_empty_question() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question=""))
    assert _code(exc) == "EMPTY_QUESTION"


def test_reject_whitespace_question() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="   "))
    assert _code(exc) == "EMPTY_QUESTION"


def test_reject_question_too_long() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="a" * 4001))
    assert _code(exc) == "QUESTION_TOO_LONG"


@pytest.mark.parametrize("top_k", [0, 101, -1])
def test_reject_top_k_out_of_range(top_k: int) -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", top_k=top_k))
    assert _code(exc) == "TOP_K_OUT_OF_RANGE"


def test_reject_top_k_bool() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", top_k=True))  # bool is not a valid integer top_k
    assert _code(exc) == "TOP_K_NOT_INTEGER"


def test_reject_unknown_lane() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", lanes=("dense", "semantic")))
    assert _code(exc) == "UNKNOWN_LANE"


def test_reject_duplicate_lane() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", lanes=("dense", "dense")))
    assert _code(exc) == "DUPLICATE_LANE"


def test_reject_too_many_lanes() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", lanes=("dense", "lexical", "facts", "tables", "dense")))
    assert _code(exc) == "TOO_MANY_LANES"


def test_reject_empty_lanes() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", lanes=()))
    assert _code(exc) == "EMPTY_LANES"


@pytest.mark.parametrize("period", ["Q5-2024", "202X", "2024-13", "2024-Q0", "twenty-twenty-four"])
def test_reject_invalid_period(period: str) -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", periods=(period,)))
    assert _code(exc) == "INVALID_PERIOD"


@pytest.mark.parametrize("period", ["2024", "2024-Q4", "2024-H1", "2024-03", "2024-12"])
def test_accept_valid_period(period: str) -> None:
    plan = _plan(QueryRequest(question="q", periods=(period,)))
    assert plan.filters.periods == (period,)


def test_reject_too_many_periods() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", periods=tuple(str(2000 + i) for i in range(21))))
    assert _code(exc) == "TOO_MANY_PERIODS"


def test_reject_empty_form() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", forms=("10-K", "  ")))
    assert _code(exc) == "EMPTY_FORM"


def test_reject_too_many_forms() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q", forms=tuple(f"F{i}" for i in range(21))))
    assert _code(exc) == "TOO_MANY_FORMS"


def test_reject_no_entity_ids() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q"), entity_ids=())
    assert _code(exc) == "NO_ENTITY_IDS"


def test_reject_bad_entity_uuid() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q"), entity_ids=("not-a-uuid",))
    assert _code(exc) == "INVALID_UUID"


def test_reject_bad_index_uuid() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q"), index_version_id="nope")
    assert _code(exc) == "INVALID_UUID"


def test_reject_bad_corpus_uuid() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q"), corpus_version_id="nope")
    assert _code(exc) == "INVALID_UUID"


def test_reject_unparsable_as_of() -> None:
    with pytest.raises(PlannerValidationError) as exc:
        _plan(QueryRequest(question="q"), effective_as_of="not-a-date")
    assert _code(exc) == "INVALID_AS_OF"
