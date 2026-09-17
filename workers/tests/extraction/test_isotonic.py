"""Failing-first regressions for deterministic weighted PAV isotonic-v1 (#337)."""

from __future__ import annotations

import ast
from copy import deepcopy
from decimal import (
    ROUND_FLOOR,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from fractions import Fraction
from pathlib import Path
from random import Random

import pytest

from fel_workers.extraction.isotonic import CalibrationError, evaluate, fit, predict

MODULE = Path(__file__).resolve().parents[2] / "src" / "fel_workers" / "extraction" / "isotonic.py"


def _rows(score: str, n_positive: int, n_negative: int) -> list[tuple[str, int]]:
    return [(score, 1)] * n_positive + [(score, 0)] * n_negative


def _fitted_constant(
    probability: str, *, n: int = 200, n_positive: int | None = None
) -> dict[str, object]:
    if n_positive is None:
        n_positive = n // 2
    return fit(_rows(probability, n_positive, n - n_positive))


def _code_fit(samples: object, code: str) -> None:
    with pytest.raises(CalibrationError) as caught:
        fit(samples)  # type: ignore[arg-type]
    assert caught.value.code == code
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "traceback" not in str(caught.value).lower()


def test_module_does_not_import_dataset_or_runtime() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    joined = " ".join(names)
    assert "calibration_dataset" not in joined
    assert "fel_workers.extraction.handler" not in joined
    assert "sklearn" not in joined


def test_empty_input_is_insufficient_not_invalid() -> None:
    artifact = fit([])
    assert artifact["status"] == "insufficient_data"
    assert artifact["n"] == 0
    assert artifact["blocks"] == []
    assert predict(artifact, "0.5") == Decimal("0")
    result = evaluate(artifact, _rows("0.5", 50, 50))
    assert result["status"] == "insufficient_calibration"
    assert result["brier"] is None
    assert result["bins"] == []
    assert result["n"] == 100


def test_decreasing_outcomes_force_pooling() -> None:
    samples = _rows("0.1", 50, 0) + _rows("0.9", 0, 50)
    artifact = fit(samples)
    assert artifact["status"] == "fitted"
    assert artifact["blocks"] == [
        {"lower_score": "0.1", "upper_score": "0.9", "count": 100, "positive": 50}
    ]
    assert predict(artifact, "0.1") == Decimal("0.500000000000")
    assert predict(artifact, "0.5") == Decimal("0.500000000000")
    assert predict(artifact, "0.9") == Decimal("0.500000000000")


def test_tied_scores_are_grouped_before_pav() -> None:
    samples = _rows("0.2", 30, 20) + _rows("0.8", 0, 50)
    artifact = fit(samples)
    assert artifact["blocks"] == [
        {"lower_score": "0.2", "upper_score": "0.8", "count": 100, "positive": 30}
    ]
    assert predict(artifact, "0.2") == Decimal("0.300000000000")


def test_constant_score_with_both_classes() -> None:
    artifact = fit(_rows("0.5", 50, 50))
    assert artifact["blocks"] == [
        {"lower_score": "0.5", "upper_score": "0.5", "count": 100, "positive": 50}
    ]


def test_weighted_pooling_uses_counts_not_unweighted_means() -> None:
    samples = _rows("0.1", 40, 0) + _rows("0.2", 40, 40)
    artifact = fit(samples)
    assert artifact["blocks"] == [
        {"lower_score": "0.1", "upper_score": "0.2", "count": 120, "positive": 80}
    ]
    assert predict(artifact, "0.1") == Decimal("0.666666666667")


def test_two_monotone_blocks_keep_gap_and_endpoints() -> None:
    samples = _rows("0.2", 20, 60) + _rows("0.8", 60, 20)
    artifact = fit(samples)
    assert artifact["blocks"] == [
        {"lower_score": "0.2", "upper_score": "0.2", "count": 80, "positive": 20},
        {"lower_score": "0.8", "upper_score": "0.8", "count": 80, "positive": 60},
    ]
    assert predict(artifact, "0") == Decimal("0.250000000000")
    assert predict(artifact, "0.2") == Decimal("0.250000000000")
    assert predict(artifact, "0.5") == Decimal("0.250000000000")
    assert predict(artifact, "0.8") == Decimal("0.750000000000")
    assert predict(artifact, "1") == Decimal("0.750000000000")


def test_permutation_stability_and_monotonic_predictions() -> None:
    samples = _rows("0.2", 20, 60) + _rows("0.8", 60, 20)
    shuffled = list(samples)
    Random(0).shuffle(shuffled)
    left = fit(samples)
    right = fit(tuple(shuffled))
    assert left == right
    scores = ["0", "0.2", "0.5", "0.8", "1"]
    preds = [predict(left, score) for score in scores]
    assert preds == sorted(preds)


def test_support_boundaries() -> None:
    low_n = fit(_rows("0.5", 20, 79))
    low_pos = fit(_rows("0.5", 19, 81))
    low_neg = fit(_rows("0.5", 81, 19))
    ok = fit(_rows("0.5", 20, 80))
    assert low_n["status"] == low_pos["status"] == low_neg["status"] == "insufficient_data"
    assert ok["status"] == "fitted"
    assert predict(low_n, "0.5") == Decimal("0")
    assert evaluate(ok, _rows("0.5", 20, 79))["status"] == "insufficient_evaluation"
    assert evaluate(ok, _rows("0.5", 19, 81))["status"] == "insufficient_evaluation"


def test_insufficient_calibration_precedes_insufficient_evaluation() -> None:
    result = evaluate(fit(_rows("0.5", 10, 10)), _rows("0.5", 10, 10))
    assert result["status"] == "insufficient_calibration"
    assert result["sufficient"] is False
    assert result["brier"] is None
    assert result["ece"] is None


def test_exact_brier_ece_oracles_and_empty_bins() -> None:
    artifact = _fitted_constant("0.5")
    result = evaluate(artifact, _rows("0.5", 50, 50))
    assert result["status"] == "evaluated"
    assert result["sufficient"] is True
    assert result["brier"] == "0.250000000000"
    assert result["ece"] == "0.000000000000"
    bins = result["bins"]
    assert isinstance(bins, list) and len(bins) == 10
    assert [bin["index"] for bin in bins] == list(range(10))
    occupied = bins[5]
    assert occupied["count"] == 100
    assert occupied["mean_probability"] == "0.500000000000"
    assert occupied["positive_rate"] == "0.500000000000"
    for index, bin_row in enumerate(bins):
        if index == 5:
            continue
        assert bin_row["count"] == 0
        assert bin_row["mean_probability"] is None
        assert bin_row["positive_rate"] is None


def test_probability_zero_one_and_tenth_bin_edges() -> None:
    zero_one = fit(_rows("0", 0, 80) + _rows("1", 20, 0))
    at_zero = evaluate(zero_one, _rows("0", 50, 50))
    assert predict(zero_one, "0") == Decimal("0.000000000000")
    assert at_zero["brier"] == "0.500000000000"
    assert at_zero["ece"] == "0.500000000000"
    assert at_zero["bins"][0]["count"] == 100
    at_one = evaluate(zero_one, _rows("1", 50, 50))
    assert predict(zero_one, "1") == Decimal("1.000000000000")
    assert at_one["bins"][9]["count"] == 100
    tenth = _fitted_constant("0.1", n=200, n_positive=20)
    assert predict(tenth, "0.1") == Decimal("0.100000000000")
    edge = evaluate(tenth, _rows("0.1", 20, 80))
    assert edge["bins"][1]["count"] == 100
    assert edge["bins"][0]["count"] == 0
    expected_brier = (20 * Fraction(9, 10) ** 2 + 80 * Fraction(1, 10) ** 2) / 100
    assert expected_brier == Fraction(17, 100)
    assert edge["brier"] == "0.170000000000"
    assert edge["ece"] == "0.100000000000"


def test_evaluation_never_refits() -> None:
    artifact = fit(_rows("0.2", 20, 80) + _rows("0.8", 80, 20))
    held_out = _rows("0.8", 20, 80)
    result = evaluate(artifact, held_out)
    refit = fit(held_out)
    assert refit["blocks"] != artifact["blocks"]
    assert result["status"] == "evaluated"
    assert predict(artifact, "0.8") == Decimal("0.800000000000")


def test_ambient_decimal_context_does_not_affect_outputs() -> None:
    samples = _rows("0.1", 40, 0) + _rows("0.2", 40, 40)
    baseline = fit(samples)
    base_predict = predict(baseline, "0.15")
    base_eval = evaluate(baseline, _rows("0.1", 50, 50))
    with localcontext() as ctx:
        ctx.prec = 1
        ctx.rounding = ROUND_FLOOR
        ctx.traps[Overflow] = True
        ctx.traps[DivisionByZero] = True
        ctx.traps[InvalidOperation] = True
        poisoned = fit(samples)
        assert poisoned == baseline
        assert predict(poisoned, "0.15") == base_predict
        assert evaluate(poisoned, _rows("0.1", 50, 50)) == base_eval


def test_inputs_are_not_mutated() -> None:
    samples = [["0.2", 1] for _ in range(50)] + [["0.8", 0] for _ in range(50)]
    snapshot = deepcopy(samples)
    artifact = fit(samples)
    artifact_snapshot = deepcopy(artifact)
    predict(artifact, "0.2")
    evaluate(artifact, samples)
    assert samples == snapshot
    assert artifact == artifact_snapshot


@pytest.mark.parametrize(
    "samples",
    [
        "ab",
        b"xx",
        {"x": 1},
        [("0.5", 1, 0)],
        [("0.5", True)],
        [(0.5, 1)],
        [("0.10", 1)],
        [("0.5", 2)],
        [iter(("0.5", 1))],
    ],
)
def test_malformed_samples_are_rejected(samples: object) -> None:
    _code_fit(samples, "invalid_sample")


def test_generator_and_limit_are_rejected() -> None:
    _code_fit((row for row in _rows("0.5", 1, 1)), "invalid_sample")
    _code_fit(_rows("0.5", 1, 0) * 100001, "limit_exceeded")


def test_hostile_artifacts_are_rejected() -> None:
    good = fit(_rows("0.2", 20, 60) + _rows("0.8", 60, 20))
    overlapping = deepcopy(good)
    overlapping["blocks"][1]["lower_score"] = "0.1"
    with pytest.raises(CalibrationError) as caught:
        predict(overlapping, "0.5")
    assert caught.value.code == "invalid_artifact"
    nonmonotone = deepcopy(good)
    nonmonotone["blocks"][0]["positive"] = 70
    nonmonotone["positive"] = 130
    nonmonotone["negative"] = 30
    with pytest.raises(CalibrationError):
        evaluate(nonmonotone, _rows("0.5", 50, 50))
    wrong_total = deepcopy(good)
    wrong_total["n"] = 161
    wrong_total["negative"] = 81
    with pytest.raises(CalibrationError) as caught:
        predict(wrong_total, "0.5")
    assert caught.value.code == "invalid_artifact"
    equal_means = deepcopy(good)
    equal_means["blocks"][1]["positive"] = 20
    equal_means["positive"] = 40
    equal_means["negative"] = 120
    with pytest.raises(CalibrationError):
        predict(equal_means, "0.5")
    bool_count = deepcopy(good)
    bool_count["n"] = True
    with pytest.raises(CalibrationError) as caught:
        predict(bool_count, "0.5")
    assert caught.value.code == "invalid_artifact"
    extra = dict(good)
    extra["family"] = "kpi"
    with pytest.raises(CalibrationError):
        predict(extra, "0.5")
    fitted_empty = {
        "schema_version": "isotonic-v1",
        "status": "fitted",
        "n": 100,
        "positive": 50,
        "negative": 50,
        "blocks": [],
    }
    with pytest.raises(CalibrationError):
        predict(fitted_empty, "0.5")
    insufficient_blocks = {
        "schema_version": "isotonic-v1",
        "status": "insufficient_data",
        "n": 10,
        "positive": 5,
        "negative": 5,
        "blocks": list(good["blocks"]),
    }
    with pytest.raises(CalibrationError):
        predict(insufficient_blocks, "0.5")


def test_invalid_prediction_score_is_invalid_sample() -> None:
    artifact = fit(_rows("0.5", 50, 50))
    with pytest.raises(CalibrationError) as caught:
        predict(artifact, "0.10")
    assert caught.value.code == "invalid_sample"
    with pytest.raises(CalibrationError) as caught:
        predict(None, "0.5")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_artifact"


def test_nesting_limit_on_artifacts() -> None:
    nested: object = None
    for _ in range(17):
        nested = [nested]
    with pytest.raises(CalibrationError) as caught:
        predict(nested, "0.5")  # type: ignore[arg-type]
    assert caught.value.code == "limit_exceeded"
