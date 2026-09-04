"""Financial Evidence Lab typed model graph and Decimal calculation engine (M4-MODEL-CALC / #63).

Public surface: node kinds (:mod:`nodes`), typed units (:mod:`units`) and
fiscal periods (:mod:`periods`), Decimal-only values and lineage
(:mod:`values`), versioned content-addressed snapshots (:mod:`snapshot`,
:mod:`store`), the evaluator (:mod:`engine`), sparse scenarios
(:mod:`scenario`) and redacted telemetry (:mod:`telemetry`).
"""

from __future__ import annotations

from fel_calculation_engine.canonical import canonical_json, content_hash
from fel_calculation_engine.engine import CalcResult, EvaluationResult, evaluate
from fel_calculation_engine.errors import (
    CalculationEngineError,
    CanonicalizationError,
    CutoffViolationError,
    CycleError,
    FormulaError,
    GraphError,
    LineageError,
    MissingInputError,
    NodeValidationError,
    PeriodError,
    ScenarioError,
    SnapshotError,
    UnitError,
    ValueTypeError,
)
from fel_calculation_engine.graph import Edge, ModelGraph
from fel_calculation_engine.nodes import (
    AggregationNode,
    AggregationOp,
    AnalystAssumptionNode,
    CheckOp,
    ForecastModelOutputNode,
    FormulaNode,
    Node,
    NodeKind,
    OperationalDriverNode,
    Operator,
    ReportedFinancialOutputNode,
    ScenarioOverrideNode,
    SourceFactNode,
    ValidationCheckNode,
)
from fel_calculation_engine.periods import (
    FiscalCalendar,
    FiscalPeriod,
    FiscalQuarter,
    FiscalYear,
    PeriodKind,
    parse_period,
)
from fel_calculation_engine.rounding import minor_unit_quantum
from fel_calculation_engine.scenario import Scenario, apply_scenario
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.store import InMemorySnapshotStore, SnapshotStore
from fel_calculation_engine.synthetic import build_synthetic_model
from fel_calculation_engine.telemetry import LoggingSink, RecordingSink, TelemetrySink
from fel_calculation_engine.units import COUNT, PERCENT, RATIO, Unit, UnitKind, currency
from fel_calculation_engine.values import (
    CALC_CONTEXT,
    Lineage,
    Provenance,
    Quantity,
    canonical_decimal,
    require_decimal,
)

__all__ = [
    "CALC_CONTEXT",
    "COUNT",
    "PERCENT",
    "RATIO",
    "AggregationNode",
    "AggregationOp",
    "AnalystAssumptionNode",
    "CalcResult",
    "CalculationEngineError",
    "CanonicalizationError",
    "CheckOp",
    "CutoffViolationError",
    "CycleError",
    "Edge",
    "EvaluationResult",
    "FiscalCalendar",
    "FiscalPeriod",
    "FiscalQuarter",
    "FiscalYear",
    "ForecastModelOutputNode",
    "FormulaError",
    "FormulaNode",
    "GraphError",
    "GraphSnapshot",
    "InMemorySnapshotStore",
    "Lineage",
    "LineageError",
    "LoggingSink",
    "MissingInputError",
    "ModelGraph",
    "Node",
    "NodeKind",
    "NodeValidationError",
    "OperationalDriverNode",
    "Operator",
    "PeriodError",
    "PeriodKind",
    "Provenance",
    "Quantity",
    "RecordingSink",
    "ReportedFinancialOutputNode",
    "Scenario",
    "ScenarioError",
    "ScenarioOverrideNode",
    "SnapshotError",
    "SnapshotStore",
    "SourceFactNode",
    "TelemetrySink",
    "Unit",
    "UnitError",
    "UnitKind",
    "ValidationCheckNode",
    "ValueTypeError",
    "apply_scenario",
    "build_synthetic_model",
    "canonical_decimal",
    "canonical_json",
    "content_hash",
    "currency",
    "evaluate",
    "minor_unit_quantum",
    "parse_period",
    "require_decimal",
]
