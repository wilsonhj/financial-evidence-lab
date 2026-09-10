"""Generated parser and fixed-point invariants; no float oracle."""

from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction

import pytest
from _fixtures import CUTOFF, Q1, assumption
from _gen import cases

from fel_calculation_engine import (
    RATIO,
    Binary,
    ExpressionFormulaNode,
    GraphSnapshot,
    IterationGroup,
    Literal,
    Quantity,
    Reference,
    evaluate,
    evaluate_formula,
    formula_dependencies,
    parse_formula,
)


def expression(node_id, text):
    return ExpressionFormulaNode.from_expression(
        node_id=node_id,
        label=node_id,
        unit=RATIO,
        period=Q1,
        expression=text,
        formula_version="v1",
    )


def test_parser_matches_exact_integer_arithmetic():
    for seed, rng in cases(base_seed=219):
        x, a, b = rng.randint(-100000, 100000), rng.randint(-1000, 1000), rng.randint(-100, 100)
        ast = parse_formula(f"([x] + {a}) * {b} - [x]")
        assert evaluate_formula(ast, {"x": Quantity(Decimal(x), RATIO)}).value == Decimal(
            (x + a) * b - x
        ), seed
        assert formula_dependencies(ast) == ("x",), seed


def test_contraction_converges_deterministically_under_order_and_context_changes():
    for case_seed, rng in cases(50, base_seed=219):
        base, seed = rng.randint(1, 100), rng.randint(-100, 100)
        nodes = [
            assumption("base", str(base)),
            assumption("seed", str(seed)),
            expression("x", "([x]+[base])/2"),
        ]
        policy = IterationGroup.of(
            group_id="fixed",
            members=("x",),
            seeds={"x": "seed"},
            absolute_tolerances={"x": Decimal("0.000001")},
            relative_tolerance=Decimal("0"),
            max_iterations=100,
        )
        snap = GraphSnapshot.build("m", nodes, iteration_groups=(policy,))
        expected = evaluate(snap, cutoff=CUTOFF)
        rng.shuffle(nodes)
        changed = GraphSnapshot.build("m", nodes, iteration_groups=(policy,))
        with localcontext() as ambient:
            ambient.prec = 2
            ambient.rounding = ROUND_DOWN
            actual = evaluate(changed, cutoff=CUTOFF)
        assert actual == expected, case_seed
        record = next(iter(actual.iteration_runs.values()))
        # A rational oracle is independent of the engine's Decimal implementation.
        expected_value = base + Fraction(seed - base, 2**record.iterations)
        assert Fraction(actual.quantity("x").value) == expected_value, case_seed
        assert abs(expected_value - base) <= Fraction(1, 1000000), case_seed
        assert record.verify(), case_seed


@pytest.mark.parametrize("last,expected", [("1", "2"), ("3", "4")])
def test_34_digit_multiplication_ties_round_half_even(last, expected):
    value = Decimal("1." + "0" * 32 + last)
    ast = Binary("*", Reference("x"), Literal(Decimal("1.5")))
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        result = evaluate_formula(ast, {"x": Quantity(value, RATIO)})
    assert result.value == Decimal("1.5" + "0" * 31 + expected)


def test_iteration_records_and_policy_are_immutable_and_tampering_is_detected():
    policy = IterationGroup.of(
        group_id="fixed",
        members=("x",),
        seeds={"x": "seed"},
        absolute_tolerances={"x": Decimal("1")},
        relative_tolerance=Decimal("0"),
        max_iterations=1,
    )
    snap = GraphSnapshot.build(
        "m", [assumption("seed", "1"), expression("x", "[x]/2")], iteration_groups=(policy,)
    )
    run = evaluate(snap, cutoff=CUTOFF)
    record = next(iter(run.iteration_runs.values()))
    with pytest.raises(TypeError):
        run.iteration_runs["other"] = record
    with pytest.raises(FrozenInstanceError):
        record.iterations = 2
    with pytest.raises(FrozenInstanceError):
        record.policy.max_iterations = 2
    assert not replace(record, iterations=2).verify()
    assert not replace(record, policy=replace(policy, max_iterations=2)).verify()
