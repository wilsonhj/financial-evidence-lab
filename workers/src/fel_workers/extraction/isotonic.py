"""Deterministic weighted pool-adjacent-violators isotonic-v1 (#337)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
)
from fractions import Fraction
from typing import Literal, NoReturn, assert_never, cast

_MAX_SAMPLES = 100000
_MAX_DEPTH = 16
_MIN_N = 100
_MIN_CLASS = 20
_QUANT = Decimal("0.000000000001")
_SCHEMA = "isotonic-v1"
_EVAL_SCHEMA = "isotonic-evaluation/v1"
_SCORE = re.compile(r"(?:0|1|0\.[0-9]{0,11}[1-9])")
_ARTIFACT_KEYS = frozenset({"schema_version", "status", "n", "positive", "negative", "blocks"})
_BLOCK_KEYS = frozenset({"lower_score", "upper_score", "count", "positive"})
_FIT_STATUSES = frozenset({"fitted", "insufficient_data"})
_CODES = frozenset({"invalid_sample", "limit_exceeded", "invalid_artifact"})
_MESSAGES = {
    "invalid_sample": "Calibration sample input is invalid",
    "limit_exceeded": "Calibration resource bound is exceeded",
    "invalid_artifact": "Calibration artifact is invalid",
}
_SIGNALS = (
    Clamped,
    InvalidOperation,
    DivisionByZero,
    Inexact,
    Rounded,
    Subnormal,
    Overflow,
    Underflow,
    FloatOperation,
)
_SEQUENCE_TYPES = (list, tuple)

FitStatus = Literal["fitted", "insufficient_data"]
EvalStatus = Literal["evaluated", "insufficient_calibration", "insufficient_evaluation"]


class CalibrationError(Exception):
    """Safe calibration failure; ``code`` is a frozen diagnostic token."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str) -> NoReturn:
    if code not in _CODES:
        raise RuntimeError("unknown calibration error")
    error = CalibrationError(_MESSAGES[code], code=code)
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    raise error


def _isolated() -> Context:
    ctx = Context(prec=50, rounding=ROUND_HALF_EVEN)
    for signal in _SIGNALS:
        ctx.traps[signal] = False
    return ctx


def _ratio12(numerator: int, denominator: int) -> Decimal:
    ctx = _isolated()
    value = ctx.divide(Decimal(numerator), Decimal(denominator))
    return ctx.quantize(value, _QUANT)


def _fraction12(value: Fraction) -> Decimal:
    return _ratio12(value.numerator, value.denominator)


def _emit12(value: Decimal) -> str:
    return format(value, "f")


def _check_depth(value: object, depth: int) -> None:
    if depth > _MAX_DEPTH:
        _fail("limit_exceeded")
    kind = type(value)
    if kind is dict:
        for inner in cast(dict[str, object], value).values():
            _check_depth(inner, depth + 1)
    elif kind is list:
        for inner in cast(list[object], value):
            _check_depth(inner, depth + 1)


def _canonical_score(value: object, *, code: str) -> str:
    if type(value) is not str or _SCORE.fullmatch(value) is None:
        _fail(code)
    return value


def _actual_int(value: object, *, code: str) -> int:
    if type(value) is not int:
        _fail(code)
    return value


def _bounded_count(value: object, *, code: str) -> int:
    number = _actual_int(value, code=code)
    if number < 0 or number > _MAX_SAMPLES:
        _fail(code)
    return number


def _parse_samples(samples: object) -> list[tuple[str, int]]:
    if type(samples) not in _SEQUENCE_TYPES:
        _fail("invalid_sample")
    sequence = cast(Sequence[object], samples)
    if len(sequence) > _MAX_SAMPLES:
        _fail("limit_exceeded")
    parsed: list[tuple[str, int]] = []
    for row in sequence:
        if type(row) not in _SEQUENCE_TYPES:
            _fail("invalid_sample")
        pair = cast(Sequence[object], row)
        if len(pair) != 2:
            _fail("invalid_sample")
        score = _canonical_score(pair[0], code="invalid_sample")
        outcome = _actual_int(pair[1], code="invalid_sample")
        if outcome not in (0, 1):
            _fail("invalid_sample")
        parsed.append((score, outcome))
    return parsed


def _support(n: int, positive: int, negative: int) -> bool:
    return n >= _MIN_N and positive >= _MIN_CLASS and negative >= _MIN_CLASS


def _should_merge(left: tuple[str, str, int, int], right: tuple[str, str, int, int]) -> bool:
    left_positive, left_count = left[3], left[2]
    right_positive, right_count = right[3], right[2]
    return left_positive * right_count >= right_positive * left_count


def _pool(groups: list[tuple[str, str, int, int]]) -> list[tuple[str, str, int, int]]:
    stack: list[tuple[str, str, int, int]] = []
    for group in groups:
        stack.append(group)
        while len(stack) >= 2 and _should_merge(stack[-2], stack[-1]):
            right = stack.pop()
            left = stack.pop()
            stack.append((left[0], right[1], left[2] + right[2], left[3] + right[3]))
    return stack


def _aggregate(samples: list[tuple[str, int]]) -> list[tuple[str, str, int, int]]:
    counts: dict[str, int] = {}
    positives: dict[str, int] = {}
    for score, outcome in samples:
        counts[score] = counts.get(score, 0) + 1
        positives[score] = positives.get(score, 0) + outcome
    ordered = sorted(counts, key=lambda score: Decimal(score))
    return [(score, score, counts[score], positives[score]) for score in ordered]


def _public_blocks(blocks: list[tuple[str, str, int, int]]) -> list[dict[str, object]]:
    return [
        {
            "lower_score": lower,
            "upper_score": upper,
            "count": count,
            "positive": positive,
        }
        for lower, upper, count, positive in blocks
    ]


def _block_tuple(value: object) -> tuple[str, str, int, int]:
    block = value
    if type(block) is not dict or set(block) != _BLOCK_KEYS:
        _fail("invalid_artifact")
    typed = cast(dict[str, object], block)
    lower = _canonical_score(typed["lower_score"], code="invalid_artifact")
    upper = _canonical_score(typed["upper_score"], code="invalid_artifact")
    if Decimal(lower) > Decimal(upper):
        _fail("invalid_artifact")
    count = _bounded_count(typed["count"], code="invalid_artifact")
    positive = _bounded_count(typed["positive"], code="invalid_artifact")
    if count < 1 or positive > count:
        _fail("invalid_artifact")
    return (lower, upper, count, positive)


def _validate_artifact(artifact: object) -> dict[str, object]:
    depth_failed = False
    try:
        _check_depth(artifact, 1)
    except RecursionError:
        depth_failed = True
    if depth_failed:
        _fail("limit_exceeded")
    if type(artifact) is not dict or set(artifact) != _ARTIFACT_KEYS:
        _fail("invalid_artifact")
    typed = cast(dict[str, object], artifact)
    if typed["schema_version"] != _SCHEMA:
        _fail("invalid_artifact")
    status_value = typed["status"]
    if status_value not in _FIT_STATUSES:
        _fail("invalid_artifact")
    status = cast(FitStatus, status_value)
    n = _bounded_count(typed["n"], code="invalid_artifact")
    positive = _bounded_count(typed["positive"], code="invalid_artifact")
    negative = _bounded_count(typed["negative"], code="invalid_artifact")
    if positive + negative != n:
        _fail("invalid_artifact")
    if type(typed["blocks"]) is not list:
        _fail("invalid_artifact")
    raw_blocks = cast(list[object], typed["blocks"])
    blocks = [_block_tuple(block) for block in raw_blocks]
    total_count = sum(block[2] for block in blocks)
    total_positive = sum(block[3] for block in blocks)
    enough = _support(n, positive, negative)
    if status == "insufficient_data":
        if blocks or enough:
            _fail("invalid_artifact")
    elif status == "fitted":
        if not blocks or not enough or total_count != n or total_positive != positive:
            _fail("invalid_artifact")
        previous: tuple[str, str, int, int] | None = None
        for block in blocks:
            if previous is not None:
                if Decimal(previous[1]) >= Decimal(block[0]):
                    _fail("invalid_artifact")
                left_pos, left_count = previous[3], previous[2]
                right_pos, right_count = block[3], block[2]
                if left_pos * right_count >= right_pos * left_count:
                    _fail("invalid_artifact")
            previous = block
    else:
        assert_never(status)
    return {
        "schema_version": _SCHEMA,
        "status": status,
        "n": n,
        "positive": positive,
        "negative": negative,
        "blocks": _public_blocks(blocks),
        "_raw_blocks": blocks,
    }


def _mean(block: tuple[str, str, int, int]) -> Decimal:
    return _ratio12(block[3], block[2])


def _left_step(blocks: list[tuple[str, str, int, int]], score: str) -> Decimal:
    query = Decimal(score)
    first = blocks[0]
    last = blocks[-1]
    if query < Decimal(first[0]):
        return _mean(first)
    if query > Decimal(last[1]):
        return _mean(last)
    chosen = first
    for block in blocks:
        lower = Decimal(block[0])
        upper = Decimal(block[1])
        if lower <= query <= upper:
            return _mean(block)
        if lower <= query:
            chosen = block
        elif Decimal(chosen[1]) < query < lower:
            return _mean(chosen)
    return _mean(chosen)


def fit(samples: Sequence[tuple[str, int]]) -> dict[str, object]:
    """Fit a weighted PAV artifact for one stratum of score/outcome tuples."""
    parsed = _parse_samples(samples)
    n = len(parsed)
    positive = sum(outcome for _score, outcome in parsed)
    negative = n - positive
    enough = _support(n, positive, negative)
    blocks = _pool(_aggregate(parsed)) if enough else []
    status: FitStatus = "fitted" if enough else "insufficient_data"
    return {
        "schema_version": _SCHEMA,
        "status": status,
        "n": n,
        "positive": positive,
        "negative": negative,
        "blocks": _public_blocks(blocks),
    }


def predict(artifact: dict[str, object], score: str) -> Decimal:
    """Return a 12-place probability, or zero for an insufficient artifact."""
    validated = _validate_artifact(artifact)
    canonical = _canonical_score(score, code="invalid_sample")
    status = cast(FitStatus, validated["status"])
    if status == "insufficient_data":
        return Decimal("0")
    if status == "fitted":
        blocks = cast(list[tuple[str, str, int, int]], validated["_raw_blocks"])
        return _left_step(blocks, canonical)
    assert_never(status)


def _bin_index(probability: Decimal) -> int:
    scaled = Fraction(probability) * 10
    return min(9, scaled.numerator // scaled.denominator)


def _evaluation(artifact: dict[str, object], samples: list[tuple[str, int]]) -> dict[str, object]:
    n = len(samples)
    positive = sum(outcome for _score, outcome in samples)
    negative = n - positive
    status_value = artifact["status"]
    status = cast(FitStatus, status_value)
    eval_status: EvalStatus
    if status == "insufficient_data":
        eval_status = "insufficient_calibration"
    elif status == "fitted":
        eval_status = "evaluated" if _support(n, positive, negative) else "insufficient_evaluation"
    else:
        assert_never(status)
    if eval_status != "evaluated":
        return {
            "schema_version": _EVAL_SCHEMA,
            "status": eval_status,
            "n": n,
            "positive": positive,
            "negative": negative,
            "sufficient": False,
            "brier": None,
            "ece": None,
            "bins": [],
        }
    blocks = cast(list[tuple[str, str, int, int]], artifact["_raw_blocks"])
    predictions = [_left_step(blocks, score) for score, _outcome in samples]
    brier_sum = Fraction(0)
    bin_counts = [0] * 10
    bin_prob = [Fraction(0)] * 10
    bin_pos = [0] * 10
    for probability, (_score, outcome) in zip(predictions, samples, strict=True):
        prob = Fraction(probability)
        brier_sum += (prob - outcome) ** 2
        index = _bin_index(probability)
        bin_counts[index] += 1
        bin_prob[index] += prob
        bin_pos[index] += outcome
    bins: list[dict[str, object]] = []
    ece_sum = Fraction(0)
    for index in range(10):
        count = bin_counts[index]
        if count == 0:
            bins.append(
                {
                    "index": index,
                    "count": 0,
                    "mean_probability": None,
                    "positive_rate": None,
                }
            )
            continue
        mean_probability = bin_prob[index] / count
        positive_rate = Fraction(bin_pos[index], count)
        ece_sum += count * abs(mean_probability - positive_rate)
        bins.append(
            {
                "index": index,
                "count": count,
                "mean_probability": _emit12(_fraction12(mean_probability)),
                "positive_rate": _emit12(_fraction12(positive_rate)),
            }
        )
    return {
        "schema_version": _EVAL_SCHEMA,
        "status": "evaluated",
        "n": n,
        "positive": positive,
        "negative": negative,
        "sufficient": True,
        "brier": _emit12(_fraction12(brier_sum / n)),
        "ece": _emit12(_fraction12(ece_sum / n)),
        "bins": bins,
    }


def evaluate(artifact: dict[str, object], samples: Sequence[tuple[str, int]]) -> dict[str, object]:
    """Evaluate a frozen artifact on held-out tuples without refitting."""
    validated = _validate_artifact(artifact)
    parsed = _parse_samples(samples)
    return _evaluation(validated, parsed)


__all__ = ["CalibrationError", "evaluate", "fit", "predict"]
