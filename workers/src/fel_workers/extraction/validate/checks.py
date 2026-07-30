"""Facade re-exporting live-path validators (kept for import stability)."""

from __future__ import annotations

from fel_ontology import load_saas_metrics
from fel_ontology.models import OntologyDocument
from fel_workers.extraction.validate.accounting import accounting_errors
from fel_workers.extraction.validate.citations import citation_errors
from fel_workers.extraction.validate.definitions import check_definitions, definition_errors
from fel_workers.extraction.validate.duplicates import (
    conflict_key_for,
    duplicate_groups,
    value_fingerprint,
)
from fel_workers.extraction.validate.range import range_errors
from fel_workers.extraction.validate.schema import validate_payload_item


def default_ontology() -> OntologyDocument:
    return load_saas_metrics()


__all__ = [
    "accounting_errors",
    "check_definitions",
    "citation_errors",
    "conflict_key_for",
    "default_ontology",
    "definition_errors",
    "duplicate_groups",
    "range_errors",
    "validate_payload_item",
    "value_fingerprint",
]
