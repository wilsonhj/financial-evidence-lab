"""Property tests over seeded deterministic generators (T0409).

Covers decimal arithmetic, unit algebra, fiscal periods, cycle detection and
scenario immutability. Each case is reproducible from the seed in its message.
"""

from __future__ import annotations

import dataclasses
from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from _fixtures import AS_OF, CUTOFF, USD, assumption, driver, formula, output, source
from _gen import cases, dag, decimal, nonzero_decimal, quarter, unit, year

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.errors import CycleError, FormulaError, PeriodError, UnitError
from fel_calculation_engine.graph import ModelGraph
from fel_calculation_engine.nodes import FormulaNode, Operator
from fel_calculation_engine.periods import FiscalCalendar, FiscalYear, parse_period
from fel_calculation_engine.scenario import Scenario, apply_scenario
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.units import COUNT, PERCENT, RATIO, Unit, UnitKind
from fel_calculation_engine.values import Quantity

# --- decimal arithmetic -----------------------------------------------------------------------


def test_addition_is_exact_commutative_and_associative() -> None:
    for seed, rng in cases():
        a, b, c = (Quantity(decimal(rng), USD) for _ in range(3))
        assert (a + b).value == (b + a).value, seed
        assert ((a + b) + c).value == (a + (b + c)).value, seed
        assert ((a + b) - b).value == a.value, seed
        assert type((a + b).value) is Decimal, seed


def test_multiplication_is_exact_commutative_associative_and_distributive() -> None:
    for seed, rng in cases():
        a, b, c = (Quantity(decimal(rng, digits=8, places=4), RATIO) for _ in range(3))
        assert (a * b).value == (b * a).value, seed
        assert ((a * b) * c).value == (a * (b * c)).value, seed
        assert (a * (b + c)).value == (a * b + a * c).value, seed


def test_exact_quotients_invert_products_and_zero_divisors_fail_closed() -> None:
    for seed, rng in cases():
        a = Quantity(decimal(rng, digits=8, places=4), USD)
        b = Quantity(nonzero_decimal(rng, digits=8, places=4), RATIO)
        assert ((a * b) / b).value == a.value, seed
        with pytest.raises(FormulaError):
            _ = a / Quantity(Decimal("0"), RATIO)


def test_quantize_is_idempotent_and_ties_go_to_even() -> None:
    quantum = Decimal("0.01")
    for seed, rng in cases():
        q = Quantity(decimal(rng), USD)
        once = q.quantize(quantum)
        assert once.quantize(quantum) == once, seed
        assert once.value == q.value.quantize(quantum, rounding=ROUND_HALF_EVEN), seed
        assert abs(once.value - q.value) <= Decimal("0.005"), seed


# --- units --------------------------------------------------------------------------------------


def test_addition_requires_identical_units() -> None:
    for seed, rng in cases():
        u, v = unit(rng), unit(rng)
        if u == v:
            assert u.add(v) == u and u.sub(v) == u, seed
        else:
            with pytest.raises(UnitError):
                u.add(v)


def test_multiplication_is_commutative_and_ratio_is_the_identity() -> None:
    for seed, rng in cases():
        u, v = unit(rng), unit(rng)
        try:
            forward = u.mul(v)
        except UnitError:
            with pytest.raises(UnitError):
                v.mul(u)
            continue
        assert v.mul(u) == forward, seed
        if u.kind is not UnitKind.PERCENT:
            assert u.mul(RATIO) == u and u.div(RATIO) == u, seed


def test_every_non_percent_unit_divided_by_itself_is_a_ratio() -> None:
    for seed, rng in cases():
        u = unit(rng, allow_percent=False)
        assert u.div(u) == RATIO, seed
        assert Unit.parse(u.key()) == u, seed


def test_percent_normalization_round_trips_exactly() -> None:
    for seed, rng in cases():
        p = Quantity(decimal(rng), PERCENT)
        assert p.to_ratio().to_percent() == p, seed
        assert p.to_ratio().value == p.value / Decimal(100), seed
        with pytest.raises(UnitError):
            _ = p * Quantity(Decimal(1), USD)


# --- periods ------------------------------------------------------------------------------------


def test_quarter_shift_is_a_group_action_consistent_with_ordering() -> None:
    for seed, rng in cases():
        q = quarter(rng)
        n, m = rng.randint(-40, 40), rng.randint(-40, 40)
        assert q.shift(n).shift(-n) == q, seed
        assert q.shift(n).shift(m) == q.shift(n + m), seed
        assert (q.shift(n) > q) is (n > 0), seed
        assert (q.shift(n) == q) is (n == 0), seed
        assert q.shift(4).year == q.year.shift(1), seed
        assert q in q.year.quarters(), seed
        assert parse_period(q.key()) == q, seed
        with pytest.raises(PeriodError):
            _ = q < FiscalYear(q.fiscal_year)


def test_sorting_quarters_matches_shift_order() -> None:
    for seed, rng in cases(50):
        base = quarter(rng)
        offsets = rng.sample(range(-30, 30), 12)
        quarters = [base.shift(o) for o in offsets]
        assert sorted(quarters) == [base.shift(o) for o in sorted(offsets)], seed


def test_fiscal_calendar_quarters_partition_the_year_with_correct_leap_days() -> None:
    for seed, rng in cases():
        cal = FiscalCalendar(year_end_month=rng.randint(1, 12))
        fy = year(rng)
        spans = [cal.span(q) for q in fy.quarters()]
        assert spans[0][0] == cal.span(fy)[0] and spans[-1][1] == cal.span(fy)[1], seed
        for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
            assert (start - end).days == 1, seed
        assert sum(cal.days(q) for q in fy.quarters()) == cal.days(fy), seed
        start, end = cal.span(fy)
        feb_year = start.year if start.month <= 2 else start.year + 1
        leap = feb_year % 4 == 0 and (feb_year % 100 != 0 or feb_year % 400 == 0)
        assert cal.days(fy) == (366 if leap else 365), seed


# --- cycles -------------------------------------------------------------------------------------


def _src(node_id: str, value: str) -> object:
    return source(node_id, value)


def _formula(node_id: str, op: Operator, operands: tuple[str, ...]) -> object:
    return formula(node_id, op, operands)


def test_random_dags_build_in_a_valid_deterministic_order() -> None:
    for seed, rng in cases(100):
        nodes = dag(rng, size=rng.randint(4, 40), source=_src, formula=_formula)  # type: ignore[arg-type]
        graph = ModelGraph.build(nodes)  # type: ignore[arg-type]
        position = {node_id: i for i, node_id in enumerate(graph.order)}
        assert len(position) == len(nodes), seed
        for edge in graph.edges:
            assert position[edge.source] < position[edge.target], seed
        shuffled = list(nodes)
        rng.shuffle(shuffled)
        assert ModelGraph.build(shuffled).order == graph.order, seed  # type: ignore[arg-type]
        assert (
            GraphSnapshot.build("m", shuffled).snapshot_id  # type: ignore[arg-type]
            == GraphSnapshot.build("m", nodes).snapshot_id  # type: ignore[arg-type]
        ), seed


def test_one_back_edge_always_makes_a_real_reported_cycle() -> None:
    for seed, rng in cases(100):
        nodes = dag(rng, size=rng.randint(6, 40), source=_src, formula=_formula)  # type: ignore[arg-type]
        formulas = [n for n in nodes if isinstance(n, FormulaNode)]
        if len(formulas) < 2:
            continue
        earlier, later = sorted(rng.sample(formulas, 2), key=nodes.index)
        # Make ``later`` depend on ``earlier`` (if it does not already), then close the loop.
        if earlier.node_id not in later.operands:
            later = dataclasses.replace(
                later, operator=Operator.ADD, operands=(*later.operands, earlier.node_id)
            )
        earlier = dataclasses.replace(
            earlier, operator=Operator.ADD, operands=(*earlier.operands, later.node_id)
        )
        by_id = {n.node_id: n for n in nodes}
        by_id[earlier.node_id] = earlier
        by_id[later.node_id] = later
        with pytest.raises(CycleError) as excinfo:
            ModelGraph.build(by_id.values())
        cycle = excinfo.value.cycle
        assert cycle[0] == cycle[-1] and len(cycle) >= 3, seed
        for node_id, dependency in zip(cycle, cycle[1:], strict=False):
            assert dependency in {ref for _, ref in by_id[node_id].inputs()}, seed


# --- scenario immutability ----------------------------------------------------------------------


def _random_model(rng) -> list:  # type: ignore[no-untyped-def,type-arg]
    nodes: list = [  # type: ignore[type-arg]
        source("price", str(nonzero_decimal(rng, digits=5, places=2))),
        source("units-fact", str(rng.randint(1, 5000)), unit=COUNT),
        driver("units", "units-fact"),
        formula("revenue", Operator.MUL, ("price", "units")),
    ]
    for i in range(rng.randint(1, 4)):
        nodes.append(assumption(f"g{i}", str(decimal(rng, digits=3, places=3))))
        nodes.append(assumption(f"one{i}", "1"))
        nodes.append(formula(f"factor{i}", Operator.ADD, (f"one{i}", f"g{i}"), unit=RATIO))
        parent = "revenue" if i == 0 else f"rev{i - 1}"
        nodes.append(formula(f"rev{i}", Operator.MUL, (parent, f"factor{i}")))
    nodes.append(output("out", "revenue"))
    return nodes


def test_applying_a_scenario_never_mutates_the_base_and_only_re_keys_dependents() -> None:
    for seed, rng in cases(100):
        base = GraphSnapshot.build("m", _random_model(rng))
        before_json = base.canonical_json()
        before_run = evaluate(base, cutoff=CUTOFF)
        overridable = [
            n.node_id
            for n in base.nodes
            if n.kind.value in ("analyst_assumption", "operational_driver")
        ]
        targets = rng.sample(overridable, rng.randint(1, len(overridable)))
        scenario = Scenario.of(
            f"s{seed}", "case", {t: decimal(rng, digits=4, places=2) for t in targets}, as_of=AS_OF
        )
        child = apply_scenario(base, scenario)
        assert base.canonical_json() == before_json, seed
        after_run = evaluate(base, cutoff=CUTOFF)
        assert after_run == before_run, seed
        child_run = evaluate(child, cutoff=CUTOFF)
        affected: set[str] = set()
        stack = list(targets)
        while stack:
            node_id = stack.pop()
            for dep in base.graph.dependents(node_id):
                if dep not in affected:
                    affected.add(dep)
                    stack.append(dep)
        for node_id in base.graph.order:
            same = child_run.result(node_id).result_id == before_run.result(node_id).result_id
            assert same is (node_id not in affected), (seed, node_id)
        assert child.parent_snapshot_id == base.snapshot_id, seed
        assert child.scenario_id == scenario.scenario_id, seed
