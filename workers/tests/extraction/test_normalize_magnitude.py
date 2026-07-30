"""Magnitude-suffix, full-consumption, declared-scale and declared-sign guards.

PR #145 review blockers 1, 2, 3 and 6. Every case here is a wrong *number* —
the failure mode a review pipeline cannot catch, because a proposal carrying a
plausible figure at the wrong order of magnitude looks exactly like a correct
one. The contract convention under test is mantissa + exponent, which is what
`packages/contracts/fixtures/extraction-payloads.valid.json` itself stores
(`{"raw_value": "$100 million", "value": "100", "scale": 6}`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fel_workers.extraction.normalize import normalize_payload, parse_numeric
from fel_workers.extraction.types import NORMALIZER_BLOCKERS_KEY
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.range import SCALE_MAX, SCALE_MIN, range_errors

_RUN_ID = "11111111-1111-4111-8111-111111111111"


# ---------------------------------------------------------------------------
# Blocker 1 — the suffix table was incomplete and case-confused.
# ---------------------------------------------------------------------------

# (raw_value, expected mantissa, expected exponent). Every row that was WRONG at
# PR #145 head is marked; the rest are the rows that were already right and must
# stay right.
_SUFFIX_CASES: list[tuple[str, str, int]] = [
    # -- already correct, kept as regression guards --------------------------
    ("$4.2M", "4.2", 6),
    ("$4.2 million", "4.2", 6),
    ("$100 millions", "100", 6),
    ("$5m", "5", 6),
    ("3.0 billion", "3.0", 9),
    ("$2B", "2", 9),
    ("4.1 billions", "4.1", 9),
    ("1.2k", "1.2", 3),
    ("7k", "7", 3),
    ("3.5 thousand", "3.5", 3),
    ("$4,200 thousand", "4200", 3),
    # -- WRONG at head: 'bn' fell off the table, so scale collapsed to 0 -----
    ("$4.2bn", "4.2", 9),
    ("US$4.2 bn", "4.2", 9),
    ("$4.2 BN", "4.2", 9),
    # -- WRONG at head: 'MM' is millions by filing convention, not 0 --------
    ("$4.2 MM", "4.2", 6),
    ("6 mm", "6", 6),
    ("$18 mn", "18", 6),
    # -- WRONG at head: trillions had no entry at all ----------------------
    ("1.2 trillion", "1.2", 12),
    ("3 trillions", "3", 12),
    ("9 tn", "9", 12),
    # -- already correct: the \b anchor rejects unit words ------------------
    ("150 bps", "150", 0),
    ("45 basis points", "45", 0),
    ("5 basis points", "5", 0),
    ("12 months", "12", 0),
    ("18 months", "18", 0),
    # -- WRONG at head: 'm/m' is month-over-month, it must NOT scale -------
    ("100 m/m", "100", 0),
    ("100 M/M", "100", 0),
    ("2.5 y/y", "2.5", 0),
    ("1 q/q", "1", 0),
    ("4 b/b", "4", 0),
    # A genuine per-unit rate keeps its exponent: the ratio guard is keyed on
    # the same token repeating, not on the slash alone.
    ("$5bn/yr", "5", 9),
    # A bare 't' is tons/tonnes in filings, never trillions.
    ("9 t", "9", 0),
]


@pytest.mark.parametrize(("raw", "mantissa", "exponent"), _SUFFIX_CASES)
def test_magnitude_suffix_table(raw: str, mantissa: str, exponent: int) -> None:
    value, scale, _sign = parse_numeric(raw)
    assert (value, scale) == (
        Decimal(mantissa),
        exponent,
    ), f"{raw!r} -> ({value}, {scale}), expected ({mantissa}, {exponent})"


def test_every_suffix_exponent_is_a_decimal_magnitude() -> None:
    """thousand=3, million=6, billion=9, trillion=12 — no SI 'm=milli' leaks in."""
    from fel_workers.extraction.normalize.numeric import _SCALE_SUFFIX

    assert set(_SCALE_SUFFIX.values()) == {3, 6, 9, 12}
    # Case folding: uppercase filing notation resolves to the same exponent.
    for token, exponent in _SCALE_SUFFIX.items():
        assert parse_numeric(f"1 {token.upper()}")[1] == exponent


# ---------------------------------------------------------------------------
# Blocker 2 — a non-consuming match silently truncated the magnitude.
# ---------------------------------------------------------------------------

# Each of these returned a wrong magnitude at head (the value in the comment),
# because `re.search` took the first token and discarded the remainder.
_TRUNCATING_CASES = [
    ("12,34,567", "12"),
    ("4,200,00", "4200"),
    ("1,23", "1"),
    ("$ 1 234 567", "1"),
    ("1e6", "1"),
    ("1.2.3", "1.2"),
    (",234", "234"),
]


@pytest.mark.parametrize(("raw", "head_value"), _TRUNCATING_CASES)
def test_partial_numeric_match_fails_closed(raw: str, head_value: str) -> None:
    """A number we cannot read in full raises instead of guessing its magnitude."""
    with pytest.raises(ValueError) as excinfo:
        parse_numeric(raw)
    message = str(excinfo.value)
    assert "unconsumed numeric remainder" in message or "malformed grouped number" in message
    del head_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Full-consumption must not start rejecting well-formed input.
        ("4200000", Decimal("4200000")),
        ("1,234,567", Decimal("1234567")),
        ("$1,234.50", Decimal("1234.50")),
        ("12345.67", Decimal("12345.67")),
        ("-1234", Decimal("-1234")),
        ("(1,234)", Decimal("-1234")),
        ("$(2,500) thousand", Decimal("-2500")),
        (".5", Decimal("0.5")),
        ("0.5", Decimal("0.5")),
        ("999", Decimal("999")),
        ("0", Decimal("0")),
        ("-2.5%", Decimal("-2.5")),
        # Prose around a single number is fine — only leftover DIGITS are fatal.
        ("US$4.2 bn", Decimal("4.2")),
        ("approximately $120 million", Decimal("120")),
        ("$4.2 million.", Decimal("4.2")),
    ],
)
def test_full_consumption_keeps_well_formed_values(raw: str, expected: Decimal) -> None:
    value, _scale, _sign = parse_numeric(raw)
    assert value == expected


def test_preview_normalize_reports_truncation_instead_of_raising() -> None:
    """The allowlisted-tool preview must surface the refusal, not a wrong number."""
    from fel_workers.extraction.normalize.numeric import preview_normalize

    preview = preview_normalize("12,34,567")
    assert preview["ok"] is False
    assert "unconsumed numeric remainder" in preview["error"]


# ---------------------------------------------------------------------------
# Blockers 3 and 6 — declared scale / sign were never validated against the value.
# ---------------------------------------------------------------------------


def _kpi(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "1234",
        "value": "1234",
        "unit": "USD",
        "currency": "USD",
        "scale": 0,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
    }
    payload.update(overrides)
    return payload


def _summary_blockers(payload: dict[str, Any]) -> list[str]:
    result = validate_proposals(run_id=_RUN_ID, payloads=[payload])
    assert result.proposals, "payload produced no draft to inspect"
    return list(result.proposals[0].validation_summary["blockers"])


@pytest.mark.parametrize(
    ("scale", "expected_blocker"),
    [
        (99, "scale out of range: 99"),
        (SCALE_MAX + 1, f"scale out of range: {SCALE_MAX + 1}"),
        (-3, "scale out of range: -3"),
        (SCALE_MIN - 1, f"scale out of range: {SCALE_MIN - 1}"),
        ("6", "scale must be int"),
        (True, "scale must be int"),
    ],
)
def test_implausible_declared_scale_is_blocked_not_applied(
    scale: Any, expected_blocker: str
) -> None:
    """A model-declared exponent is checked BEFORE it is used, and never raises.

    At PR #145 head `payload.py` forced `scale = 0`, so a declared 99 multiplied
    the value into a 100-digit integer and a declared -3 silently divided it by
    1000 — and `range_errors`' two messages were unreachable, with zero coverage
    anywhere in the repo. The exponent is now carried, so the payload is blocked
    for review instead of being rewritten, and the value keeps its mantissa.
    """
    out = normalize_payload(_kpi(scale=scale))

    # The mantissa is untouched: no inflation, no silent division.
    assert out["value"] == "1234"
    # Reported as a blocker rather than an exception — the pipeline expects blockers.
    assert expected_blocker in out[NORMALIZER_BLOCKERS_KEY]
    # And range_errors, previously unreachable, now fires on the live path too.
    assert expected_blocker in range_errors(out)
    # It reaches the reviewer through validation_summary, exactly once.
    blockers = _summary_blockers(out)
    assert blockers.count(expected_blocker) == 1
    result = validate_proposals(run_id=_RUN_ID, payloads=[out])
    assert result.proposals[0].validation_summary["ok"] is False


@pytest.mark.parametrize("scale", [SCALE_MIN, 3, 6, 9, SCALE_MAX])
def test_valid_declared_scale_is_carried_without_a_blocker(scale: int) -> None:
    """Boundary values inside the bound are honoured silently, exponent preserved."""
    out = normalize_payload(_kpi(scale=scale))
    assert out["scale"] == scale
    assert out["value"] == "1234"
    assert NORMALIZER_BLOCKERS_KEY not in out
    assert range_errors(out) == []


def test_field_text_suffix_overrides_a_declared_scale_without_compounding() -> None:
    """A suffix in the field's own text is authoritative; the two never multiply."""
    out = normalize_payload(_kpi(raw_value="$4.2 million", value="$4.2 million", scale=3))
    assert (out["value"], out["scale"]) == ("4.2", 6)


def test_guidance_range_bounds_are_restated_onto_one_exponent() -> None:
    """One payload carries one `scale`, so mixed-magnitude bounds are reconciled."""
    out = normalize_payload(
        {
            "schema_version": "extraction-payload/v1",
            "kind": "guidance",
            "shape": "range",
            "entity_id": "11111111-1111-4111-8111-111111111111",
            "issuer_label": "Example SaaS",
            "metric_id": "revenue",
            "raw_value": "$900 million to $1.2 billion",
            "low": "900 million",
            "high": "1.2 billion",
            "unit": "USD",
            "currency": "USD",
            "period": {"type": "forecast", "end": "2027-06-30"},
            "dimensions": {},
            "qualifiers": {},
        }
    )
    # Smallest exponent wins, so every restatement is an exact left shift.
    assert (out["low"], out["high"], out["scale"]) == ("900", "1200", 6)
    # And the ordering the range validator depends on survives the restatement.
    assert Decimal(out["low"]) < Decimal(out["high"])


def test_declared_sign_that_contradicts_the_value_is_blocked() -> None:
    """Blocker 6: the loss -> profit inversion, relocated to the declared sign.

    At head `out["sign"] = out.get("sign") or sign` let a model-declared
    `positive` stand over a value normalizing to -1234.5, with zero blockers.
    """
    out = normalize_payload(_kpi(raw_value="(1,234.50)", value="-1234.50", sign="positive"))

    assert out["value"] == "-1234.5"
    # The value is the authoritative number, so the derived sign wins ...
    assert out["sign"] == "negative"
    # ... and the disagreement is reported rather than silently overwritten.
    assert out[NORMALIZER_BLOCKERS_KEY] == [
        "sign contradicts value: declared positive, value is negative"
    ]
    blockers = _summary_blockers(out)
    assert "sign contradicts value: declared positive, value is negative" in blockers


@pytest.mark.parametrize(
    ("value", "declared"),
    [("1234", "positive"), ("-1234", "negative"), ("0", "zero")],
)
def test_agreeing_declared_sign_produces_no_blocker(value: str, declared: str) -> None:
    out = normalize_payload(_kpi(value=value, raw_value=value, sign=declared))
    assert out["sign"] == declared
    assert NORMALIZER_BLOCKERS_KEY not in out


def test_unknown_declared_sign_is_blocked() -> None:
    out = normalize_payload(_kpi(sign="up"))
    assert out["sign"] == "positive"
    assert out[NORMALIZER_BLOCKERS_KEY] == ["sign must be positive/negative/zero: 'up'"]


def test_normalizer_blockers_survive_renormalization() -> None:
    """Re-normalizing (which crash-resume does) neither loses nor duplicates them."""
    once = normalize_payload(_kpi(raw_value="(1,234.50)", value="-1234.50", sign="positive"))
    twice = normalize_payload(once)
    assert twice[NORMALIZER_BLOCKERS_KEY] == once[NORMALIZER_BLOCKERS_KEY]
    assert twice["value"] == once["value"]
    assert twice["scale"] == once["scale"]


def test_normalizer_blockers_never_reach_the_persisted_payload_or_its_hash() -> None:
    """The metadata key is `_`-prefixed, so it is stripped before schema/persist."""
    out = normalize_payload(_kpi(scale=99))
    result = validate_proposals(run_id=_RUN_ID, payloads=[out])
    draft = result.proposals[0]
    assert NORMALIZER_BLOCKERS_KEY not in draft.payload
    clean = normalize_payload(_kpi(scale=99))
    clean.pop(NORMALIZER_BLOCKERS_KEY)
    # Same content-address whether or not the blocker metadata rode along.
    assert (
        draft.raw_payload_hash
        == validate_proposals(run_id=_RUN_ID, payloads=[clean]).proposals[0].raw_payload_hash
    )
