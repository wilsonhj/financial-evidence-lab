"""Shared ingestion error hierarchy and the closed quarantine reason-code set.

Every quarantineable failure in the ingestion pipeline carries a stable
``reason_code`` (a member of :class:`ReasonCode`) plus an operator-actionable
``diagnostic``. The code set is CLOSED: constructing an :class:`IngestError`
(or any subclass) with a code outside the enum raises ``ValueError``, so a
new code can only be minted by adding it here — one place to audit.

``ParseError`` and ``NormalizationError`` are kept as distinct names for API
stability (callers match on them), but both are thin subclasses of
:class:`IngestError`; the pipeline quarantines on the base class.
"""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    """Closed set of stable quarantine reason codes."""

    # Parser-side (malformed source document).
    ENCODING_ERROR = "ENCODING_ERROR"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    INCOMPLETE_FACT = "INCOMPLETE_FACT"
    UNKNOWN_CONTEXT = "UNKNOWN_CONTEXT"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    INVALID_SCALE = "INVALID_SCALE"
    # A context period date fails to parse as an ISO date (was one half of
    # the old ambiguous INVALID_PERIOD, split per finding 20).
    INVALID_PERIOD_DATE = "INVALID_PERIOD_DATE"
    # Normalizer-side (facts cannot be normalized).
    # A context has neither an instant nor a complete start/end duration
    # (the other half of the old INVALID_PERIOD collision).
    INVALID_PERIOD_STRUCTURE = "INVALID_PERIOD_STRUCTURE"
    EMPTY_FACT_VALUE = "EMPTY_FACT_VALUE"
    UNPARSEABLE_FACT_VALUE = "UNPARSEABLE_FACT_VALUE"
    NONFINITE_FACT_VALUE = "NONFINITE_FACT_VALUE"
    UNKNOWN_FORMAT = "UNKNOWN_FORMAT"
    INCONSISTENT_DUPLICATE = "INCONSISTENT_DUPLICATE"
    # Raw-store side: a re-fetch of an already-recorded accession returned
    # different bytes; provenance would be corrupted, so we fail closed.
    DIVERGENT_ACCESSION_CONTENT = "DIVERGENT_ACCESSION_CONTENT"


class IngestError(Exception):
    """Base for quarantineable ingestion failures.

    ``reason_code`` is stable (a :class:`ReasonCode` value); ``diagnostic``
    is an actionable operator-readable message.
    """

    def __init__(self, reason_code: str, diagnostic: str) -> None:
        # Closed-set enforcement (finding 20): unknown codes cannot be minted.
        code = ReasonCode(reason_code)
        super().__init__(diagnostic)
        self.reason_code: str = code.value
        self.diagnostic = diagnostic


class ParseError(IngestError):
    """Malformed source; kept as a distinct name for API stability."""


class NormalizationError(IngestError):
    """Fact cannot be normalized; kept as a distinct name for API stability."""


class DivergentAccessionError(IngestError):
    """Same accession re-fetched with different bytes (fail closed).

    Carries the existing document id and both content hashes so the
    quarantine row and the ingestion-run ledger can point at the conflict.
    """

    def __init__(
        self,
        diagnostic: str,
        *,
        document_id: str,
        existing_content_hash: str,
        new_content_hash: str,
    ) -> None:
        super().__init__(ReasonCode.DIVERGENT_ACCESSION_CONTENT, diagnostic)
        self.document_id = document_id
        self.existing_content_hash = existing_content_hash
        self.new_content_hash = new_content_hash
