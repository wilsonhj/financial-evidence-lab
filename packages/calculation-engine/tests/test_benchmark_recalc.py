"""5,000-node recalculation against the spec budget (T0410, spec.md:872 "< 500 ms").

The model is generated from a fixed seed and covers all nine node kinds, so the
*shape* of the work is deterministic. The **timing** is not, so it is opt-in:
set ``FEL_RUN_BENCHMARKS=1`` to assert the budget. Two reasons, both measured
during review of PR #212:

* A wall-clock assertion on a shared CI runner flakes. Unloaded this machine
  measures 45-59 ms; under 3x CPU oversubscription, on hardware faster than a
  GitHub runner, the same test measured **322 ms** against the 500 ms gate. The
  apparent 11x headroom is an idle-machine figure.
* ``addopts`` carries ``-q``, so a ``print`` never reaches a CI log. The first
  red run would have been undiagnosable, which is why the measurement now lives
  in the assertion message instead.

The determinism and coverage checks below stay unconditional: they are what CI
can actually hold stable. The spec's target is a p95 under 25 concurrent users
on the reference profile of section 16.1, which this single-process proxy does
not reproduce either way -- see the PR's handoff notes.
"""

from __future__ import annotations

import gc
import os
import statistics
from time import perf_counter

import pytest

from _fixtures import CUTOFF

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.nodes import NodeKind
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.synthetic import build_synthetic_model
from fel_calculation_engine.telemetry import RecordingSink

NODE_COUNT = 5_000
BUDGET_MS = 500
RUNS = 11

requires_benchmarks = pytest.mark.skipif(
    os.environ.get("FEL_RUN_BENCHMARKS") != "1",
    reason="timing assertion is opt-in; set FEL_RUN_BENCHMARKS=1",
)


def _slowest(samples: list[float]) -> float:
    """The worst sample -- which is what nearest-rank p95 degenerates to here.

    With ``RUNS = 11`` the nearest-rank index is ``round(0.95 * 11 + 0.5) - 1 =
    10``, the last element of an 11-element sorted list. The old name said p95
    and the value was the maximum; the formula does not yield an interior
    statistic until at least 21 samples. Reporting the maximum is the stricter
    claim, so the gate is unchanged -- only its name is now honest.
    """
    return max(samples)


def test_synthetic_model_has_exactly_5000_nodes_of_all_nine_kinds() -> None:
    nodes = build_synthetic_model(NODE_COUNT, seed=63)
    assert len(nodes) == NODE_COUNT
    assert {n.kind for n in nodes} == set(NodeKind)
    again = build_synthetic_model(NODE_COUNT, seed=63)
    assert (
        GraphSnapshot.build("bench", nodes).snapshot_id
        == GraphSnapshot.build("bench", again).snapshot_id
    )


@requires_benchmarks
def test_5000_node_recalculation_is_under_the_spec_budget() -> None:
    snapshot = GraphSnapshot.build("bench", build_synthetic_model(NODE_COUNT, seed=63))
    sink = RecordingSink()
    samples: list[float] = []
    evaluate(snapshot, cutoff=CUTOFF, sink=sink)  # warm-up
    for _ in range(RUNS):
        gc.collect()
        started = perf_counter()
        run = evaluate(snapshot, cutoff=CUTOFF, sink=sink)
        samples.append((perf_counter() - started) * 1000)
        assert len(run.results) == NODE_COUNT
    slowest = _slowest(samples)
    median = statistics.median(samples)
    assert slowest < BUDGET_MS, (
        f"slowest of {RUNS} runs was {slowest:.1f} ms against the {BUDGET_MS} ms budget "
        f"(median {median:.1f} ms, samples {[f'{s:.1f}' for s in samples]}). "
        "A loaded machine can produce this without the engine having regressed."
    )
    completed = [e for e in sink.events if e["event"] == "calc.evaluate.completed"]
    assert len(completed) == RUNS + 1 and all(e["node_count"] == NODE_COUNT for e in completed)
