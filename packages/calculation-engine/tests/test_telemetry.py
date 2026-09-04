"""Structured, redacted telemetry for evaluations, scenarios and snapshot stores (T0403)."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from _fixtures import AS_OF, CUTOFF, formula, revenue_model, source

from fel_calculation_engine.engine import evaluate
from fel_calculation_engine.errors import FormulaError
from fel_calculation_engine.nodes import Operator
from fel_calculation_engine.scenario import Scenario, apply_scenario
from fel_calculation_engine.snapshot import GraphSnapshot
from fel_calculation_engine.store import InMemorySnapshotStore
from fel_calculation_engine.telemetry import RecordingSink, redact


def test_evaluate_emits_started_and_completed_events_without_values() -> None:
    sink = RecordingSink()
    snapshot = GraphSnapshot.build("m", revenue_model())
    evaluate(snapshot, cutoff=CUTOFF, sink=sink)
    events = [e["event"] for e in sink.events]
    assert events == ["calc.evaluate.started", "calc.evaluate.completed"]
    done = sink.events[-1]
    assert done["snapshot_id"] == snapshot.snapshot_id
    assert done["node_count"] == 9 and done["edge_count"] == 8
    assert done["result_count"] == 9 and done["failed_check_count"] == 0
    assert isinstance(done["duration_ms"], int) and done["duration_ms"] >= 0
    assert done["cutoff"] == CUTOFF.isoformat()
    flat = str(sink.events)
    assert "19.99" not in flat and "Revenue" not in flat and "label" not in flat


def test_evaluate_emits_failed_event_with_error_code_and_node() -> None:
    sink = RecordingSink()
    nodes = [
        source("n", "1"),
        source("d", "0"),
        formula(
            "q",
            Operator.DIV,
            ("n", "d"),
            unit=formula("x", Operator.ADD, ("a", "b")).unit.div(source("z", "1").unit),
        ),
    ]
    with pytest.raises(FormulaError):
        evaluate(GraphSnapshot.build("m", nodes), cutoff=CUTOFF, sink=sink)
    failed = sink.events[-1]
    assert failed["event"] == "calc.evaluate.failed"
    assert failed["error_code"] == "FORMULA_ERROR" and failed["node_id"] == "q"


def test_scenario_and_store_events() -> None:
    sink = RecordingSink()
    base = GraphSnapshot.build("m", revenue_model())
    bull = apply_scenario(
        base, Scenario.of("bull", "Bull", {"growth": Decimal("0.3")}, as_of=AS_OF), sink=sink
    )
    assert sink.events[-1]["event"] == "calc.scenario.applied"
    assert sink.events[-1]["override_count"] == 1 and sink.events[-1]["scenario_id"] == "bull"
    store = InMemorySnapshotStore(sink=sink)
    store.put(base)
    store.put(bull)
    store.put(bull)
    stored = [e for e in sink.events if e["event"] == "calc.snapshot.stored"]
    assert [e["version"] for e in stored] == [1, 2]
    assert "0.3" not in str(sink.events)


def test_redaction_masks_sensitive_keys_and_truncates_long_strings() -> None:
    payload = redact(
        {
            "event": "x",
            "label": "Revenue",
            "value": "1",
            "values": [1],
            "api_key": "k",
            "nested": {"prompt": "p", "ok": "y" * 300},
            "items": [{"text": "t"}, "plain"],
        }
    )
    assert payload["label"] == "[redacted]" and payload["value"] == "[redacted]"
    assert payload["values"] == "[redacted]" and payload["api_key"] == "[redacted]"
    assert payload["nested"]["prompt"] == "[redacted]"
    assert payload["nested"]["ok"].endswith("...[truncated]") and len(payload["nested"]["ok"]) < 300
    assert payload["items"] == [{"text": "[redacted]"}, "plain"]


def test_default_sink_logs_structured_lines(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="fel_calculation_engine.telemetry"):
        evaluate(GraphSnapshot.build("m", revenue_model()), cutoff=CUTOFF)
    messages = [r.getMessage() for r in caplog.records]
    assert any("calc_telemetry" in m and "calc.evaluate.completed" in m for m in messages)
