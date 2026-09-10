"""The explicit vocabulary folds ASCII aliases only."""

import pytest

from fel_ontology.units import canonical_unit, is_monetary_unit


@pytest.mark.parametrize(
    "source,expected",
    [
        (" USD ", "USD"),
        ("usd", "USD"),
        ("Usd/mo", "USD/mo"),
        ("usd/Mo", "USD/Mo"),
        ("Percent", "percent"),
        ("PERCENT", "percent"),
        ("%", "percent"),
        ("pct", "percent"),
        ("Percentage", "percent"),
        ("PP", "percentage_points"),
        ("Count", "count"),
        ("Pure", "pure"),
        ("Ratio", "ratio"),
        ("Shares", "shares"),
        ("Customers", "customers"),
        ("cpu", "cpu"),
        ("CPU", "CPU"),
        ("ß", "ß"),
        ("K", "K"),
        ("ı", "ı"),
        ("İ", "İ"),
        ("uſd", "uſd"),
        ("US D", "US D"),
        (None, None),
        (42, 42),
        ([], []),
    ],
)
def test_explicit_aliases(source, expected):
    assert canonical_unit(source) == expected


@pytest.mark.parametrize("unit", ["CHF", "sek", "INR", "usd/yr", "Currency/mo"])
def test_money(unit):
    assert is_monetary_unit(unit)


@pytest.mark.parametrize("unit", ["CPU", "cpu", "uſd", "count/mo", None, []])
def test_nonmoney(unit):
    assert not is_monetary_unit(unit)
