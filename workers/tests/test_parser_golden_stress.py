"""T0111 (b): parser golden-file suite over the committed SYNTHETIC stress
fixture library.

Each fixture in ``regen_parser_goldens.GOLDEN_FIXTURES`` is parsed (and,
where it carries inline XBRL, normalized) and the FULL output — canonical
text hash/length, section hierarchy, spans with offsets and text hashes,
tables, contexts, units, raw inline facts, normalized financial-fact/v1
records, and diagnostics — is compared against its committed golden file.

The regeneration workflow is documented in
``workers/tests/fixtures/regen_parser_goldens.py`` (the suite loads that
module, so generation and verification share one serializer). Beyond the
golden comparison, invariant tests re-verify every span hash against the
canonical text slice it addresses, so a golden regenerated from a broken
parser cannot silently self-certify.

Stress coverage on top of the per-feature tests on main
(test_parser_golden.py): nested tables inside a populated outer table,
parenthesized negatives, comma-decimal values with an explicit iXBRL
format attribute, dash-as-zero, fixed-zero, nil and content-empty facts,
multi-dimensional facts, sign attributes, shares/pure units,
ix:continuation-style narrative, heading-level jumps, and header-less /
body-less tables.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
from types import ModuleType

import pytest

from fel_workers.ingestion.parser import parse_filing

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_REGEN_SCRIPT = FIXTURES / "regen_parser_goldens.py"

TEXT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DECIMAL_STRING_PATTERN = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def _load_regen_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("regen_parser_goldens", _REGEN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


regen = _load_regen_module()

FIXTURE_NAMES = sorted(regen.GOLDEN_FIXTURES)


def _golden(fixture_name: str) -> dict[str, object]:
    payload = json.loads((FIXTURES / regen.GOLDEN_FIXTURES[fixture_name]).read_text())
    assert isinstance(payload, dict)
    return payload


# Compare section by section so a drift failure names the exact facet.
_GOLDEN_KEYS = (
    "parser_version",
    "normalizer_version",
    "content_hash",
    "text_length",
    "text_hash",
    "sections",
    "spans",
    "tables",
    "contexts",
    "units",
    "facts",
    "normalized_facts",
    "diagnostics",
)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
@pytest.mark.parametrize("key", _GOLDEN_KEYS)
def test_full_output_matches_golden(fixture_name: str, key: str) -> None:
    """The committed golden pins the FULL parse + normalize output."""
    golden = _golden(fixture_name)
    actual = regen.build_golden(fixture_name)
    assert key in golden, f"golden for {fixture_name} is missing {key!r}; regenerate it"
    assert actual[key] == golden[key], (
        f"parser output drifted from golden ({fixture_name} / {key}); if the "
        "change is intentional, bump the parser/normalizer version and follow "
        "the regeneration workflow in regen_parser_goldens.py"
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_golden_has_no_unpinned_keys(fixture_name: str) -> None:
    """Generation and verification agree on the exact golden shape."""
    golden = _golden(fixture_name)
    actual = regen.build_golden(fixture_name)
    assert set(actual) == set(golden)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_span_hashes_reverify_against_canonical_text(fixture_name: str) -> None:
    """Independent invariant (not golden-vs-golden): every span's text hash
    re-verifies against the canonical text slice its offsets address, and
    every raw fact's span exists."""
    parsed = parse_filing((FIXTURES / fixture_name).read_bytes())
    section_ids = {s.id for s in parsed.sections}
    span_ids = set()
    for span in parsed.spans:
        assert span.section_id in section_ids
        assert 0 <= span.start_char < span.end_char <= len(parsed.text)
        covered = parsed.text[span.start_char : span.end_char]
        assert TEXT_HASH_PATTERN.match(span.text_hash)
        assert span.text_hash == "sha256:" + hashlib.sha256(covered.encode()).hexdigest()
        assert span.text == covered
        span_ids.add(span.id)
    for fact in parsed.facts:
        assert fact.span_id in span_ids


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_parse_and_goldens_are_deterministic(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_bytes()
    assert parse_filing(raw) == parse_filing(raw)
    assert regen.build_golden(fixture_name) == regen.build_golden(fixture_name)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_normalized_values_are_contract_decimal_strings(fixture_name: str) -> None:
    """Money is decimal strings end-to-end: every normalized value matches
    the DB CHECK pattern for financial_facts.value (never float, never
    exponent notation)."""
    golden = _golden(fixture_name)
    for fact in golden["normalized_facts"]:  # type: ignore[union-attr]
        assert isinstance(fact["value"], str)
        assert DECIMAL_STRING_PATTERN.match(fact["value"]), fact


def _normalized_by_key(golden: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    out: dict[tuple[str, str], dict[str, object]] = {}
    for fact in golden["normalized_facts"]:  # type: ignore[union-attr]
        out.setdefault((fact["concept"], fact["fact_key"]), fact)
    return out


@pytest.fixture(scope="module")
def stress_golden() -> dict[str, object]:
    return _golden("synthetic_10q_stress.html")


@pytest.fixture(scope="module")
def narrative_golden() -> dict[str, object]:
    return _golden("synthetic_8k_narrative.html")


class TestStressSemantics:
    """Pin the SEMANTIC readings of the stress constructs (belt to the
    stress_golden comparison's braces): these assertions fail with meaning even
    if the stress_golden file were regenerated from a wrong parse."""

    def test_parenthesized_negative(self, stress_golden: dict[str, object]) -> None:
        facts = _normalized_by_key(stress_golden)
        charge = next(
            fact
            for (concept, _), fact in facts.items()
            if concept == "us-gaap:RestructuringCharges"
        )
        assert charge["value"] == "-2500000"  # (2,500) thousand -> -2,500,000

    def test_sign_attribute_negates(self, stress_golden: dict[str, object]) -> None:
        facts = _normalized_by_key(stress_golden)
        loss = next(
            fact for (concept, _), fact in facts.items() if concept == "us-gaap:OperatingIncomeLoss"
        )
        assert loss["value"] == "-300000000"

    def test_comma_decimal_format(self, stress_golden: dict[str, object]) -> None:
        eur = next(
            fact
            for fact in stress_golden["normalized_facts"]  # type: ignore[union-attr]
            if fact["unit"] == "EUR"
        )
        # '987.654,32' thousand EUR -> 987,654,320 (no locale guessing).
        assert eur["value"] == "987654320"
        assert eur["dimensions"] == {"srt:StatementGeographicalAxis": "syn:EuropeMember"}

    def test_dash_and_fixed_zero_are_zero(self, stress_golden: dict[str, object]) -> None:
        values = {
            fact["concept"]: fact["value"]
            for fact in stress_golden["normalized_facts"]  # type: ignore[union-attr]
        }
        assert values["us-gaap:ImpairmentOfIntangibleAssetsExcludingGoodwill"] == "0"
        assert values["us-gaap:LossContingencyAccrualAtCarryingValue"] == "0"

    def test_nil_and_empty_facts_skipped_with_diagnostics(
        self, stress_golden: dict[str, object]
    ) -> None:
        concepts = {fact["concept"] for fact in stress_golden["normalized_facts"]}  # type: ignore[union-attr]
        assert "us-gaap:GoodwillImpairmentLoss" not in concepts
        assert "us-gaap:DeferredCostsCurrent" not in concepts
        diagnostics = stress_golden["diagnostics"]
        assert any("nil" in d and "us-gaap:GoodwillImpairmentLoss" in d for d in diagnostics)  # type: ignore[union-attr]
        assert any("empty" in d and "us-gaap:DeferredCostsCurrent" in d for d in diagnostics)  # type: ignore[union-attr]

    def test_two_dimensional_fact(self, stress_golden: dict[str, object]) -> None:
        cloud = next(
            fact
            for fact in stress_golden["normalized_facts"]  # type: ignore[union-attr]
            if len(fact["dimensions"]) == 2
        )
        assert cloud["dimensions"] == {
            "srt:StatementGeographicalAxis": "syn:EuropeMember",
            "srt:ProductOrServiceAxis": "syn:CloudSubscriptionMember",
        }
        assert cloud["value"] == "45600000"

    def test_duplicate_presentation_collapses(self, stress_golden: dict[str, object]) -> None:
        revenue = [
            fact
            for fact in stress_golden["normalized_facts"]  # type: ignore[union-attr]
            if fact["concept"].endswith("ExcludingAssessedTax") and fact["dimensions"] == {}
        ]
        assert len(revenue) == 2
        canonical, duplicate = revenue
        assert canonical["duplicate_of"] is None
        assert duplicate["duplicate_of"] == canonical["id"]
        assert canonical["value"] == duplicate["value"] == "1234500000"

    def test_nested_table_preserves_outer_rows(self, stress_golden: dict[str, object]) -> None:
        outer, inner = stress_golden["tables"]  # type: ignore[misc]
        assert outer["caption"] == "Condensed consolidated results (synthetic)"
        assert [row[0] for row in outer["rows"]] == [
            "Revenue ($M)",
            "Detail",
            "Operating income ($M)",
        ]
        assert inner["caption"] == "Inner detail (synthetic)"
        assert inner["rows"] == [
            ["Europe (€K)", "987.654,32"],
            ["Rest of world ($K)", "52,900"],
        ]

    def test_continuation_content_flows_into_canonical_text(
        self, stress_golden: dict[str, object]
    ) -> None:
        parsed = parse_filing((FIXTURES / "synthetic_10q_stress.html").read_bytes())
        assert "continues into the notes" in parsed.text
        # The continuation text is addressable evidence: some span covers it.
        assert any(
            "continues into the notes" in parsed.text[span.start_char : span.end_char]
            for span in parsed.spans
        )


class TestNarrativeSemantics:

    def test_heading_level_jump_keeps_hierarchy(self, narrative_golden: dict[str, object]) -> None:
        by_heading = {section["heading"]: section for section in narrative_golden["sections"]}  # type: ignore[union-attr]
        preliminary = by_heading["Preliminary, unaudited highlights"]
        assert preliminary["heading_path"][-2] == "Item 2.02. Results of Operations"
        # The later h2 pops back to the document level, not under the h4.
        exhibits = by_heading["Item 9.01. Exhibits"]
        assert "Preliminary, unaudited highlights" not in exhibits["heading_path"]

    def test_headerless_and_bodyless_tables(self, narrative_golden: dict[str, object]) -> None:
        headerless, headers_only = narrative_golden["tables"]  # type: ignore[misc]
        assert headerless["headers"] == []
        assert len(headerless["rows"]) == 2
        assert headers_only["headers"] == ["Exhibit", "Description"]
        assert headers_only["rows"] == []

    def test_no_facts_no_diagnostics(self, narrative_golden: dict[str, object]) -> None:
        assert narrative_golden["facts"] == []
        assert narrative_golden["normalized_facts"] == []
        assert narrative_golden["diagnostics"] == []
