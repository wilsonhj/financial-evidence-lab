"""Typed extraction failures (ADR-0007 / M3-WF-010).

Provider/schema/budget/cancel/lease/integrity failures terminate before review
and never emit unvalidated proposals. Abstention is *not* a failure — see
:class:`~fel_workers.extraction.runner.Abstention`.
"""

from __future__ import annotations


class ExtractionError(Exception):
    """Base typed extraction failure."""

    code: str = "extraction_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class StepFailed(ExtractionError):
    """Typed terminal step failure. Fails before review (M3-WF-010)."""

    code = "step_failed"


class BudgetExceeded(StepFailed):
    """An ADR-0007 hard cap would be (or was) breached."""

    code = "budget_exceeded"


class Cancelled(StepFailed):
    """Run cancellation observed at a stage boundary."""

    code = "cancelled"


class LeaseLost(StepFailed):
    """Queue lease fencing lost; worker must not write terminal results."""

    code = "lease_lost"


class ProviderRefused(StepFailed):
    """Provider refusal — never an abstention (injection vector otherwise)."""

    code = "provider_refused"


class ProviderError(StepFailed):
    """Provider raised, returned unparseable output, or violated pin."""

    code = "provider_error"


class SchemaInvalid(StepFailed):
    """Output failed schema validation after the single permitted repair."""

    code = "schema_invalid"


class IntegrityError(StepFailed):
    """Span hash / document-version / evidence integrity failure."""

    code = "integrity_error"


class CutoffViolation(StepFailed):
    """Evidence is not cutoff-visible for the pinned as_of."""

    code = "cutoff_violation"


__all__ = [
    "BudgetExceeded",
    "Cancelled",
    "CutoffViolation",
    "ExtractionError",
    "IntegrityError",
    "LeaseLost",
    "ProviderError",
    "ProviderRefused",
    "SchemaInvalid",
    "StepFailed",
]
