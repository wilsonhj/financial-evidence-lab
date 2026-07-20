"""Smoke-benchmark metrics, release gate and reranker trigger (M2-024 / T0215).

The evaluator turns per-question outcomes into the five exit-gate metrics (spec
§ exit gates) and grades them against the frozen smoke thresholds:

    temporal validity  = 100%
    numeric accuracy    >= 99%
    entailment precision>= 95%
    citation completeness>= 92%
    Recall@10           >= 90%

Every rate is exact ``Decimal`` (no float drift can nudge a value across a
threshold). ``recall_at_k`` for *exact-vs-HNSW* index quality is reused directly
from ``fel_retrieval.oracle`` — the same oracle the index-build suite grades HNSW
against — so there is one definition of recall in the codebase.

The release gate is *report-only* for the reranker decision (ADR-0002 / M2-FR-008):
if the baseline Recall@10 is below 90% the report flags that a cross-encoder over
the fused top-100 must be enabled; at or above 90% the reranker stays disabled.
The gate never mutates retrieval — it only reports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fel_retrieval.oracle import recall_at_k as hnsw_recall_at_k

__all__ = [
    "RERANKER_RECALL_TRIGGER",
    "SMOKE_THRESHOLDS",
    "GateReport",
    "GateResult",
    "QuestionOutcome",
    "aggregate_metrics",
    "build_gate_report",
    "hnsw_recall_at_k",
    "metric_supports",
    "question_recall_at_k",
    "rate",
    "reranker_triggered",
]

# Frozen smoke thresholds (spec exit gates / issue #58 acceptance). Recall@10 is
# also the ADR-0002 reranker trigger point.
SMOKE_THRESHOLDS: dict[str, Decimal] = {
    "temporal_validity": Decimal("1.00"),
    "numeric_accuracy": Decimal("0.99"),
    "entailment_precision": Decimal("0.95"),
    "citation_completeness": Decimal("0.92"),
    "recall_at_10": Decimal("0.90"),
}
RERANKER_RECALL_TRIGGER = Decimal("0.90")


def rate(numerator: int, denominator: int) -> Decimal:
    """Exact ``numerator/denominator`` rate; an empty denominator is vacuously 1."""
    if denominator == 0:
        return Decimal(1)
    return Decimal(numerator) / Decimal(denominator)


def question_recall_at_k(retrieved_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> Decimal:
    """Fraction of a question's gold evidence present in the retrieved top-k.

    A question with no gold evidence (a negative case) is vacuously perfect.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    gold = set(gold_ids)
    if not gold:
        return Decimal(1)
    found = gold.intersection(set(retrieved_ids[:k]))
    return Decimal(len(found)) / Decimal(len(gold))


@dataclass(frozen=True)
class QuestionOutcome:
    """One question's graded outcome, over which the aggregate metrics fold."""

    recall_at_10: Decimal
    temporal_ok: bool
    # Numeric accuracy is scored only for numeric-answer questions.
    numeric_expected: bool = False
    numeric_correct: bool = False
    # Entailment precision: of the supporting edges the run asserted, how many
    # are true supporting edges (against gold).
    supporting_citations: int = 0
    correct_supporting_citations: int = 0
    # Citation completeness: of the rendered (supported/derived) claims, how many
    # carry at least one citation.
    rendered_claims: int = 0
    cited_rendered_claims: int = 0


def aggregate_metrics(outcomes: Sequence[QuestionOutcome]) -> dict[str, Decimal]:
    """Fold per-question outcomes into the five gate metrics."""
    n = len(outcomes)
    recall = sum((o.recall_at_10 for o in outcomes), Decimal(0)) / Decimal(n) if n else Decimal(1)
    temporal = rate(sum(1 for o in outcomes if o.temporal_ok), n)
    numeric = rate(
        sum(1 for o in outcomes if o.numeric_expected and o.numeric_correct),
        sum(1 for o in outcomes if o.numeric_expected),
    )
    entailment = rate(
        sum(o.correct_supporting_citations for o in outcomes),
        sum(o.supporting_citations for o in outcomes),
    )
    completeness = rate(
        sum(o.cited_rendered_claims for o in outcomes),
        sum(o.rendered_claims for o in outcomes),
    )
    return {
        "temporal_validity": temporal,
        "numeric_accuracy": numeric,
        "entailment_precision": entailment,
        "citation_completeness": completeness,
        "recall_at_10": recall,
    }


def metric_supports(outcomes: Sequence[QuestionOutcome]) -> dict[str, int]:
    """Denominator (populated sample size) behind each aggregate metric.

    A release gate must not PASS on absent data: a metric whose denominator is
    zero was never measured. ``rate`` returns a vacuous 1 for an empty
    denominator (correct per-question — a negative case has no gold), but the
    *gate* uses these supports to fail closed when nothing was actually graded.
    """
    n = len(outcomes)
    return {
        "temporal_validity": n,
        "recall_at_10": n,
        "numeric_accuracy": sum(1 for o in outcomes if o.numeric_expected),
        "entailment_precision": sum(o.supporting_citations for o in outcomes),
        "citation_completeness": sum(o.rendered_claims for o in outcomes),
    }


@dataclass(frozen=True)
class GateResult:
    """One metric graded against its threshold."""

    name: str
    value: Decimal
    threshold: Decimal
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": f"{self.value:.4f}",
            "threshold": f"{self.threshold:.4f}",
            "passed": self.passed,
        }


@dataclass(frozen=True)
class GateReport:
    """The release-gate verdict plus the report-only reranker decision."""

    results: tuple[GateResult, ...]
    reranker_triggered: bool

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
            "reranker": {
                "triggered": self.reranker_triggered,
                "trigger_threshold": f"{RERANKER_RECALL_TRIGGER:.4f}",
                "note": (
                    "baseline Recall@10 below 90%: enable cross-encoder over fused top-100 "
                    "(ADR-0002)"
                    if self.reranker_triggered
                    else "baseline Recall@10 at or above 90%: reranker stays disabled (ADR-0002)"
                ),
            },
        }


def reranker_triggered(recall_at_10: Decimal) -> bool:
    """ADR-0002: trigger the cross-encoder only when baseline Recall@10 < 90%."""
    return recall_at_10 < RERANKER_RECALL_TRIGGER


def build_gate_report(
    metrics: dict[str, Decimal],
    *,
    supports: dict[str, int] | None = None,
    thresholds: dict[str, Decimal] | None = None,
) -> GateReport:
    """Grade every metric against its threshold and decide the reranker trigger.

    Pass ``supports`` (from :func:`metric_supports`) to make the gate fail closed:
    a metric whose denominator is zero was never measured and cannot PASS,
    regardless of the vacuous ``1.0`` its rate reports. Omitting ``supports``
    preserves the legacy threshold-only grading.
    """
    active = thresholds if thresholds is not None else SMOKE_THRESHOLDS
    results = tuple(
        GateResult(
            name=name,
            value=metrics[name],
            threshold=active[name],
            passed=(
                metrics[name] >= active[name] and (supports is None or supports.get(name, 0) > 0)
            ),
        )
        for name in sorted(active)
    )
    return GateReport(
        results=results,
        reranker_triggered=reranker_triggered(metrics["recall_at_10"]),
    )
