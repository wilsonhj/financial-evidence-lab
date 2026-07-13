"""Findings 17 + 20: the shared ingestion error hierarchy and the CLOSED
quarantine reason-code enum. Every reason code minted anywhere in the worker
sources must be a ReasonCode member."""

from __future__ import annotations

import pathlib
import re

import pytest

from fel_workers.ingestion.errors import (
    DivergentAccessionError,
    IngestError,
    NormalizationError,
    ParseError,
    ReasonCode,
)

SRC = pathlib.Path(__file__).parents[1] / "src" / "fel_workers"


def test_parse_and_normalization_errors_share_the_ingest_base() -> None:
    """Finding 17: one base class carries reason_code + diagnostic; the
    pipeline quarantines on the base."""
    assert issubclass(ParseError, IngestError)
    assert issubclass(NormalizationError, IngestError)
    assert issubclass(DivergentAccessionError, IngestError)
    error = ParseError(ReasonCode.EMPTY_DOCUMENT, "nothing to parse")
    assert error.reason_code == "EMPTY_DOCUMENT"
    assert error.diagnostic == "nothing to parse"
    assert str(error) == "nothing to parse"


def test_divergent_accession_error_carries_conflict_details() -> None:
    error = DivergentAccessionError(
        "bytes changed",
        document_id="doc-1",
        existing_content_hash="sha256:" + "a" * 64,
        new_content_hash="sha256:" + "b" * 64,
    )
    assert error.reason_code == "DIVERGENT_ACCESSION_CONTENT"
    assert error.document_id == "doc-1"
    assert error.existing_content_hash != error.new_content_hash


def test_unknown_reason_codes_cannot_be_minted() -> None:
    """Finding 20: the code set is closed — constructing any ingest error
    with a code outside the enum fails loudly."""
    for exc_type in (IngestError, ParseError, NormalizationError):
        with pytest.raises(ValueError):
            exc_type("MADE_UP_CODE", "should not construct")


def test_invalid_period_collision_is_split() -> None:
    """Finding 20: the old ambiguous INVALID_PERIOD is gone, split into the
    parser-side date error and the normalizer-side structure error."""
    assert "INVALID_PERIOD" not in ReasonCode.__members__
    assert ReasonCode.INVALID_PERIOD_DATE.value == "INVALID_PERIOD_DATE"
    assert ReasonCode.INVALID_PERIOD_STRUCTURE.value == "INVALID_PERIOD_STRUCTURE"


def test_every_reason_code_minted_in_source_is_in_the_enum() -> None:
    """Finding 20: scan the worker sources for reason-code call sites; every
    string literal or ReasonCode attribute used must be an enum member."""
    literal_call = re.compile(
        r"(?:ParseError|NormalizationError|IngestError|_ValueRejected)\(\s*[\"']([A-Z_]+)[\"']"
    )
    attribute_use = re.compile(r"ReasonCode\.([A-Z_]+)")
    minted: set[str] = set()
    for path in SRC.rglob("*.py"):
        source = path.read_text()
        minted.update(literal_call.findall(source))
        minted.update(attribute_use.findall(source))
    assert minted, "expected at least one reason-code call site in the sources"
    unknown = {code for code in minted if code not in ReasonCode.__members__}
    assert not unknown, f"reason codes minted outside the closed enum: {sorted(unknown)}"
