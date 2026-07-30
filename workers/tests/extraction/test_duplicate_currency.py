"""``duplicate_groups`` must not collapse equal numbers in different currencies."""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.validate.duplicates import comparability_key_for, duplicate_groups

_PERIOD = {"type": "instant", "instant": "2026-06-30"}


def _arr(currency: str, value: str = "100") -> dict[str, Any]:
    return {
        "kind": "kpi",
        "metric_id": "arr",
        "period": dict(_PERIOD),
        "value": value,
        "unit": currency,
        "currency": currency,
        "qualifiers": {"currency": currency, "construction": "reported_arr", "scope": "all"},
    }


def test_same_number_in_different_currencies_is_not_a_duplicate() -> None:
    assert duplicate_groups([_arr("USD"), _arr("JPY")]) == []


def test_same_number_in_the_same_currency_is_still_a_duplicate() -> None:
    assert duplicate_groups([_arr("USD"), _arr("USD")]) == [[0, 1]]


def test_duplicate_grouping_agrees_with_comparability_key_on_currency() -> None:
    """The two fingerprints in this module must not disagree about currency."""
    usd, jpy = _arr("USD"), _arr("JPY")
    assert comparability_key_for(usd)["currency"] != comparability_key_for(jpy)["currency"]
    assert duplicate_groups([usd, jpy]) == []
