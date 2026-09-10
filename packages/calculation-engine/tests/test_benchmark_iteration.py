"""Separate bounded iterative proxy; the existing 5,000-node DAG gate is unchanged."""

import gc
import os
from decimal import Decimal
from time import perf_counter

import pytest
from _fixtures import CUTOFF, Q1, assumption

from fel_calculation_engine import (
    RATIO,
    ExpressionFormulaNode,
    GraphSnapshot,
    IterationGroup,
    evaluate,
)


def bounded_iterative_model():
    members = tuple(f"n{i:03d}" for i in range(100))
    nodes = [assumption("seed", "10")]
    nodes.extend(
        ExpressionFormulaNode.from_expression(
            node_id=member,
            label=member,
            unit=RATIO,
            period=Q1,
            expression=f"[{members[(index + 1) % len(members)]}]/2",
            formula_version="v1",
        )
        for index, member in enumerate(members)
    )
    group = IterationGroup.of(
        group_id="ring",
        members=members,
        seeds={member: "seed" for member in members},
        absolute_tolerances={member: Decimal("0.000001") for member in members},
        relative_tolerance=Decimal("0"),
        max_iterations=100,
    )
    return GraphSnapshot.build("iteration-benchmark", nodes, iteration_groups=(group,))


def test_bounded_iteration_fixture_is_deterministic():
    snapshot = bounded_iterative_model()
    first = evaluate(snapshot, cutoff=CUTOFF)
    assert first == evaluate(snapshot, cutoff=CUTOFF)
    assert len(first.results) == 101
    assert next(iter(first.iteration_runs.values())).iterations == 24


@pytest.mark.skipif(
    os.environ.get("FEL_RUN_BENCHMARKS") != "1", reason="timing assertion is opt-in"
)
def test_100_member_24_sweep_iteration_proxy_is_under_500_ms():
    snapshot = bounded_iterative_model()
    evaluate(snapshot, cutoff=CUTOFF)
    samples = []
    for _ in range(11):
        gc.collect()
        started = perf_counter()
        result = evaluate(snapshot, cutoff=CUTOFF)
        samples.append((perf_counter() - started) * 1000)
        assert next(iter(result.iteration_runs.values())).iterations == 24
    assert max(samples) < 500, f"bounded iteration proxy samples in ms: {samples}"
