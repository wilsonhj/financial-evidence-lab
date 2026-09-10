"""Explicit exact-SCC Jacobi execution, provenance and failure semantics (ADR-0018)."""

from dataclasses import replace
from decimal import ROUND_UP, Decimal, localcontext

import pytest
from _fixtures import AS_OF, CUTOFF, Q1, Q2, USD, assumption, formula, source

import fel_calculation_engine as calc
from fel_calculation_engine import RATIO, GraphSnapshot, evaluate


def expression(node_id, text, *, unit=RATIO):
    return calc.ExpressionFormulaNode.from_expression(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=Q1,
        expression=text,
        formula_version="v1",
    )


def policy(
    members=("x",), *, seeds=None, tolerances=None, relative="0", cap=1000, group_id="fixed"
):
    assert hasattr(calc, "IterationGroup"), "explicit iteration policy is missing"
    return calc.IterationGroup.of(
        group_id=group_id,
        members=members,
        seeds=seeds if seeds is not None else {member: "seed" for member in members},
        absolute_tolerances=(
            tolerances
            if tolerances is not None
            else {member: Decimal("0.0001") for member in members}
        ),
        relative_tolerance=Decimal(relative),
        max_iterations=cap,
    )


def self_model(text="([x] + [base]) / 2", *, group=None, seed="0"):
    return GraphSnapshot.build(
        "m",
        [
            assumption("seed", seed),
            assumption("base", "10"),
            expression("x", text),
            expression("down", "[x]*2"),
        ],
        iteration_groups=(group or policy(),),
    )


def test_explicit_self_cycle_converges_and_provenance_resolves():
    group = policy()
    snap = self_model(group=group)
    run = evaluate(snap, cutoff=CUTOFF)
    record = next(iter(run.iteration_runs.values()))
    assert record.iterations == 17
    assert run.quantity("x").value == Decimal("9.9999237060546875")
    assert run.quantity("down").value == Decimal("19.9998474121093750")
    assert record.run_id == run.result("x").iteration_run_id
    assert set(run.iteration_runs) == {record.run_id}
    assert record.verify()
    assert dict(record.dependencies)["x"] == ("x", "base")
    assert {r.node_id for r in run.trace("down")} == {"down", "x", "seed", "base"}
    assert set(run.result("x").input_result_ids) == {
        run.result("seed").result_id,
        run.result("base").result_id,
    }
    assert run.result("x").lineage.derived_from == run.result("x").input_result_ids
    assert snap.verify() and snap.payload()["schema"] == "fel-calc-snapshot/v2"


def test_two_member_sweeps_are_jacobi_and_require_every_member():
    group = policy(
        ("b", "a"),
        seeds={"a": "zero", "b": "one"},
        tolerances={"a": Decimal("1"), "b": Decimal("0.01")},
        cap=20,
    )
    # Jacobi alternates (1, 0), (0, .5), (.5, 0), ...; b first qualifies at sweep 14.
    snap = GraphSnapshot.build(
        "two",
        [
            assumption("zero", "0"),
            assumption("one", "1"),
            expression("a", "[b]"),
            expression("b", "[a]/2"),
        ],
        iteration_groups=(group,),
    )
    run = evaluate(snap, cutoff=CUTOFF)
    record = next(iter(run.iteration_runs.values()))
    assert record.iterations == 14
    assert run.quantity("a").value == 0
    assert run.quantity("b").value == Decimal("0.0078125")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"members": ()},
        {"members": ("x", "x")},
        {"seeds": {}},
        {"seeds": {"x": "seed", "y": "seed"}},
        {"tolerances": {}},
        {"tolerances": {"x": Decimal("-1")}},
        {"tolerances": {"x": Decimal("NaN")}},
        {"tolerances": {"x": Decimal("0")}},
        {"relative": "-1"},
        {"relative": "Infinity"},
        {"cap": 0},
        {"cap": 1001},
        {"cap": True},
        {"cap": Decimal("3")},
    ],
)
def test_invalid_policies_fail_closed(kwargs):
    assert hasattr(calc, "IterationGroup"), "explicit iteration policy is missing"
    with pytest.raises(calc.IterationPolicyError):
        policy(**kwargs)


def test_policy_copies_inputs_and_snapshot_preserves_or_replaces_it():
    seeds = {"x": "seed"}
    tolerances = {"x": Decimal("0.0001")}
    group = policy(seeds=seeds, tolerances=tolerances)
    seeds["x"] = "other"
    tolerances["x"] = Decimal("100")
    assert dict(group.seeds) == {"x": "seed"}
    assert dict(group.absolute_tolerances) == {"x": Decimal("0.0001")}
    snap = self_model(group=group)
    assert snap.derive(snap.nodes).iteration_groups == (group,)
    assert snap.with_nodes([]).iteration_groups == (group,)
    replacement = policy(cap=999)
    assert snap.with_nodes([], iteration_groups=(replacement,)).iteration_groups == (replacement,)
    with pytest.raises(calc.CycleError):
        snap.derive(snap.nodes, iteration_groups=())


def test_graph_rejects_undeclared_partial_superset_overlap_and_acyclic_groups():
    group = policy(("a", "b"))
    nodes = [assumption("seed", "0"), expression("a", "[b]/2"), expression("b", "[a]/2")]
    with pytest.raises(calc.CycleError):
        GraphSnapshot.build("m", nodes)
    for groups in [
        (policy(("a",)),),
        (policy(("a", "b", "seed")),),
        (group, group),
        (group, policy(("b",), group_id="other")),
        (policy(("missing",)),),
        (policy(("seed",)),),
    ]:
        with pytest.raises(calc.IterationPolicyError):
            GraphSnapshot.build("m", nodes, iteration_groups=groups)
    with pytest.raises(calc.IterationPolicyError):
        GraphSnapshot.build(
            "m",
            [assumption("seed", "0"), expression("a", "[seed]*2")],
            iteration_groups=(policy(("a",)),),
        )


def test_seed_prerequisites_cannot_depend_on_their_group_or_another_seed_cycle():
    group = policy(seeds={"x": "later"})
    nodes = [expression("x", "[x]/2"), expression("later", "[x]*2")]
    with pytest.raises(calc.IterationPolicyError):
        GraphSnapshot.build("m", nodes, iteration_groups=(group,))
    with pytest.raises(calc.IterationPolicyError):
        GraphSnapshot.build(
            "m", [expression("x", "[x]/2")], iteration_groups=(policy(seeds={"x": "x"}),)
        )
    with pytest.raises(calc.IterationPolicyError):
        GraphSnapshot.build(
            "m",
            [expression("x", "[x]/2"), expression("y", "[y]/2")],
            iteration_groups=(
                policy(seeds={"x": "y"}),
                policy(("y",), seeds={"y": "x"}, group_id="other"),
            ),
        )


@pytest.mark.parametrize(
    "seed,error",
    [
        (source("seed", "0"), calc.UnitError),
        (assumption("seed", "0", period=Q2), calc.PeriodError),
    ],
)
def test_seed_unit_and_exact_period_are_checked(seed, error):
    group = policy()
    with pytest.raises(error):
        GraphSnapshot.build("m", [seed, expression("x", "[x]/2")], iteration_groups=(group,))


def test_seed_missing_and_after_cutoff_are_rejected_even_if_numerically_erased():
    group = policy()
    with pytest.raises(calc.MissingInputError):
        GraphSnapshot.build("m", [expression("x", "[x]*0")], iteration_groups=(group,))
    snap = GraphSnapshot.build(
        "m",
        [assumption("seed", "1", as_of=CUTOFF.replace(year=2025)), expression("x", "[x]*0")],
        iteration_groups=(group,),
    )
    with pytest.raises(calc.CutoffViolationError):
        evaluate(snap, cutoff=CUTOFF)


@pytest.mark.parametrize("text,seed", [("-[x]", "1"), ("[x]*2", "1"), ("[x]+1", "0")])
def test_nonconvergence_is_typed_and_never_evaluates_downstream(text, seed):
    group = policy(cap=3)
    snap = self_model(text, group=group, seed=seed).with_nodes([expression("down", "[x]/0")])
    sink = calc.RecordingSink()
    with pytest.raises(calc.IterationConvergenceError) as exc:
        evaluate(snap, cutoff=CUTOFF, sink=sink)
    assert exc.value.details["group_id"] == "fixed"
    assert exc.value.details["iterations"] == 3
    assert tuple(exc.value.details["residuals"]) == ("x",)
    assert "calc.iteration.failed" in [event["event"] for event in sink.events]
    assert "calc.evaluate.completed" not in [event["event"] for event in sink.events]


def test_later_sweep_arithmetic_error_aborts_immediately():
    group = policy(cap=10)
    # seed 1 => 2 => division by zero on sweep 2.
    with pytest.raises(calc.FormulaError):
        evaluate(self_model("2/(2-[x])", group=group, seed="1"), cutoff=CUTOFF)


def test_exact_tolerance_boundary_and_ambient_decimal_context():
    group = policy(tolerances={"x": Decimal("0.5")}, cap=1)
    snap = self_model("[x]/2", group=group, seed="1")
    assert evaluate(snap, cutoff=CUTOFF).quantity("x").value == Decimal("0.5")
    tiny = policy(tolerances={"x": Decimal("0.4999999999999999999999999999999999")}, cap=1)
    with pytest.raises(calc.IterationConvergenceError):
        evaluate(self_model("[x]/2", group=tiny, seed="1"), cutoff=CUTOFF)
    snap = self_model(seed="1.234567890123456789012345678901234")
    expected = evaluate(snap, cutoff=CUTOFF)
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_UP
        assert evaluate(snap, cutoff=CUTOFF) == expected


def test_relative_tolerance_and_mixed_units():
    group = policy(
        ("cash", "rate"),
        seeds={"cash": "cash-seed", "rate": "rate-seed"},
        tolerances={"cash": Decimal("1"), "rate": Decimal("0")},
        relative="0.01",
    )
    snap = GraphSnapshot.build(
        "mixed",
        [
            source("cash-seed", "100"),
            assumption("rate-seed", "1"),
            source("base", "100"),
            expression("cash", "[base]*[rate]", unit=USD),
            expression("rate", "([cash]/[base]+1)/2"),
        ],
        iteration_groups=(group,),
    )
    run = evaluate(snap, cutoff=CUTOFF)
    assert next(iter(run.iteration_runs.values())).iterations == 1
    assert run.quantity("cash").unit == USD and run.quantity("rate").unit == RATIO


def test_result_identity_is_local_to_group_definition_policy_inputs_and_cutoff():
    snap = self_model()
    run = evaluate(snap, cutoff=CUTOFF)

    def ids(model, cutoff=CUTOFF):
        result = evaluate(model, cutoff=cutoff)
        return result.result("x").result_id, result.result("down").result_id

    expected = ids(snap)
    assert (
        ids(GraphSnapshot.build("m", reversed(snap.nodes), iteration_groups=snap.iteration_groups))
        == expected
    )
    assert ids(snap.with_nodes([assumption("unrelated", "99")])) == expected
    assert ids(snap.with_nodes([replace(snap.graph.node("x"), label="renamed")])) == expected
    assert ids(snap.with_nodes([expression("x", " ([x]+[base])/2.0 ")])) == expected
    for changed in [
        snap.with_nodes([assumption("seed", "1")]),
        snap.with_nodes([assumption("base", "20")]),
        snap.with_nodes([expression("x", "([x]+[base])/3")]),
        snap.with_nodes([], iteration_groups=(policy(cap=999),)),
    ]:
        assert all(a != b for a, b in zip(ids(changed), expected, strict=True))
        assert evaluate(changed, cutoff=CUTOFF).result("base").result_id == run.result(
            "base"
        ).result_id or changed.graph.node("base") != snap.graph.node("base")
    assert ids(snap, CUTOFF.replace(day=29)) != expected


def test_scenario_rewrites_ast_and_seed_references_and_restore_retains_policy():
    snap = self_model()
    scenario = calc.Scenario.of(
        "bull", "Bull", {"base": Decimal("20"), "seed": Decimal("1")}, as_of=AS_OF
    )
    child = calc.apply_scenario(snap, scenario)
    assert dict(child.iteration_groups[0].seeds) == {"x": "seed--bull"}
    assert calc.formula_dependencies(child.graph.node("x").ast) == ("x", "base--bull")
    assert (
        child.iteration_groups[0].absolute_tolerances
        == snap.iteration_groups[0].absolute_tolerances
    )
    run = evaluate(child, cutoff=CUTOFF)
    assert run.quantity("x").value > 19
    assert {r.node_id for r in run.trace("x")} == {"x", "seed", "base", "seed--bull", "base--bull"}
    store = calc.InMemorySnapshotStore()
    store.put(snap)
    store.put(child)
    restored = child.derive(
        store.get(snap.snapshot_id).nodes,
        iteration_groups=store.get(snap.snapshot_id).iteration_groups,
    )
    assert (
        evaluate(restored, cutoff=CUTOFF).result("x").result_id
        == evaluate(snap, cutoff=CUTOFF).result("x").result_id
    )


def test_legacy_formula_members_are_supported():
    group = policy(("a", "b"))
    snap = GraphSnapshot.build(
        "legacy-cycle",
        [
            assumption("seed", "0"),
            assumption("base", "10"),
            assumption("half", "0.5"),
            formula("a", calc.Operator.ADD, ("b", "base"), unit=RATIO),
            formula("b", calc.Operator.MUL, ("a", "half"), unit=RATIO),
        ],
        iteration_groups=(group,),
    )
    assert evaluate(snap, cutoff=CUTOFF).quantity("a").value > Decimal("19.999")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"members": ("x", 3)},
        {"members": None},
        {"seeds": None},
        {"seeds": {3: "seed"}},
        {"absolute_tolerances": []},
    ],
)
def test_policy_factory_invalid_shapes_raise_typed_errors(kwargs):
    arguments = dict(
        group_id="fixed",
        members=("x",),
        seeds={"x": "seed"},
        absolute_tolerances={"x": Decimal("0.01")},
        relative_tolerance=Decimal("0"),
        max_iterations=10,
    )
    arguments.update(kwargs)
    with pytest.raises(calc.IterationPolicyError):
        calc.IterationGroup.of(**arguments)


def test_failure_after_convergence_still_emits_iteration_failure():
    # The vector is finite in Decimal128 but exceeds the canonical exponent limit.
    snap = GraphSnapshot.build(
        "large",
        [assumption("seed", "1e250000"), expression("x", "[x]*1e250000")],
        iteration_groups=(policy(tolerances={"x": Decimal("1e250000")}, relative="1", cap=1),),
    )
    sink = calc.RecordingSink()
    with pytest.raises(calc.CalculationEngineError):
        evaluate(snap, cutoff=CUTOFF, sink=sink)
    assert [event["event"] for event in sink.events][-2:] == [
        "calc.iteration.failed",
        "calc.evaluate.failed",
    ]


def test_graph_dependency_inspection_includes_seed_execution_prerequisites():
    snap = self_model()
    assert snap.graph.dependencies("x") == ("x", "base", "seed")
    assert "x" in snap.graph.dependents("seed")
    assert ("seed", "x", "iteration_seed") in [
        (e.source, e.target, e.role) for e in snap.graph.edges
    ]


def test_two_groups_execute_in_seed_dependency_order_and_keep_local_identities():
    # Group z's seed depends on group a, despite its node ID sorting first.
    a = policy(("a",), seeds={"a": "seed"}, group_id="a-group")
    z = policy(("0-z",), seeds={"0-z": "a"}, group_id="z-group")
    nodes = [assumption("seed", "10"), expression("a", "[a]/2"), expression("0-z", "[0-z]/2")]
    snap = GraphSnapshot.build("m", nodes, iteration_groups=(z, a))
    run = evaluate(snap, cutoff=CUTOFF)
    assert run.order == ("seed", "a", "0-z")
    assert {r.node_id for r in run.trace("0-z")} == {"0-z", "a", "seed"}
    assert len(run.iteration_runs) == 2
    assert (
        evaluate(GraphSnapshot.build("m", reversed(nodes), iteration_groups=(a, z)), cutoff=CUTOFF)
        == run
    )
    updated = snap.with_nodes([expression("0-z", "[0-z]/3")])
    assert evaluate(updated, cutoff=CUTOFF).result("a").result_id == run.result("a").result_id


def test_a_seed_also_used_in_the_equation_has_one_lineage_parent():
    snap = GraphSnapshot.build(
        "m", [assumption("seed", "1"), expression("x", "[x]*[seed]")], iteration_groups=(policy(),)
    )
    run = evaluate(snap, cutoff=CUTOFF)
    assert run.result("x").input_result_ids == (run.result("seed").result_id,)
    assert run.result("x").available_at == AS_OF


def test_success_and_arithmetic_failure_events_include_algorithm_and_completed_sweeps():
    sink = calc.RecordingSink()
    evaluate(self_model(), cutoff=CUTOFF, sink=sink)
    events = [event for event in sink.events if event["event"].startswith("calc.iteration.")]
    assert [event["event"] for event in events] == [
        "calc.iteration.started",
        "calc.iteration.completed",
    ]
    assert all(
        event["algorithm"] == "jacobi/v1" and event["max_iterations"] == 1000 for event in events
    )
    assert events[-1]["iterations"] == 17
    sink = calc.RecordingSink()
    with pytest.raises(calc.FormulaError):
        evaluate(self_model("2/(2-[x])", seed="1"), cutoff=CUTOFF, sink=sink)
    failed = next(event for event in sink.events if event["event"] == "calc.iteration.failed")
    assert failed["iterations"] == 1 and failed["error_code"] == "FORMULA_ERROR"
    assert "values" not in failed and "residuals" not in failed


def test_non_arithmetic_nodes_cannot_be_group_members():
    group = policy(("x", "reported"), seeds={"x": "seed", "reported": "seed"})
    nodes = [
        source("seed", "0"),
        expression("x", "[reported]/2", unit=USD),
        calc.ReportedFinancialOutputNode(
            node_id="reported",
            label="reported",
            unit=USD,
            period=Q1,
            source="x",
            metric_id="metric",
        ),
    ]
    with pytest.raises(calc.IterationPolicyError):
        GraphSnapshot.build("m", nodes, iteration_groups=(group,))


def test_5000_member_scc_does_not_recurse():
    members = tuple(f"n{i:04d}" for i in range(5000))
    nodes = [assumption("seed", "1")]
    nodes.extend(
        expression(member, f"[{members[(index+1) % len(members)]}]")
        for index, member in enumerate(members)
    )
    group = policy(members, cap=1)
    snap = GraphSnapshot.build("large-cycle", nodes, iteration_groups=(group,))
    run = evaluate(snap, cutoff=CUTOFF)
    assert len(run.results) == 5001
    assert next(iter(run.iteration_runs.values())).iterations == 1
    assert all(run.quantity(member).value == 1 for member in members)
    assert len(run.trace(members[0])) == 2
