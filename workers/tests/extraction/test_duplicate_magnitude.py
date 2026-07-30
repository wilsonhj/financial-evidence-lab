"""Magnitude must participate in duplicate / conflict identity (P1-6).

`normalize` keeps a mantissa in `value` and the filing's declared exponent in
`scale`, so `$100 thousand` and `$100 million` are byte-identical in every field
the old fingerprints read. A reviewer was shown two figures 1000x apart as a
`duplicate_candidate` and nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.duplicates import duplicate_groups, value_fingerprint

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)

_QUALIFIERS = {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"}


def _arr(*, value: str = "100", scale: int = 6, unit: str = "USD") -> dict[str, Any]:
    kpi = dict(json.loads(FIXTURES.read_text())["kpi"])
    kpi.update(value=value, scale=scale, unit=unit, qualifiers=dict(_QUALIFIERS))
    return kpi


def _reason_codes(payloads: list[dict[str, Any]]) -> set[str]:
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000a1",
        payloads=payloads,
    )
    return {code for conflict in result.conflicts for code in conflict.reason_codes}


def test_same_mantissa_different_scale_is_not_a_duplicate() -> None:
    """$100 thousand and $100 million are two figures, not one restated twice."""
    assert duplicate_groups([_arr(scale=3), _arr(scale=6)]) == []


def test_same_mantissa_different_scale_disagrees_on_value() -> None:
    """The 1000x gap must reach the reviewer as a value_disagreement."""
    assert value_fingerprint(_arr(scale=3)) != value_fingerprint(_arr(scale=6))


def test_scale_gap_surfaces_as_value_disagreement_conflict() -> None:
    codes = _reason_codes([_arr(scale=3), _arr(scale=6)])
    assert "value_disagreement" in codes
    assert "duplicate_candidate" not in codes


def test_same_magnitude_written_differently_is_still_a_duplicate() -> None:
    """100e6 and 100000000e0 are the same number, so they are duplicates."""
    assert duplicate_groups([_arr(value="100", scale=6), _arr(value="100000000", scale=0)]) == [
        [0, 1]
    ]


def test_same_magnitude_written_differently_does_not_disagree() -> None:
    assert value_fingerprint(_arr(value="100", scale=6)) == value_fingerprint(
        _arr(value="100000000", scale=0)
    )


def test_same_number_in_different_units_is_not_a_duplicate() -> None:
    """USD/yr and USD are not the same unit of account for one mantissa."""
    assert duplicate_groups([_arr(unit="USD"), _arr(unit="USD/yr")]) == []


def test_identical_figures_are_still_duplicates() -> None:
    assert duplicate_groups([_arr(), _arr()]) == [[0, 1]]
