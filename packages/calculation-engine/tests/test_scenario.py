"""Sparse scenario layers: applying one yields a new snapshot and never mutates the base (T0403)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from _fixtures import AS_OF, CUTOFF, revenue_model

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.errors import MissingInputError, ScenarioError, ValueTypeError
from fel_calculation_engine.nodes import NodeKind
from fel_calculation_engine.scenario import Scenario, apply_scenario
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.values import Provenance


def _bull() -> Scenario:
    return Scenario.of("bull", "Bull case", {"growth": Decimal("0.25")}, as_of=AS_OF)


def test_apply_scenario_yields_a_child_snapshot_and_leaves_the_base_untouched() -> None:
    base = GraphSnapshot.build("m", revenue_model())
    before = base.canonical_json()
    base_ids = {n.node_id: id(n) for n in base.nodes}
    bull = apply_scenario(base, _bull())
    assert base.canonical_json() == before
    assert {n.node_id: id(n) for n in base.nodes} == base_ids
    assert bull.parent_snapshot_id == base.snapshot_id
    assert bull.scenario_id == "bull"
    assert bull.version == base.version + 1
    assert bull.snapshot_id != base.snapshot_id


def test_scenario_override_shadows_the_target_for_every_dependent() -> None:
    base = GraphSnapshot.build("m", revenue_model())
    bull = apply_scenario(base, _bull())
    override = next(n for n in bull.nodes if n.kind is NodeKind.SCENARIO_OVERRIDE)
    assert override.target == "growth"  # type: ignore[attr-defined]
    assert bull.graph.node("growth-factor").operands == ("one", override.node_id)  # type: ignore[attr-defined]
    assert bull.graph.dependents("growth") == (override.node_id,)
    base_run = evaluate(base, cutoff=CUTOFF)
    bull_run = evaluate(bull, cutoff=CUTOFF)
    assert bull_run.quantity("growth-factor").value == Decimal("1.25")
    assert bull_run.quantity("revenue-next").value == Decimal("24987.5000")
    assert base_run.quantity("revenue-next").value == Decimal("21989.0000")
    assert bull_run.result(override.node_id).provenance is Provenance.ASSUMPTION
    assert bull_run.result(override.node_id).lineage.assumption_id == "bull:growth"
    assert bull_run.result("revenue").result_id == base_run.result("revenue").result_id
    assert bull_run.result("growth").result_id == base_run.result("growth").result_id
    assert bull_run.result("revenue-next").result_id != base_run.result("revenue-next").result_id


def test_scenarios_layer_over_scenarios() -> None:
    base = GraphSnapshot.build("m", revenue_model())
    bull = apply_scenario(base, _bull())
    bear = apply_scenario(
        bull, Scenario.of("bear", "Bear", {"growth": Decimal("0.01")}, as_of=AS_OF)
    )
    assert evaluate(bear, cutoff=CUTOFF).quantity("growth-factor").value == Decimal("1.01")
    assert evaluate(bull, cutoff=CUTOFF).quantity("growth-factor").value == Decimal("1.25")
    assert bear.parent_snapshot_id == bull.snapshot_id


def test_scenario_is_sparse_immutable_and_validated() -> None:
    scenario = _bull()
    assert scenario.overrides == (("growth", Decimal("0.25")),)
    with pytest.raises(AttributeError):
        scenario.overrides = ()  # type: ignore[misc]
    with pytest.raises(ValueTypeError):
        Scenario.of("bull", "Bull", {"growth": 0.25}, as_of=AS_OF)  # type: ignore[dict-item]
    with pytest.raises(ScenarioError):
        Scenario.of("bull", "Bull", {}, as_of=AS_OF)
    with pytest.raises(ScenarioError):
        Scenario.of("bull case", "Bull", {"growth": Decimal("1")}, as_of=AS_OF)


def test_scenario_rejects_unknown_or_non_overridable_targets() -> None:
    base = GraphSnapshot.build("m", revenue_model())
    with pytest.raises(MissingInputError):
        apply_scenario(base, Scenario.of("s", "s", {"ghost": Decimal("1")}, as_of=AS_OF))
    with pytest.raises(ScenarioError):
        apply_scenario(base, Scenario.of("s", "s", {"price": Decimal("1")}, as_of=AS_OF))
    with pytest.raises(ScenarioError):
        apply_scenario(base, Scenario.of("s", "s", {"revenue": Decimal("1")}, as_of=AS_OF))
    # Drivers are overridable.
    driven = apply_scenario(base, Scenario.of("s", "s", {"units": Decimal("10")}, as_of=AS_OF))
    assert evaluate(driven, cutoff=CUTOFF).quantity("revenue").value == Decimal("199.90")
