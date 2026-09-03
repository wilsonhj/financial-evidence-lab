"""Typed, fail-closed errors for the calculation engine.

Every error carries a stable ``code`` so telemetry and API layers can classify
failures without parsing messages. Nothing in this package degrades silently:
a missing input, an incompatible unit, a cycle, or a temporal violation raises.
"""

from __future__ import annotations


class CalculationEngineError(Exception):
    """Base class for every engine failure."""

    code: str = "CALC_ERROR"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UnitError(CalculationEngineError):
    """Incompatible or malformed typed unit."""

    code = "UNIT_ERROR"


class PeriodError(CalculationEngineError):
    """Malformed fiscal period or period mismatch between operands."""

    code = "PERIOD_ERROR"


class ValueTypeError(CalculationEngineError):
    """A value that is not a finite ``Decimal`` (floats and NaN/Inf are rejected)."""

    code = "VALUE_TYPE_ERROR"


class NodeValidationError(CalculationEngineError):
    """A node definition violates its kind's invariants (lineage, inputs, identifiers)."""

    code = "NODE_VALIDATION_ERROR"


class LineageError(NodeValidationError):
    """Exactly-one-lineage-by-kind invariant violated."""

    code = "LINEAGE_ERROR"


class GraphError(CalculationEngineError):
    """Structural graph failure (dangling reference, duplicate node id)."""

    code = "GRAPH_ERROR"


class MissingInputError(GraphError):
    """A node references an input that does not exist in the snapshot."""

    code = "MISSING_INPUT"


class CycleError(GraphError):
    """The dependency graph contains a cycle; ``cycle`` is the offending node-id path."""

    code = "CYCLE_DETECTED"

    def __init__(self, cycle: tuple[str, ...]) -> None:
        super().__init__(f"dependency cycle: {' -> '.join(cycle)}", cycle=cycle)
        self.cycle = cycle


class CutoffViolationError(CalculationEngineError):
    """An input became public after the evaluation cutoff (Constitution I)."""

    code = "TEMPORAL_SCOPE_VIOLATION"


class FormulaError(CalculationEngineError):
    """Arithmetic could not be completed exactly (division by zero, overflow)."""

    code = "FORMULA_ERROR"


class ScenarioError(CalculationEngineError):
    """A scenario override targets a node that cannot be overridden."""

    code = "SCENARIO_ERROR"


class CanonicalizationError(CalculationEngineError):
    """A value cannot be encoded as typed canonical JSON (floats, naive datetimes, forged keys)."""

    code = "CANONICALIZATION_ERROR"


class SnapshotError(CalculationEngineError):
    """Snapshot store integrity failure (unknown id, content-hash mismatch)."""

    code = "SNAPSHOT_ERROR"


__all__ = [
    "CalculationEngineError",
    "CanonicalizationError",
    "CutoffViolationError",
    "CycleError",
    "FormulaError",
    "GraphError",
    "LineageError",
    "MissingInputError",
    "NodeValidationError",
    "PeriodError",
    "ScenarioError",
    "SnapshotError",
    "UnitError",
    "ValueTypeError",
]
