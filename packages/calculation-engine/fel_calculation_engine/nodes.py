"""The nine typed model-graph node kinds (T0401, spec §8.5, FR-MOD-001).

Every node is a frozen value object identified by a slug ``node_id`` and
carrying its typed ``unit`` and fiscal ``period``. Leaf kinds (source fact,
analyst assumption, scenario override, forecast model output) carry a finite
``Decimal`` value, a timezone-aware ``as_of`` publication timestamp and the one
lineage id their provenance kind requires. Derived kinds declare their inputs
as role-tagged node references — :meth:`Node.inputs` is the single source of
truth for the dependency edges (T0402).

Nothing here has an implicit default value: an assumption without a value is a
construction error, never a silent zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from fel_calculation_engine.errors import NodeValidationError
from fel_calculation_engine.periods import FiscalPeriod, FiscalYear
from fel_calculation_engine.units import Unit, UnitKind
from fel_calculation_engine.values import (
    Lineage,
    Provenance,
    Quantity,
    require_decimal,
    require_safe_id,
)


class NodeKind(StrEnum):
    SOURCE_FACT = "source_fact"
    ANALYST_ASSUMPTION = "analyst_assumption"
    OPERATIONAL_DRIVER = "operational_driver"
    FORMULA = "formula"
    AGGREGATION = "aggregation"
    SCENARIO_OVERRIDE = "scenario_override"
    FORECAST_MODEL_OUTPUT = "forecast_model_output"
    VALIDATION_CHECK = "validation_check"
    REPORTED_FINANCIAL_OUTPUT = "reported_financial_output"


class Operator(StrEnum):
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"


class AggregationOp(StrEnum):
    SUM = "sum"
    ROLLUP_YEAR = "rollup_year"


class CheckOp(StrEnum):
    EQUALS = "equals"
    NON_NEGATIVE = "non_negative"
    LESS_OR_EQUAL = "less_or_equal"
    GREATER_OR_EQUAL = "greater_or_equal"


def _node_id(value: object, field: str) -> str:
    return require_safe_id(value, field, NodeValidationError)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NodeValidationError(f"{field} must be a timezone-aware datetime", field=field)
    return value


def _operands(node_id: str, operands: object, *, minimum: int, exact: int | None) -> None:
    if not isinstance(operands, tuple):
        raise NodeValidationError(f"{node_id}: operands must be a tuple of node ids")
    for operand in operands:
        _node_id(operand, "operand")
    if exact is not None and len(operands) != exact:
        raise NodeValidationError(f"{node_id}: expected exactly {exact} operands")
    if len(operands) < minimum:
        raise NodeValidationError(f"{node_id}: expected at least {minimum} operands")
    if len(set(operands)) != len(operands):
        raise NodeValidationError(f"{node_id}: operands must be distinct")
    if node_id in operands:
        raise NodeValidationError(f"{node_id}: a node cannot depend on itself")


@dataclass(frozen=True, slots=True)
class Node:
    """Base shape shared by every node kind. Do not instantiate directly."""

    kind: ClassVar[NodeKind]
    provenance: ClassVar[Provenance]

    node_id: str
    label: str
    unit: Unit
    period: FiscalPeriod

    def __post_init__(self) -> None:
        if type(self) is Node:
            raise NodeValidationError("Node is abstract")
        _node_id(self.node_id, "node_id")
        if not isinstance(self.label, str):
            raise NodeValidationError(f"{self.node_id}: label must be a string")
        if not isinstance(self.unit, Unit):
            raise NodeValidationError(f"{self.node_id}: unit must be a Unit")
        if not isinstance(self.period, FiscalPeriod) or type(self.period) is FiscalPeriod:
            raise NodeValidationError(f"{self.node_id}: period must be a FiscalQuarter/FiscalYear")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        """Role-tagged ``(role, node_id)`` dependencies in declaration order."""
        return ()


@dataclass(frozen=True, slots=True)
class _LeafNode(Node):
    value: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        require_decimal(self.value, f"{self.node_id}.value")
        _aware(self.as_of, f"{self.node_id}.as_of")

    def lineage(self) -> Lineage:
        raise NotImplementedError

    def lineage_quantity(self) -> Quantity:
        return Quantity(self.value, self.unit)


@dataclass(frozen=True, slots=True)
class SourceFactNode(_LeafNode):
    """A value reported verbatim by an immutable source span (approved extraction)."""

    kind: ClassVar[NodeKind] = NodeKind.SOURCE_FACT
    provenance: ClassVar[Provenance] = Provenance.REPORTED

    source_span_id: str
    fact_id: str | None = None

    def __post_init__(self) -> None:
        _LeafNode.__post_init__(self)
        _node_id(self.source_span_id, f"{self.node_id}.source_span_id")
        if self.fact_id is not None:
            _node_id(self.fact_id, f"{self.node_id}.fact_id")

    def lineage(self) -> Lineage:
        return Lineage(Provenance.REPORTED, source_span_id=self.source_span_id)


@dataclass(frozen=True, slots=True)
class AnalystAssumptionNode(_LeafNode):
    """A user-supplied value. Explicit only — there is no default."""

    kind: ClassVar[NodeKind] = NodeKind.ANALYST_ASSUMPTION
    provenance: ClassVar[Provenance] = Provenance.ASSUMPTION

    assumption_id: str

    def __post_init__(self) -> None:
        _LeafNode.__post_init__(self)
        _node_id(self.assumption_id, f"{self.node_id}.assumption_id")

    def lineage(self) -> Lineage:
        return Lineage(Provenance.ASSUMPTION, assumption_id=self.assumption_id)


@dataclass(frozen=True, slots=True)
class ForecastModelOutputNode(_LeafNode):
    """Output of an immutable forecast run (FR-FOR-002: dataset version and cutoff pinned)."""

    kind: ClassVar[NodeKind] = NodeKind.FORECAST_MODEL_OUTPUT
    provenance: ClassVar[Provenance] = Provenance.FORECAST

    forecast_run_id: str
    dataset_cutoff: datetime
    dataset_version: str

    def __post_init__(self) -> None:
        _LeafNode.__post_init__(self)
        _node_id(self.forecast_run_id, f"{self.node_id}.forecast_run_id")
        _node_id(self.dataset_version, f"{self.node_id}.dataset_version")
        _aware(self.dataset_cutoff, f"{self.node_id}.dataset_cutoff")

    def lineage(self) -> Lineage:
        return Lineage(Provenance.FORECAST, forecast_run_id=self.forecast_run_id)


@dataclass(frozen=True, slots=True)
class ScenarioOverrideNode(_LeafNode):
    """A sparse scenario override shadowing ``target``; user-supplied, so ASSUMPTION lineage."""

    kind: ClassVar[NodeKind] = NodeKind.SCENARIO_OVERRIDE
    provenance: ClassVar[Provenance] = Provenance.ASSUMPTION

    target: str
    scenario_id: str
    assumption_id: str

    def __post_init__(self) -> None:
        _LeafNode.__post_init__(self)
        _node_id(self.target, f"{self.node_id}.target")
        _node_id(self.scenario_id, f"{self.node_id}.scenario_id")
        _node_id(self.assumption_id, f"{self.node_id}.assumption_id")
        if self.target == self.node_id:
            raise NodeValidationError(f"{self.node_id}: override cannot target itself")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return (("overrides", self.target),)

    def lineage(self) -> Lineage:
        return Lineage(Provenance.ASSUMPTION, assumption_id=self.assumption_id)


@dataclass(frozen=True, slots=True)
class OperationalDriverNode(Node):
    """A named driver seeded from one upstream node (an approved fact or an assumption)."""

    kind: ClassVar[NodeKind] = NodeKind.OPERATIONAL_DRIVER
    provenance: ClassVar[Provenance] = Provenance.DERIVED

    seed: str

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        _node_id(self.seed, f"{self.node_id}.seed")
        if self.seed == self.node_id:
            raise NodeValidationError(f"{self.node_id}: driver cannot seed itself")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return (("seed", self.seed),)


@dataclass(frozen=True, slots=True)
class FormulaNode(Node):
    """A versioned arithmetic formula over same-period-kind operands."""

    kind: ClassVar[NodeKind] = NodeKind.FORMULA
    provenance: ClassVar[Provenance] = Provenance.DERIVED

    operator: Operator
    operands: tuple[str, ...]
    formula_version: str

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        if not isinstance(self.operator, Operator):
            raise NodeValidationError(f"{self.node_id}: operator must be an Operator")
        exact = 2 if self.operator in (Operator.SUB, Operator.DIV) else None
        _operands(self.node_id, self.operands, minimum=2, exact=exact)
        _node_id(self.formula_version, f"{self.node_id}.formula_version")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return tuple((f"operand[{i}]", operand) for i, operand in enumerate(self.operands))


@dataclass(frozen=True, slots=True)
class AggregationNode(Node):
    """Sum across operands (same period) or roll four quarters up into a fiscal year."""

    kind: ClassVar[NodeKind] = NodeKind.AGGREGATION
    provenance: ClassVar[Provenance] = Provenance.DERIVED

    operator: AggregationOp
    operands: tuple[str, ...]

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        if not isinstance(self.operator, AggregationOp):
            raise NodeValidationError(f"{self.node_id}: operator must be an AggregationOp")
        if self.operator is AggregationOp.ROLLUP_YEAR:
            _operands(self.node_id, self.operands, minimum=4, exact=4)
            if not isinstance(self.period, FiscalYear):
                raise NodeValidationError(
                    f"{self.node_id}: rollup_year output must be a FiscalYear"
                )
        else:
            _operands(self.node_id, self.operands, minimum=1, exact=None)

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return tuple((f"operand[{i}]", operand) for i, operand in enumerate(self.operands))


@dataclass(frozen=True, slots=True)
class ValidationCheckNode(Node):
    """A deterministic check over operands; evaluates to a passed/failed result."""

    kind: ClassVar[NodeKind] = NodeKind.VALIDATION_CHECK
    provenance: ClassVar[Provenance] = Provenance.DERIVED

    check: CheckOp
    operands: tuple[str, ...]
    tolerance: Decimal | None = None

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        if not isinstance(self.check, CheckOp):
            raise NodeValidationError(f"{self.node_id}: check must be a CheckOp")
        exact = 1 if self.check is CheckOp.NON_NEGATIVE else 2
        _operands(self.node_id, self.operands, minimum=exact, exact=exact)
        if self.tolerance is not None:
            tolerance = require_decimal(self.tolerance, f"{self.node_id}.tolerance")
            if tolerance < 0:
                raise NodeValidationError(f"{self.node_id}: tolerance must be non-negative")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return tuple((f"operand[{i}]", operand) for i, operand in enumerate(self.operands))


@dataclass(frozen=True, slots=True)
class ReportedFinancialOutputNode(Node):
    """The graph edge where a derived value is quantized for reporting (once, never upstream)."""

    kind: ClassVar[NodeKind] = NodeKind.REPORTED_FINANCIAL_OUTPUT
    provenance: ClassVar[Provenance] = Provenance.DERIVED

    source: str
    metric_id: str
    quantum: Decimal | None = None

    def __post_init__(self) -> None:
        Node.__post_init__(self)
        _node_id(self.source, f"{self.node_id}.source")
        _node_id(self.metric_id, f"{self.node_id}.metric_id")
        if self.source == self.node_id:
            raise NodeValidationError(f"{self.node_id}: output cannot report itself")
        if self.quantum is None:
            if self.unit.kind is not UnitKind.CURRENCY:
                raise NodeValidationError(
                    f"{self.node_id}: non-currency outputs need an explicit quantum"
                )
        else:
            quantum = require_decimal(self.quantum, f"{self.node_id}.quantum")
            if quantum <= 0:
                raise NodeValidationError(f"{self.node_id}: quantum must be positive")

    def inputs(self) -> tuple[tuple[str, str], ...]:
        return (("source", self.source),)


LeafNode = SourceFactNode | AnalystAssumptionNode | ForecastModelOutputNode | ScenarioOverrideNode

__all__ = [
    "AggregationNode",
    "AggregationOp",
    "AnalystAssumptionNode",
    "CheckOp",
    "ForecastModelOutputNode",
    "FormulaNode",
    "LeafNode",
    "Node",
    "NodeKind",
    "OperationalDriverNode",
    "Operator",
    "ReportedFinancialOutputNode",
    "ScenarioOverrideNode",
    "SourceFactNode",
    "ValidationCheckNode",
]
