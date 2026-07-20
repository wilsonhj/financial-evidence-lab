"""Unit tests for smoke metrics, release gate and reranker trigger (M2-024)."""

from __future__ import annotations

from decimal import Decimal

from fel_retrieval.oracle import recall_at_k as oracle_recall
from fel_retrieval_evals.metrics import (
    RERANKER_RECALL_TRIGGER,
    SMOKE_THRESHOLDS,
    QuestionOutcome,
    aggregate_metrics,
    build_gate_report,
    hnsw_recall_at_k,
    metric_supports,
    question_recall_at_k,
    rate,
    reranker_triggered,
)


def test_rate_and_empty_denominator() -> None:
    assert rate(3, 4) == Decimal("0.75")
    assert rate(0, 0) == Decimal(1)  # vacuous


def test_question_recall_at_k() -> None:
    assert question_recall_at_k(["a", "b", "c"], ["a", "b"], 10) == Decimal(1)
    assert question_recall_at_k(["a", "x"], ["a", "b"], 10) == Decimal("0.5")
    # gold outside the top-k window is missed.
    assert question_recall_at_k(["x", "y", "a"], ["a"], 2) == Decimal(0)
    # a negative case (no gold) is vacuously perfect.
    assert question_recall_at_k([], [], 10) == Decimal(1)


def test_hnsw_recall_reuses_oracle() -> None:
    assert hnsw_recall_at_k is oracle_recall
    assert hnsw_recall_at_k(["a", "b"], ["a", "b"], 2) == 1.0


def test_aggregate_metrics_all_pass() -> None:
    outcomes = [
        QuestionOutcome(
            recall_at_10=Decimal(1),
            temporal_ok=True,
            numeric_expected=True,
            numeric_correct=True,
            supporting_citations=2,
            correct_supporting_citations=2,
            rendered_claims=2,
            cited_rendered_claims=2,
        )
        for _ in range(3)
    ]
    metrics = aggregate_metrics(outcomes)
    assert metrics["recall_at_10"] == Decimal(1)
    assert metrics["temporal_validity"] == Decimal(1)
    assert metrics["numeric_accuracy"] == Decimal(1)
    report = build_gate_report(metrics, supports=metric_supports(outcomes))
    assert report.passed is True
    assert report.reranker_triggered is False


def test_gate_fails_below_threshold_and_triggers_reranker() -> None:
    metrics = {
        "temporal_validity": Decimal(1),
        "numeric_accuracy": Decimal(1),
        "entailment_precision": Decimal(1),
        "citation_completeness": Decimal(1),
        "recall_at_10": Decimal("0.80"),  # below 0.90
    }
    report = build_gate_report(metrics)
    assert report.passed is False
    assert report.reranker_triggered is True
    recall_result = next(r for r in report.results if r.name == "recall_at_10")
    assert recall_result.passed is False


def test_reranker_trigger_boundary() -> None:
    assert reranker_triggered(RERANKER_RECALL_TRIGGER) is False  # exactly 0.90 passes
    assert reranker_triggered(Decimal("0.8999")) is True
    assert reranker_triggered(Decimal("0.95")) is False


def test_thresholds_match_spec() -> None:
    assert SMOKE_THRESHOLDS["temporal_validity"] == Decimal("1.00")
    assert SMOKE_THRESHOLDS["numeric_accuracy"] == Decimal("0.99")
    assert SMOKE_THRESHOLDS["entailment_precision"] == Decimal("0.95")
    assert SMOKE_THRESHOLDS["citation_completeness"] == Decimal("0.92")
    assert SMOKE_THRESHOLDS["recall_at_10"] == Decimal("0.90")


def test_numeric_accuracy_only_over_numeric_questions() -> None:
    outcomes = [
        QuestionOutcome(recall_at_10=Decimal(1), temporal_ok=True, numeric_expected=False),
        QuestionOutcome(
            recall_at_10=Decimal(1),
            temporal_ok=True,
            numeric_expected=True,
            numeric_correct=False,
        ),
    ]
    # One numeric question, wrong -> 0/1.
    assert aggregate_metrics(outcomes)["numeric_accuracy"] == Decimal(0)


def test_empty_outcomes_fail_the_gate_when_supports_supplied() -> None:
    # Per-question rates are still vacuously 1 (a negative case has no gold)...
    metrics = aggregate_metrics([])
    assert all(v == Decimal(1) for v in metrics.values())
    supports = metric_supports([])
    assert all(s == 0 for s in supports.values())
    # ...but a *release gate* must not PASS on data that was never measured.
    report = build_gate_report(metrics, supports=supports)
    assert report.passed is False
    assert all(r.passed is False for r in report.results)
    # Legacy threshold-only grading (no supports) still reports the vacuous pass.
    assert build_gate_report(metrics).passed is True


def test_gate_fails_metric_with_zero_support() -> None:
    # All rates 1.0, but zero numeric questions were graded -> numeric fails closed.
    outcomes = [QuestionOutcome(recall_at_10=Decimal(1), temporal_ok=True, numeric_expected=False)]
    report = build_gate_report(aggregate_metrics(outcomes), supports=metric_supports(outcomes))
    numeric = next(r for r in report.results if r.name == "numeric_accuracy")
    assert numeric.passed is False
    assert report.passed is False
