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


def _fact(raw_text: str, *, scale: int = 0, sign: str | None = None) -> InlineFact:
    return InlineFact(
        concept="us-gaap:Revenues",
        context_ref="c1",
        unit_ref="u1",
        scale=scale,
        decimals=None,
        sign=sign,
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
    assert excinfo.value.reason_code == "INVALID_PERIOD"


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
