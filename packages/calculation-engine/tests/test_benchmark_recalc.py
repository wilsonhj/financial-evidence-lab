"""5,000-node recalculation p95 under the spec budget (T0410, spec.md:872 "< 500 ms").

Deterministic and CI-safe: the synthetic model is generated from a fixed seed,
covers all nine node kinds, and the p95 is taken over repeated full
recalculations of the same snapshot. The budget is the spec's, not a machine
calibrated one; the measured value is printed and carried into the PR evidence.
"""

from __future__ import annotations

import gc
import statistics
from time import perf_counter

from _fixtures import CUTOFF

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.nodes import NodeKind
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.synthetic import build_synthetic_model
from fel_calculation_engine.telemetry import RecordingSink

NODE_COUNT = 5_000
BUDGET_MS = 500
RUNS = 11


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(0.95 * len(ordered) + 0.5) - 1))
    return ordered[index]


def test_synthetic_model_has_exactly_5000_nodes_of_all_nine_kinds() -> None:
    nodes = build_synthetic_model(NODE_COUNT, seed=63)
    assert len(nodes) == NODE_COUNT
    assert {n.kind for n in nodes} == set(NodeKind)
    again = build_synthetic_model(NODE_COUNT, seed=63)
    assert (
        GraphSnapshot.build("bench", nodes).snapshot_id
        == GraphSnapshot.build("bench", again).snapshot_id
    )


def test_5000_node_recalculation_p95_is_under_500ms() -> None:
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
    p95 = _p95(samples)
    median = statistics.median(samples)
    print(f"\n5,000-node recalculation: p95={p95:.1f} ms median={median:.1f} ms over {RUNS} runs")
    assert (
        p95 < BUDGET_MS
    ), f"p95 {p95:.1f} ms exceeds the {BUDGET_MS} ms budget (samples={samples})"
    completed = [e for e in sink.events if e["event"] == "calc.evaluate.completed"]
    assert len(completed) == RUNS + 1 and all(e["node_count"] == NODE_COUNT for e in completed)
