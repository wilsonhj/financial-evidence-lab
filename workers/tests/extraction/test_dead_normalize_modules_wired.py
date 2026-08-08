"""Normalizers that exist must actually run on the live path (issue #155).

`normalize/dimensions.py` and `normalize/currency.py` had no importers, so the
two blockers they implement — `dimensions_non_string` and
`currency_missing_for_monetary` — could never fire, while `payload.py` carried
private near-duplicates that behaved differently: a non-string dimension value
was `str()`-coerced into a schema-clean string rather than reported.

Each test below states the behaviour at the seam the modules are wired into, so
a future consolidation cannot quietly drop a rule again.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.normalize.payload import normalize_payload
from fel_workers.extraction.normalize.pipeline import normalize_payload as normalize_or_reject
from fel_workers.extraction.types import NORMALIZER_BLOCKERS_KEY
from fel_workers.extraction.validate import validate_proposals

SPAN = "22222222-2222-4222-8222-222222222222"
DOC = "33333333-3333-4333-8333-333333333333"
TEXT = "ARR was $100 million as of June 30, 2026."


def _kpi(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"},
        "reported_or_derived": "reported",
        "evidence": [
            {
                "source_span_id": SPAN,
                "document_version_id": DOC,
                "role": "supports",
                "text_hash": sha256_hex(TEXT),
            }
        ],
    }
    payload.update(overrides)
    return payload


def _guidance(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "extraction-payload/v1",
        "kind": "guidance",
        "shape": "point",
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "issuer_label": "Example SaaS",
        "metric_id": "revenue",
        "raw_value": "approximately $120 million",
        "value": "120",
        "unit": "USD",
        "currency": "USD",
        "scale": 6,
        "sign": "positive",
        "period": {"type": "forecast", "end": "2026-09-30"},
        "dimensions": {},
        "qualifiers": {},
    }
    payload.update(overrides)
    return payload


def _carried(payload: dict[str, Any]) -> list[str]:
    """Blockers the normalizer attached without aborting."""
    return [str(b) for b in payload.get(NORMALIZER_BLOCKERS_KEY, [])]


def _review_blockers(raw: dict[str, Any]) -> list[str]:
    """Blockers a reviewer actually sees, normalize → validate end to end."""
    payload, rejection = normalize_or_reject(raw)
    if rejection:
        payload = {**payload, NORMALIZER_BLOCKERS_KEY: rejection}
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000d5",
        payloads=[payload],
        evidence_by_span={
            SPAN: {"text": TEXT, "text_hash": sha256_hex(TEXT), "document_version_id": DOC}
        },
    )
    assert len(result.proposals) == 1
    summary = result.proposals[0].validation_summary
    blockers = [str(b) for b in summary["blockers"]]
    assert summary["ok"] is (not blockers)
    return blockers


# --- control: nothing below is blocked merely by the wiring ------------------


def test_a_clean_kpi_stays_clean() -> None:
    out = normalize_payload(_kpi())
    assert _carried(out) == []
    assert _review_blockers(_kpi()) == []


# --- dimensions: non-string entries were coerced, never reported -------------


def test_non_string_dimension_value_is_reported_not_coerced() -> None:
    """`{"segment": 42}` used to normalize to `{"segment": "42"}`, clean."""
    out = normalize_payload(_kpi(dimensions={"segment": 42}))
    assert "dimensions_non_string" in _carried(out)
    assert out["dimensions"] == {}


def test_non_string_dimension_key_is_reported() -> None:
    out = normalize_payload(_kpi(dimensions={7: "total"}))
    assert "dimensions_non_string" in _carried(out)
    assert out["dimensions"] == {}


def test_a_structured_dimension_value_never_becomes_its_repr() -> None:
    """The coercing version persisted `"{'eu': 1}"` as though the issuer wrote it."""
    out = normalize_payload(_kpi(dimensions={"region": {"eu": 1}}))
    assert "dimensions_non_string" in _carried(out)
    assert "region" not in out["dimensions"]


def test_the_good_dimensions_of_a_mixed_map_survive() -> None:
    out = normalize_payload(_kpi(dimensions={"segment": "total", "quarter": 3}))
    assert out["dimensions"] == {"segment": "total"}
    assert _carried(out).count("dimensions_non_string") == 1


def test_string_dimensions_are_ordered_and_untouched() -> None:
    out = normalize_payload(_kpi(dimensions={"segment": "emea", "basis": "reported"}))
    assert out["dimensions"] == {"basis": "reported", "segment": "emea"}
    assert list(out["dimensions"]) == ["basis", "segment"]
    assert _carried(out) == []


def test_dimensions_that_are_not_a_map_still_raise() -> None:
    """Preserved from the private implementation, so `blocked_count` still counts it."""
    with pytest.raises(ValueError, match="dimensions must be an object"):
        normalize_payload(_kpi(dimensions=["emea"]))


def test_a_rejected_dimensions_payload_is_carried_not_dropped() -> None:
    payload, rejection = normalize_or_reject(_kpi(dimensions=["emea"]))
    assert rejection == ["dimensions must be an object"]
    assert payload["raw_value"] == "$100 million"


def test_the_dimension_blocker_reaches_the_review_queue() -> None:
    assert "dimensions_non_string" in _review_blockers(_kpi(dimensions={"segment": 42}))


def test_dimensions_are_graded_on_a_payload_with_no_numeric_fields() -> None:
    """Qualitative guidance never enters `_normalize_numeric_fields`."""
    out = normalize_payload(
        _guidance(
            shape="qualitative",
            text="Momentum improved",
            dimensions={"segment": 42},
            value=None,
            unit=None,
            currency=None,
            scale=None,
            sign=None,
        )
    )
    assert "dimensions_non_string" in _carried(out)


# --- currency: a monetary figure with no currency was never reported ---------


def test_a_monetary_kpi_without_a_currency_is_reported() -> None:
    out = normalize_payload(_kpi(currency=None))
    assert "currency_missing_for_monetary" in _carried(out)


def test_a_monetary_guidance_point_without_a_currency_is_reported() -> None:
    """The real gap: `revenue` is free-text, so the ontology check never graded it."""
    assert "currency_missing_for_monetary" in _review_blockers(_guidance(currency=None))


def test_an_absent_currency_key_is_reported_too() -> None:
    raw = _kpi()
    del raw["currency"]
    out = normalize_payload(raw)
    assert "currency_missing_for_monetary" in _carried(out)
    assert "currency" not in out


def test_a_currency_is_never_inferred_from_the_unit() -> None:
    """Filling in `USD` from `unit: "USD"` would repair a reported figure silently."""
    out = normalize_payload(_kpi(currency=None))
    assert out["currency"] is None


def test_any_iso_shaped_unit_is_monetary_not_just_the_major_six() -> None:
    """The deleted `is_monetary_unit` allowed six codes; CHF was not one of them."""
    out = normalize_payload(_kpi(unit="CHF", currency=None))
    assert "currency_missing_for_monetary" in _carried(out)


def test_the_generic_currency_unit_is_monetary() -> None:
    out = normalize_payload(_kpi(unit="currency", currency=None))
    assert "currency_missing_for_monetary" in _carried(out)


def test_a_non_monetary_unit_needs_no_currency() -> None:
    out = normalize_payload(
        _kpi(metric_id="sub_gm", unit="percent", currency=None, value="78", scale=0)
    )
    assert _carried(out) == []


def test_a_malformed_currency_still_raises_rather_than_being_nulled() -> None:
    """The orphan dropped the issuer's value and continued; the live path does not."""
    with pytest.raises(ValueError, match="ISO-4217"):
        normalize_payload(_kpi(currency="usd"))
    with pytest.raises(ValueError, match="ISO-4217"):
        normalize_payload(_kpi(currency="DOLLARS"))


def test_a_missing_currency_does_not_disturb_the_declared_scale() -> None:
    """The currency blocker is kept out of the list that gates `scale`."""
    out = normalize_payload(_kpi(currency=None))
    assert out["scale"] == 6
    assert out["value"] == "100"


def test_normalizing_twice_does_not_duplicate_the_new_blockers() -> None:
    once = normalize_payload(_kpi(currency=None, dimensions={"segment": 42}))
    twice = normalize_payload(once)
    assert _carried(twice) == _carried(once)
    assert sorted(_carried(twice)) == ["currency_missing_for_monetary", "dimensions_non_string"]


# --- the defect class itself -------------------------------------------------

_SRC = Path(__file__).resolve().parents[2] / "src" / "fel_workers"
_NORMALIZE = _SRC / "extraction" / "normalize"


def _referenced_names() -> dict[str, set[str]]:
    """Every identifier each source module mentions, `__init__.py` excluded.

    A re-export in `__init__.py` is not a call site — it is exactly what made
    the orphans look wired — so those files do not count as importers here.
    """
    refs: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.name.rsplit(".", 1)[-1])
        refs[str(path)] = names
    return refs


def test_every_public_normalizer_has_a_call_site_outside_its_own_module() -> None:
    """`identify_currency`, `is_monetary_unit` and `normalize_dimensions` had none.

    A public normalizer nothing calls is not merely unused: it is a rule that
    looks implemented, so the next person extending this area edits it and sees
    no behavioural change (issue #155, first raised in PR #145's review).
    """
    refs = _referenced_names()
    orphans: list[str] = []
    for module in sorted(_NORMALIZE.glob("*.py")):
        if module.name == "__init__.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            elsewhere = any(
                node.name in names for path, names in refs.items() if path != str(module)
            )
            if not elsewhere:
                orphans.append(f"{module.name}::{node.name}")
    assert orphans == [], f"public normalizers with no importer: {orphans}"
