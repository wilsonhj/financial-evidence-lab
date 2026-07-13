"""T0104: XBRL normalization — scale/sign/unit/period/dimensions, decimal
string values, duplicate detection, and restatement linkage."""

from __future__ import annotations

import pathlib
import random
import re
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from fel_workers.ingestion.parser import (
    InlineFact,
    ParsedDocument,
    SourceSpan,
    XbrlContext,
    parse_filing,
    text_hash,
)
from fel_workers.ingestion.xbrl import (
    NormalizationError,
    PriorFact,
    decimal_str,
    fact_key,
    map_unit,
    normalize_facts,
    parse_fact_value,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


VALUE_PATTERN = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
ENTITY = "00000000-0000-0000-0000-000000000001"
VERSION = "11111111-1111-1111-1111-111111111111"


def _fact(
    raw_text: str, *, scale: int = 0, sign: str | None = None, format: str | None = None
) -> InlineFact:
    return InlineFact(
        concept="us-gaap:Revenues",
        context_ref="c1",
        unit_ref="u1",
        scale=scale,
        decimals=None,
        sign=sign,
        format=format,
        raw_text=raw_text,
        span_id="span-1",
        section_id="sec-1",
        start_char=0,
        end_char=len(raw_text),
    )


def _document(facts: list[InlineFact], contexts: dict[str, XbrlContext]) -> ParsedDocument:
    spans = tuple(
        SourceSpan(
            id=f.span_id,
            section_id=f.section_id,
            start_char=f.start_char,
            end_char=f.end_char,
            text_hash=text_hash(f.raw_text),
            text=f.raw_text,
        )
        for f in facts
    )
    return ParsedDocument(
        content_hash="0" * 64,
        parser_version="fel-parser/test",
        text=" ".join(f.raw_text for f in facts),
        sections=(),
        spans=spans,
        tables=(),
        contexts=MappingProxyType(contexts),
        units=MappingProxyType({"u1": "iso4217:USD"}),
        facts=tuple(facts),
    )


DURATION_CTX = XbrlContext(
    id="c1",
    instant=None,
    start=date(2026, 1, 1),
    end=date(2026, 3, 31),
    dimensions=MappingProxyType({}),
)


def test_scale_and_comma_stripping() -> None:
    assert parse_fact_value(_fact("1,250", scale=6)) == Decimal("1250000000")


def test_sign_attribute_negates() -> None:
    assert parse_fact_value(_fact("450", scale=3, sign="-")) == Decimal("-450000")


def test_fractional_values_survive_scaling() -> None:
    assert decimal_str(parse_fact_value(_fact("1.25", scale=2))) == "125"
    assert decimal_str(parse_fact_value(_fact("0.4525", scale=2))) == "45.25"


def test_unparseable_and_empty_values_fail_closed() -> None:
    with pytest.raises(NormalizationError) as excinfo:
        parse_fact_value(_fact("N/A"))
    assert excinfo.value.reason_code == "UNPARSEABLE_FACT_VALUE"
    with pytest.raises(NormalizationError) as excinfo:
        parse_fact_value(_fact("  "))
    assert excinfo.value.reason_code == "EMPTY_FACT_VALUE"


def test_format_num_dot_decimal_transform() -> None:
    """Finding 6: explicit ixt:num-dot-decimal — ',' thousands, '.' decimal."""
    assert parse_fact_value(_fact("1,234.56", format="ixt:num-dot-decimal")) == Decimal("1234.56")


def test_format_num_comma_decimal_transform() -> None:
    """Finding 6: ixt:num-comma-decimal — '1.234,56' is 1234.56, not 1.234."""
    assert parse_fact_value(_fact("1.234,56", format="ixt:num-comma-decimal")) == Decimal("1234.56")
    assert parse_fact_value(_fact("1.234,56", format="ixt:num-comma-decimal", scale=3)) == Decimal(
        "1234560"
    )


def test_format_fixed_zero_transform() -> None:
    """Finding 6: ixt:fixed-zero is zero regardless of the display text."""
    assert parse_fact_value(_fact("anything", format="ixt:fixed-zero")) == Decimal(0)


def test_format_fixed_empty_rejects_instead_of_zeroing() -> None:
    """Finding 6: fixed-empty declares NO numeric value; storing 0 would
    fabricate a number, so it fails closed."""
    with pytest.raises(NormalizationError) as excinfo:
        parse_fact_value(_fact("", format="ixt:fixed-empty"))
    assert excinfo.value.reason_code == "EMPTY_FACT_VALUE"


def test_parenthesized_negative_values() -> None:
    """Finding 6: '(1,234)' renders a negative value in filings."""
    assert parse_fact_value(_fact("(1,234)")) == Decimal("-1234")
    assert parse_fact_value(_fact("(1,234)", scale=3)) == Decimal("-1234000")
    assert parse_fact_value(_fact("(1.234,56)", format="ixt:num-comma-decimal")) == Decimal(
        "-1234.56"
    )


def test_dash_is_zero() -> None:
    """Finding 6: a lone dash glyph (any common variant) means zero."""
    for dash in ("-", "–", "—", "−"):
        assert parse_fact_value(_fact(dash)) == Decimal(0)


def test_unknown_format_fails_closed() -> None:
    """Finding 6: an unregistered iXBRL transform must never be guessed."""
    with pytest.raises(NormalizationError) as excinfo:
        parse_fact_value(_fact("1,250", format="ixt:num-unit-decimal"))
    assert excinfo.value.reason_code == "UNKNOWN_FORMAT"
    assert "num-unit-decimal" in excinfo.value.diagnostic


@pytest.mark.parametrize("literal", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_decimals_fail_closed(literal: str) -> None:
    """Finding 7: NaN/sNaN/Infinity/-Infinity parse as valid Decimals but can
    never be stored; they must raise NormalizationError, not corrupt data or
    crash on scaleb."""
    with pytest.raises(NormalizationError) as excinfo:
        parse_fact_value(_fact(literal, scale=3))
    assert excinfo.value.reason_code == "NONFINITE_FACT_VALUE"


def test_decimal_str_never_uses_exponent_or_float() -> None:
    """Property: for a wide range of decimal magnitudes, the rendered value
    is a plain decimal string that round-trips exactly."""
    rng = random.Random(20260713)
    for _ in range(500):
        digits = rng.randint(1, 24)
        magnitude = Decimal(rng.randint(0, 10**digits))
        shift = rng.randint(-6, 12)
        sign = rng.choice([1, -1])
        value = (magnitude * sign).scaleb(shift)
        text = decimal_str(value)
        assert VALUE_PATTERN.match(text), text
        assert Decimal(text) == value


def test_map_unit() -> None:
    assert map_unit("iso4217:USD") == "USD"
    assert map_unit("xbrli:shares") == "shares"
    assert map_unit("xbrli:pure") == "pure"
    assert map_unit("utr:sqft") == "utr:sqft"


def test_duration_and_instant_periods() -> None:
    doc = parse_filing(fixture_bytes("synthetic_10q.html"))
    facts = normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION)
    by_concept = {f.concept: f for f in facts if f.duplicate_of is None and not f.dimensions}
    revenue = by_concept["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert revenue.period_type == "duration"
    assert (revenue.period_start, revenue.period_end) == (date(2026, 1, 1), date(2026, 3, 31))
    assert revenue.value == "1250000000"
    assets = by_concept["us-gaap:Assets"]
    assert assets.period_type == "instant"
    assert assets.period_instant == date(2026, 3, 31)
    assert assets.value == "8400000000"
    charges = by_concept["us-gaap:RestructuringCharges"]
    assert charges.value == "-450000"
    shares = by_concept["us-gaap:WeightedAverageNumberOfSharesOutstandingBasic"]
    assert shares.unit == "shares"
    assert shares.value == "120000000"


def test_dimensions_separate_fact_keys() -> None:
    doc = parse_filing(fixture_bytes("synthetic_10q.html"))
    facts = normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION)
    revenue_facts = [
        f
        for f in facts
        if f.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ]
    keys = {f.fact_key for f in revenue_facts}
    assert len(keys) == 2, "segmented and consolidated revenue must not collide"
    segmented = [f for f in revenue_facts if f.dimensions]
    assert segmented[0].dimensions == {
        "us-gaap:StatementBusinessSegmentsAxis": "syn:WidgetSegmentMember"
    }
    assert segmented[0].value == "700000000"


def test_duplicate_detection_collapses_identical_values() -> None:
    doc = parse_filing(fixture_bytes("synthetic_10q.html"))
    facts = normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION)
    duplicates = [f for f in facts if f.duplicate_of is not None]
    assert len(duplicates) == 1
    canonical = {f.id: f for f in facts}[duplicates[0].duplicate_of]
    assert canonical.fact_key == duplicates[0].fact_key
    assert canonical.value == duplicates[0].value == "1250000000"


def test_conflicting_duplicate_fails_closed() -> None:
    facts = [_fact("100"), _fact("200")]
    doc = _document(facts, {"c1": DURATION_CTX})
    with pytest.raises(NormalizationError) as excinfo:
        normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION)
    assert excinfo.value.reason_code == "INCONSISTENT_DUPLICATE"
    assert "conflicting values" in excinfo.value.diagnostic


def test_restatement_linkage_records_superseded_fact() -> None:
    doc = _document([_fact("1,300", scale=6)], {"c1": DURATION_CTX})
    key = fact_key(
        "us-gaap:Revenues",
        "USD",
        period_type="duration",
        period_instant=None,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        dimensions={},
    )
    prior = {key: PriorFact(fact_id="prior-fact-id", value="1250000000")}
    facts = normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION, prior_facts=prior)
    assert facts[0].restates == "prior-fact-id"
    # Same value -> no restatement.
    unchanged = normalize_facts(
        doc,
        entity_id=ENTITY,
        document_version_id=VERSION,
        prior_facts={key: PriorFact(fact_id="prior-fact-id", value="1300000000")},
    )
    assert unchanged[0].restates is None


def test_context_without_period_fails_closed() -> None:
    broken = XbrlContext(
        id="c1", instant=None, start=date(2026, 1, 1), end=None, dimensions=MappingProxyType({})
    )
    with pytest.raises(NormalizationError) as excinfo:
        normalize_facts(
            _document([_fact("1")], {"c1": broken}),
            entity_id=ENTITY,
            document_version_id=VERSION,
        )
    assert excinfo.value.reason_code == "INVALID_PERIOD_STRUCTURE"


def test_to_contract_matches_financial_fact_v1() -> None:
    doc = parse_filing(fixture_bytes("synthetic_10q.html"))
    facts = normalize_facts(doc, entity_id=ENTITY, document_version_id=VERSION)
    for fact in facts:
        record = fact.to_contract()
        required = {
            "entity_id",
            "concept",
            "value",
            "unit",
            "scale",
            "period",
            "source_span_id",
            "reported_or_derived",
        }
        assert required <= set(record)
        assert isinstance(record["value"], str)
        assert VALUE_PATTERN.match(record["value"])
        assert record["reported_or_derived"] == "reported"
        period = record["period"]
        assert isinstance(period, dict)
        assert period["type"] in ("instant", "duration")
        if period["type"] == "duration":
            assert "start" in period and "end" in period
        else:
            assert "instant" in period
