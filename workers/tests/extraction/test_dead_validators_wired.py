"""Validators that exist must actually run on the live path (P1-5).

`check_accounting` and `check_definitions` each had exactly two references
repo-wide - their `def` and their `__all__` entry - so a derived `billings` with
no lineage, an `arr` denominated in percent, and a proposal citing nothing at
all all reached the review queue as `ok: true, blockers: []`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.validate import validate_proposals

FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "fixtures"
    / "extraction-payloads.valid.json"
)

SPAN = "22222222-2222-4222-8222-222222222222"
DOC = "33333333-3333-4333-8333-333333333333"
TEXT = "ARR was $100 million as of June 30, 2026."

_ARR_QUALIFIERS = {"currency": "USD", "construction": "reported_arr", "scope": "consolidated"}


def _pinned() -> dict[str, dict[str, Any]]:
    return {SPAN: {"text": TEXT, "text_hash": sha256_hex(TEXT), "document_version_id": DOC}}


def _cited(*, text_hash: str | None = sha256_hex(TEXT)) -> list[dict[str, Any]]:
    row: dict[str, Any] = {"source_span_id": SPAN, "document_version_id": DOC, "role": "supports"}
    if text_hash is not None:
        row["text_hash"] = text_hash
    return [row]


def _kpi(**overrides: Any) -> dict[str, Any]:
    payload = dict(json.loads(FIXTURES.read_text())["kpi"])
    payload["qualifiers"] = dict(_ARR_QUALIFIERS)
    payload["evidence"] = _cited()
    payload.update(overrides)
    return payload


def _blockers(payload: dict[str, Any]) -> list[str]:
    result = validate_proposals(
        run_id="00000000-0000-4000-8000-0000000000c1",
        payloads=[payload],
        evidence_by_span=_pinned(),
    )
    assert len(result.proposals) == 1
    summary = result.proposals[0].validation_summary
    blockers = [str(b) for b in summary["blockers"]]
    assert summary["ok"] is (not blockers)
    return blockers


# --- metric-identity blockers that never ran (were in the dead check_accounting,
# --- now folded into accounting_errors itself) -------------------------------


def test_a_fully_cited_arr_is_clean() -> None:
    """Control: nothing below is blocked merely by being wired in."""
    assert _blockers(_kpi()) == []


def test_derived_billings_without_lineage_is_blocked() -> None:
    payload = _kpi(
        metric_id="billings",
        reported_or_derived="derived",
        definition=None,
        qualifiers={"currency": "USD", "formula": "revenue + delta deferred"},
    )
    assert "billings_derivation_inputs_missing" in _blockers(payload)


def test_derived_billings_with_lineage_is_not_blocked_for_lineage() -> None:
    payload = _kpi(
        metric_id="billings",
        reported_or_derived="derived",
        definition=None,
        qualifiers={
            "currency": "USD",
            "formula": "revenue + delta deferred",
            "derivation_inputs": ["revenue", "deferred_rev"],
        },
    )
    assert "billings_derivation_inputs_missing" not in _blockers(payload)


def test_crpo_without_a_verified_horizon_is_blocked() -> None:
    payload = _kpi(
        metric_id="crpo",
        definition=None,
        qualifiers={"currency": "USD", "horizon_months": "12"},
    )
    assert "crpo_timing_unverified" in _blockers(payload)


def test_svc_gm_on_a_blended_basis_is_blocked() -> None:
    payload = _kpi(
        metric_id="svc_gm",
        unit="percent",
        currency=None,
        value="35",
        scale=0,
        definition=None,
        qualifiers={"margin_scope": "services", "basis": "blended"},
    )
    assert "svc_gm_blended_forbidden" in _blockers(payload)


# --- check_definitions: ontology cross-checks that never ran ----------------


def test_currency_metric_declared_in_percent_is_blocked() -> None:
    """`arr` is a currency metric; `unit: percent` cannot describe it."""
    blockers = _blockers(_kpi(unit="percent", currency=None))
    assert any("percent" in b and "arr" in b for b in blockers), blockers


def test_currency_metric_without_a_currency_is_blocked() -> None:
    blockers = _blockers(_kpi(currency=None))
    assert any("currency" in b for b in blockers), blockers


def test_ratio_metric_carrying_a_currency_is_blocked() -> None:
    payload = _kpi(
        metric_id="sub_gm",
        unit="percent",
        currency="USD",
        value="78",
        scale=0,
        definition=None,
        qualifiers={"margin_scope": "subscription"},
    )
    blockers = _blockers(payload)
    assert any("currency" in b and "sub_gm" in b for b in blockers), blockers


def test_kpi_period_type_must_match_ontology_period_semantics() -> None:
    """`arr` is an instant snapshot; a duration payload is the wrong quantity."""
    payload = _kpi(period={"type": "duration", "start": "2026-04-01", "end": "2026-06-30"})
    blockers = _blockers(payload)
    assert any("instant" in b and "duration" in b for b in blockers), blockers


def test_unknown_metric_id_is_not_blocked_for_guidance() -> None:
    """Guidance carries free-text metric labels by design (accounting.py:33)."""
    guidance = dict(json.loads(FIXTURES.read_text())["guidance_point"])
    guidance["evidence"] = _cited()
    assert "metric_unknown_to_ontology" not in _blockers(guidance)


# --- citations: a proposal supported by nothing is not clean ----------------


def test_a_proposal_citing_nothing_is_blocked() -> None:
    payload = _kpi()
    payload.pop("evidence")
    assert _blockers(payload) != []


def test_a_membership_only_citation_is_not_verification() -> None:
    """A pinned span with no asserted text_hash grades `partial`, never clean."""
    assert _blockers(_kpi(evidence=_cited(text_hash=None))) != []


def test_a_verified_citation_clears_the_citation_blocker() -> None:
    assert _blockers(_kpi(evidence=_cited())) == []
