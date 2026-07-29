"""PR #145 review blocker 5: the citation hash check never ran.

`validate/pipeline.py` called `citation_errors` with no `expected_hashes`, so its
hash-comparison branch was dead code, and `verify_citations` — which read as a
fail-closed integrity guarantee — had zero callers anywhere in the repo.
"""

from __future__ import annotations

from typing import Any

from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.citations import citation_errors

from .conftest import FIXTURE_DOC, FIXTURE_SPAN

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_PINNED_TEXT = "ARR was $100 million as of June 30, 2026."


def _pinned() -> dict[str, dict[str, Any]]:
    return {
        FIXTURE_SPAN: {
            "source_span_id": FIXTURE_SPAN,
            "document_version_id": FIXTURE_DOC,
            "text": _PINNED_TEXT,
            "text_hash": sha256_hex(_PINNED_TEXT),
        }
    }


def _kpi_with_evidence(evidence: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
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
        "evidence": evidence,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Blocker 5 — the citation hash comparison is now actually wired in.
# ---------------------------------------------------------------------------


def test_citation_asserting_a_wrong_span_hash_is_blocked() -> None:
    """A proposal that cites a span while asserting a different digest is blocked.

    At PR #145 head `validate/pipeline.py` called `citation_errors` with no
    `expected_hashes`, so the hash branch was dead code and this payload produced
    no citation blocker at all.
    """
    lying = _kpi_with_evidence(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "role": "supports",
                "citation_status": "partial",
                # The model asserts a digest that does not describe the pinned span.
                "text_hash": sha256_hex("ARR was $900 million as of June 30, 2026."),
            }
        ]
    )
    result = validate_proposals(run_id=_RUN_ID, payloads=[lying], evidence_by_span=_pinned())

    blockers = result.proposals[0].validation_summary["blockers"]
    assert f"span hash mismatch: {FIXTURE_SPAN}" in blockers
    assert result.proposals[0].validation_summary["ok"] is False


def test_citation_asserting_the_correct_span_hash_is_clean() -> None:
    honest = _kpi_with_evidence(
        [
            {
                "source_span_id": FIXTURE_SPAN,
                "document_version_id": FIXTURE_DOC,
                "role": "supports",
                "citation_status": "partial",
                "text_hash": sha256_hex(_PINNED_TEXT),
            }
        ]
    )
    result = validate_proposals(run_id=_RUN_ID, payloads=[honest], evidence_by_span=_pinned())
    blockers = result.proposals[0].validation_summary["blockers"]
    assert not [b for b in blockers if "hash mismatch" in b]


def test_citation_without_an_asserted_hash_is_not_penalised() -> None:
    """Most models omit the digest; absence is not a mismatch."""
    silent = _kpi_with_evidence(
        [{"source_span_id": FIXTURE_SPAN, "document_version_id": FIXTURE_DOC}]
    )
    result = validate_proposals(run_id=_RUN_ID, payloads=[silent], evidence_by_span=_pinned())
    blockers = result.proposals[0].validation_summary["blockers"]
    assert not [b for b in blockers if "hash mismatch" in b]


def test_citation_errors_hash_branch_is_exercised_directly() -> None:
    """The two previously unreachable lines of citations.py, called head on."""
    payload = _kpi_with_evidence([{"source_span_id": FIXTURE_SPAN}])
    assert citation_errors(
        payload,
        evidence_by_span=_pinned(),
        expected_hashes={FIXTURE_SPAN: sha256_hex("something else")},
    ) == [f"span hash mismatch: {FIXTURE_SPAN}"]
    assert (
        citation_errors(
            payload,
            evidence_by_span=_pinned(),
            expected_hashes={FIXTURE_SPAN: sha256_hex(_PINNED_TEXT)},
        )
        == []
    )


def test_the_dead_verify_citations_validator_is_gone() -> None:
    """It had zero callers, so none of its fail-closed-looking checks ever ran."""
    import fel_workers.extraction.validate.citations as citations

    assert not hasattr(citations, "verify_citations")
    assert citations.__all__ == ["citation_errors"]
