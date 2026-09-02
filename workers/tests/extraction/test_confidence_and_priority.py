"""Unscored means NULL, and priority is earned rather than assumed (#194).

Two constants that were pretending to be measurements.

``record_confidence`` was ``Decimal("0")`` on every proposal the pipeline ever
wrote, because 0004 declared the column ``NOT NULL`` and no calibrator exists
yet (#62). ``0`` is a legal value on the column's own ``BETWEEN 0 AND 1`` scale,
so nothing flagged it — and to a reviewer, or to any queue sorted by it, it reads
as "the extractor is certain this figure is wrong". Migration 0006 drops the
``NOT NULL``; NULL is the only spelling of "not scored".

``review_priority`` was the literal ``"high"`` for every proposal, which is the
same defect in the other direction: a queue in which everything is urgent has no
ordering at all. It is now derived from what the validator actually found.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fel_workers.extraction.hashing import sha256_hex
from fel_workers.extraction.validate import validate_proposals
from fel_workers.extraction.validate.pipeline import _review_priority_for

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_SPAN = "22222222-2222-4222-8222-222222222222"
_DOC = "33333333-3333-4333-8333-333333333333"


def _kpi(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": "44444444-4444-4444-8444-444444444444",
        "issuer_label": "Example SaaS",
        "metric_id": "arr",
        "raw_value": "$100 million",
        "value": "100000000",
        "unit": "currency",
        "currency": "USD",
        "scale": 0,
        "sign": "positive",
        "period": {"type": "instant", "end": "2026-06-30"},
        "dimensions": {},
        "qualifiers": {"currency": "USD", "construction": "gaap", "scope": "consolidated"},
        "reported_or_derived": "reported",
        "evidence": [
            {
                "source_span_id": _SPAN,
                "document_version_id": _DOC,
                "role": "supports",
                "text_hash": _TEXT_HASH,
            }
        ],
    }
    payload.update(overrides)
    return payload


_TEXT = "ARR was $100 million as of June 30, 2026."
_TEXT_HASH = sha256_hex(_TEXT)
_PINNED = {_SPAN: {"document_version_id": _DOC, "text": _TEXT, "text_hash": _TEXT_HASH}}


def _validate(payloads: list[dict[str, Any]]) -> Any:
    return validate_proposals(run_id=_RUN_ID, payloads=payloads, evidence_by_span=_PINNED)


# ---------------------------------------------------------------------------
# record_confidence
# ---------------------------------------------------------------------------


def test_unscored_proposals_carry_no_confidence() -> None:
    result = _validate([_kpi()])
    assert result.proposals
    for draft in result.proposals:
        assert draft.record_confidence is None
        # The point of the change: NULL is not zero, and must not compare as it.
        assert draft.record_confidence != Decimal("0")


def test_confidence_stays_none_even_when_the_proposal_is_blocked() -> None:
    """A blocker is a validation finding, not a score of zero.

    Conflating the two is exactly the reading `0` invited: "blocked" and "scored
    0" are different claims, and only one of them is one this pipeline can make.
    """
    result = _validate([_kpi(metric_id="not_a_real_metric_id")])
    assert result.proposals
    draft = result.proposals[0]
    assert draft.validation_summary["blockers"], "expected this payload to be blocked"
    assert draft.record_confidence is None


# ---------------------------------------------------------------------------
# review_priority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("blockers", "in_conflict", "expected"),
    [
        ([], False, "normal"),
        (["metric_unknown"], False, "high"),
        ([], True, "high"),
        (["metric_unknown"], True, "high"),
    ],
)
def test_priority_rule(blockers: list[str], in_conflict: bool, expected: str) -> None:
    assert _review_priority_for(blockers=blockers, in_conflict=in_conflict) == expected


def test_a_clean_proposal_is_normal_priority() -> None:
    result = _validate([_kpi()])
    draft = result.proposals[0]
    assert draft.validation_summary["blockers"] == []
    assert draft.review_priority == "normal", (
        "a proposal the validator had nothing to say about was still flagged "
        "urgent, which is how the column stopped carrying information"
    )


def test_a_blocked_proposal_is_high_priority() -> None:
    result = _validate([_kpi(metric_id="not_a_real_metric_id")])
    draft = result.proposals[0]
    assert draft.validation_summary["blockers"]
    assert draft.review_priority == "high"


def test_conflict_members_are_high_priority_even_when_individually_clean() -> None:
    """Two contradictory figures for one fact: neither is wrong on its own.

    Conflict membership is a property of the SET, computed after every
    per-payload check has passed, which is why the priority pass has to run last.
    """
    result = _validate([_kpi(), _kpi(value="200000000", raw_value="$200 million")])
    if not result.conflicts:
        pytest.skip("fixture did not produce a conflict group")
    members = {pid for group in result.conflicts for pid in group.member_proposal_ids}
    assert members
    for draft in result.proposals:
        if draft.id in members:
            assert draft.review_priority == "high"


def test_priority_is_deterministic_across_a_rebuild() -> None:
    """A resume rebuilds drafts from the checkpoint and must sort identically."""
    payloads = [_kpi(), _kpi(metric_id="not_a_real_metric_id")]
    first = _validate(payloads)
    second = _validate(payloads)
    assert [d.review_priority for d in first.proposals] == [
        d.review_priority for d in second.proposals
    ]
