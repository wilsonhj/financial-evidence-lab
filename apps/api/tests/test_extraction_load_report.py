"""The acceptance report must reject incomplete, serial, or failing measurements."""

import copy

import pytest

from benchmarks.extraction_load_report import OPERATIONS, report


def samples():
    return [
        dict(
            operation=operation,
            phase="measured",
            wave=wave,
            user=user,
            actor_id=f"actor-{wave}-{user}",
            start_ns=wave * 10**10,
            end_ns=wave * 10**10 + 100_000_000,
            status=202 if operation == "create" else 200,
            verified=True,
            error=None,
        )
        for operation in OPERATIONS
        for wave in range(4)
        for user in range(25)
    ]


def test_complete_concurrent_observations_pass():
    result = report(samples())
    assert result["passed"]
    assert result["operations"]["review"]["p95_ms"] == 100
    assert result["operations"]["review"]["min_wave_overlap"] == 25


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "error", "status", "unverified", "serial", "slow", "same_actor"],
)
def test_report_rejects_invalid_evidence(change):
    rows = samples()
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = copy.deepcopy(rows[-2])
    elif change == "error":
        rows[0]["error"] = "timeout"
    elif change == "status":
        rows[0]["status"] = 429
    elif change == "unverified":
        rows[0]["verified"] = False
    elif change == "serial":
        for row in rows:
            row["start_ns"] += row["user"] * 200_000_000
            row["end_ns"] += row["user"] * 200_000_000
    elif change == "same_actor":
        for row in rows:
            row["actor_id"] = "one-actor"
    elif change == "slow":
        for row in rows:
            row["end_ns"] = row["start_ns"] + 2_000_000_000
    assert not report(rows)["passed"]


def test_nearest_rank_and_strict_threshold_without_warmup_contamination():
    rows = samples()
    create = [row for row in rows if row["operation"] == "create"]
    for index, row in enumerate(create):
        row["end_ns"] = row["start_ns"] + (index + 1) * 1_000_000
    rows.append(dict(create[0], phase="warmup", end_ns=999_000_000_000))
    assert report(rows)["operations"]["create"]["p95_ms"] == 95
    for row in create:
        row["end_ns"] = row["start_ns"] + 500_000_000
    assert not report(rows)["passed"]


def test_bulk_mock_produces_100_distinct_source_supported_dates():
    from uuid import uuid4

    from benchmarks.extraction_load_fixture import DATES, SOURCE_TEXT, BulkMock
    from fel_providers.interfaces import StructuredGenerationRequest

    ids = {key: str(uuid4()) for key in ("span", "version", "entity")}
    result = BulkMock(ids).generate_structured(
        StructuredGenerationRequest(
            schema_name="kpi",
            schema_version="load/v1",
            json_schema={},
            messages=[],
            max_output_tokens=4096,
        )
    )
    proposals = result.parsed["proposals"]
    assert len(proposals) == 100
    assert {p["period"]["instant"] for p in proposals} == set(DATES)
    for proposal in proposals:
        assert proposal["period"]["instant"] in SOURCE_TEXT
        assert proposal["evidence"][0]["source_span_id"] == ids["span"]
        assert proposal["evidence"][0]["document_version_id"] == ids["version"]


@pytest.mark.parametrize("kind", ["correct", "comment_only", "wrong_payload", "wrong_id", "error"])
def test_reconnect_requires_complete_exact_durable_frame(monkeypatch, kind):
    import json
    import threading
    from uuid import uuid4

    import httpx

    from benchmarks.extraction_load import measure

    ids = {key: str(uuid4()) for key in ("org", "user", "run")}
    event = dict(id=2, type="review_waiting", run_id=ids["run"], payload={"count": 100})
    ids["resume"] = (1, dict(id=2, event_type="review_waiting", projected=event))
    transmitted = dict(event, payload={"count": 99}) if kind == "wrong_payload" else event
    frame = ": connected\n\n"
    if kind != "comment_only":
        frame += (
            f"id: {3 if kind == 'wrong_id' else 2}\nevent: review_waiting\n"
            f"data: {json.dumps(transmitted)}\n\n"
        )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429 if kind == "error" else 200, text=frame)
        ),
        base_url="http://localhost",
    )
    monkeypatch.setattr("benchmarks.extraction_load.httpx.Client", lambda **kwargs: client)
    result = measure("waiting_reconnect", ids, "http://localhost", threading.Barrier(1))
    assert result["verified"] == (kind == "correct")
    assert bool(result["error"]) == (kind != "correct")
