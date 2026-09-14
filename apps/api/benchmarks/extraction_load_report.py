"""Pure acceptance statistics, retaining failures and checking offered overlap."""

from __future__ import annotations

import math
from typing import Any

OPERATIONS = {"create": 500, "review": 1000, "waiting_reconnect": 2000, "terminal_reconnect": 2000}


def overlap(rows: list[dict[str, Any]]) -> int:
    events = [(row[key], delta) for row in rows for key, delta in (("start_ns", 1), ("end_ns", -1))]
    active = maximum = 0
    for _, delta in sorted(events):
        active += delta
        maximum = max(maximum, active)
    return maximum


def report(rows: list[dict[str, Any]], waves: int = 4) -> dict[str, Any]:
    """Require all 25 users in every wave and strict nearest-rank latency gates."""
    operations = {}
    passed = waves >= 4
    for operation, threshold in OPERATIONS.items():
        measured = [r for r in rows if r["operation"] == operation and r["phase"] == "measured"]
        expected = {(wave, user) for wave in range(waves) for user in range(25)}
        identities = {(r["wave"], r["user"]) for r in measured}
        distinct_actors = all(
            len({r.get("actor_id") for r in measured if r["wave"] == wave}) == 25
            for wave in range(waves)
        )
        complete = len(measured) == len(expected) and identities == expected and distinct_actors
        durations = sorted(r["end_ns"] - r["start_ns"] for r in measured)
        p95 = durations[math.ceil(0.95 * len(durations)) - 1] / 1e6 if durations else None
        minimum = min(
            (overlap([r for r in measured if r["wave"] == w]) for w in range(waves)), default=0
        )
        failures = sum(
            bool(r.get("error"))
            or not r.get("verified")
            or r["status"] != (202 if operation == "create" else 200)
            or r["end_ns"] <= r["start_ns"]
            for r in measured
        )
        ok = complete and failures == 0 and minimum == 25 and p95 is not None and p95 < threshold
        operations[operation] = dict(
            samples=len(measured),
            complete=complete,
            failures=failures,
            p95_ms=p95,
            threshold_ms=threshold,
            min_wave_overlap=minimum,
            passed=ok,
        )
        passed = passed and ok
    setup_ok = all(not r.get("error") and r.get("verified") for r in rows)
    return dict(
        profile="scaled-local-25-users",
        full_reference_profile_verified=False,
        passed=passed and setup_ok,
        setup_and_warmup_passed=setup_ok,
        operations=operations,
    )
