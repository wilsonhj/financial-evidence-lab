"""Runtime command models consume the exact committed strict contract fixtures."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.extraction import models

FIXTURES = Path(__file__).resolve().parents[4] / "packages/contracts/fixtures"


@pytest.mark.parametrize(
    "case",
    json.loads((FIXTURES / "extraction-review-cases.valid.json").read_text()),
    ids=lambda case: case["name"],
)
def test_valid_contract_commands(case):
    assert hasattr(models, "REVIEW_ADAPTER"), "review command boundary is missing"
    command = models.REVIEW_ADAPTER.validate_python(case["command"])
    assert command.model_dump(mode="json", exclude_unset=True) == case["command"]


@pytest.mark.parametrize(
    "case",
    json.loads((FIXTURES / "extraction-review-cases.invalid.json").read_text()),
    ids=lambda case: case["name"],
)
def test_invalid_contract_commands(case):
    assert hasattr(models, "REVIEW_ADAPTER"), "review command boundary is missing"
    with pytest.raises(ValidationError):
        models.REVIEW_ADAPTER.validate_python(case["command"])


@pytest.mark.parametrize("bad", [True, "1", 0, -1])
def test_precondition_versions_are_positive_json_integers(bad):
    assert hasattr(models, "REVIEW_ADAPTER"), "review command boundary is missing"
    ident = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(ValidationError):
        models.REVIEW_ADAPTER.validate_python(
            {
                "action": "accept",
                "extraction_ids": [ident],
                "expected_versions": {ident: bad},
                "reason": "reviewed",
            }
        )


@pytest.mark.parametrize("field", ["expected_versions", "member_versions"])
@pytest.mark.parametrize("alias", ["upper", "hex", "urn"])
def test_version_maps_reject_canonical_uuid_collisions(field, alias):
    ident = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    spelling = {"upper": str(ident).upper(), "hex": ident.hex, "urn": ident.urn}[alias]
    values = {str(ident): 2, spelling: 1}
    with pytest.raises(ValidationError):
        if field == "expected_versions":
            models.REVIEW_ADAPTER.validate_python(
                {
                    "action": "accept",
                    "extraction_ids": [str(ident)],
                    field: values,
                    "reason": "Checked source.",
                }
            )
        else:
            models.ConflictDecision.model_validate(
                {
                    "conflict_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "expected_etag": '"snapshot"',
                    field: {**values, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": 1},
                    "selected_winner_ids": [str(ident)],
                    "reason": "Checked group.",
                }
            )


def test_unique_uppercase_version_ids_remain_valid():
    first = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    second = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
    command = models.REVIEW_ADAPTER.validate_python(
        {
            "action": "accept",
            "extraction_ids": [first],
            "expected_versions": {first: 1},
            "reason": "Checked source.",
            "conflict_resolution": [
                {
                    "conflict_id": "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC",
                    "expected_etag": '"snapshot"',
                    "member_versions": {first: 1, second: 1},
                    "selected_winner_ids": [first],
                    "reason": "Checked group.",
                }
            ],
        }
    )
    assert command.expected_versions == {UUID(first): 1}
    assert command.conflict_resolution[0].member_versions == {UUID(first): 1, UUID(second): 1}
