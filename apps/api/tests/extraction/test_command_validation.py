"""Runtime command models consume the exact committed strict contract fixtures."""

import json
from pathlib import Path

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
