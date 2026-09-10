"""The worker module entrypoint: heartbeat mode terminates cleanly, the
``run`` job-consumer mode (finding 4) wires the queue loop, live-mode
provider binding fails closed without durable storage (re-review finding 2),
the structured-model binding fails closed without an explicit opt-in, and
extraction output stays durable unless an operator says otherwise (#169)."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import socket
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from fel_providers.mocks import MockSecClient, MockStorageProvider, MockStructuredLLMProvider
from fel_workers.__main__ import (
    EXTRACTION_QUEUE,
    build_run_providers,
    build_structured_llm,
    main,
    parse_run_args,
    resolve_extraction_memory_stores,
    run_main,
)
from fel_workers.ingestion.sec_client import LiveSecClient
from fel_workers.storage import LocalDirStorageProvider


def test_heartbeat_loop_bounded() -> None:
    assert main(max_beats=2, interval_seconds=0.0) == 0


def test_parse_run_args_defaults_and_overrides() -> None:
    defaults = parse_run_args([])
    assert defaults.max_iterations is None
    assert defaults.queue == "ingestion"
    custom = parse_run_args(["--max-iterations", "3", "--queue", "other"])
    assert custom.max_iterations == 3
    assert custom.queue == "other"


def test_run_mode_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_DATABASE_URL", raising=False)
    assert run_main(["--max-iterations", "1"]) == 2


def test_mock_mode_binds_mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    sec, storage = build_run_providers()
    assert isinstance(sec, MockSecClient)
    assert isinstance(storage, MockStorageProvider)


def test_live_mode_without_storage_dir_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEL_SEC_LIVE=1 with no FEL_STORAGE_DIR must refuse to start: live
    ingestion over in-memory mock storage persists storage keys whose blobs
    die with the process, making citations unresolvable."""
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        build_run_providers()
    assert "FEL_SEC_LIVE" in str(excinfo.value) and "FEL_STORAGE_DIR" in str(excinfo.value)


def test_run_main_live_without_storage_dir_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed check happens before any DB or network activity."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.delenv("FEL_STORAGE_DIR", raising=False)
    assert run_main(["--max-iterations", "1"]) == 2


def test_live_mode_binds_local_dir_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Env-driven wiring only — LiveSecClient construction performs no
    network I/O, and no request is ever issued in this test."""
    monkeypatch.setenv("FEL_SEC_LIVE", "1")
    monkeypatch.setenv("FEL_STORAGE_DIR", str(tmp_path / "blobs"))
    sec, storage = build_run_providers()
    assert isinstance(sec, LiveSecClient)
    assert isinstance(storage, LocalDirStorageProvider)
    storage.put("raw/sha256/abc", b"blob")
    assert storage.get("raw/sha256/abc") == b"blob"
    assert (tmp_path / "blobs" / "raw" / "sha256" / "abc").read_bytes() == b"blob"


class _StubConnection:
    """Stands in for the worker's psycopg connection in wiring-only tests.

    Statements are appended to ``captured['statements']`` so a test can assert
    what run_main ran on the connection before handing it to the loop.
    """

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured
        captured.setdefault("statements", [])

    def execute(self, statement: str, *args: Any) -> None:
        self._captured["statements"].append(statement)


def _capture_run_worker_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub out the queue loop and the database so ``run_main`` can be run for
    its WIRING only: returns the kwargs it passed to ``run_worker``."""
    captured: dict[str, Any] = {}

    def _fake_run_worker(*args: Any, **kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    @contextlib.contextmanager
    def _fake_connect(*args: Any, **kwargs: Any) -> Iterator[object]:
        # A bare object() is no longer enough: run_main issues the optional
        # `SET ROLE` (#190) on the connection before the loop starts, so the
        # stub records statements and the wiring stays observable.
        yield _StubConnection(captured)

    monkeypatch.setattr("fel_workers.consumer.run_worker", _fake_run_worker)
    monkeypatch.setattr(psycopg, "connect", _fake_connect)
    return captured


def test_run_main_binds_no_model_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No FEL_ALLOW_MOCK_LLM => no structured model is bound at all.

    The mock model answers every extraction_run with fabricated financials
    (a fixed $100m ARR proposal against fixture span/document ids). Binding
    it unconditionally meant a production worker persisted those into a real
    tenant's needs_review queue, indistinguishable from genuine output.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["structured_llm"] is None


def test_run_main_binds_mock_model_with_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEL_ALLOW_MOCK_LLM=1 on the extraction queue is the explicit opt-in the
    CI/mock smoke path uses."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1", "--queue", EXTRACTION_QUEUE]) == 0
    assert isinstance(captured["structured_llm"], MockStructuredLLMProvider)


def test_run_main_binds_no_model_on_a_non_extraction_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in binds a model only for the queue that carries extraction work.

    ``run_main`` is reachable directly (library/test contract) without the
    :func:`run_entry` startup gate, so the binding itself — not only the gate —
    has to be queue-scoped. Otherwise an ingestion worker holds a model whose
    only possible use is answering a misrouted ``extraction_run`` with
    fabricated proposals.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "1")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1", "--queue", "ingestion"]) == 0
    assert captured["structured_llm"] is None


def test_build_structured_llm_rejects_typo_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in shares the strict mode-flag parser: a typo fails closed
    rather than silently reading as unset."""
    monkeypatch.setenv("FEL_ALLOW_MOCK_LLM", "ture")
    with pytest.raises(RuntimeError) as excinfo:
        build_structured_llm(EXTRACTION_QUEUE)
    assert "FEL_ALLOW_MOCK_LLM" in str(excinfo.value)


def test_extraction_memory_stores_defaults_to_durable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No FEL_EXTRACTION_MEMORY_STORES => durable stores, and no warning.

    In-memory stores discard every proposal, conflict, step and event when
    the process exits while the job still completes as ``succeeded``, so the
    default has to be the one whose failure is visible. Selection used to be
    inferred from payload shape — inline ``evidence`` chose memory — which is
    how production runs silently wrote nothing at all.

    The silence is asserted, not incidental. A discard warning that also fired
    on every durable boot would train operators to filter it out, which costs
    nothing to a passing test and costs everything to the one run that really
    did discard its output.
    """
    monkeypatch.delenv("FEL_EXTRACTION_MEMORY_STORES", raising=False)
    with caplog.at_level(logging.WARNING, logger="fel_workers"):
        assert resolve_extraction_memory_stores() is False
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_extraction_memory_stores_accepts_documented_truthy_spellings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in shares the strict mode-flag parser: the documented set of
    'set' spellings is accepted after strip + lower-casing. That the set is
    *closed* is pinned separately, by
    ``test_extraction_memory_stores_rejects_falsy_and_typo_values``."""
    for spelling in ("1", "true", "TRUE", "yes", "on", "  on  "):
        monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", spelling)
        assert resolve_extraction_memory_stores() is True, spelling


def test_extraction_memory_stores_warns_that_output_is_discarded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Set truthy => a WARNING naming the discarded output is emitted.

    The run reports ``waiting_review`` and the job is marked ``succeeded``
    either way, so nothing downstream distinguishes a discarded run from a
    persisted one. This log line is the operator's first signal at startup
    that a job which looks successful wrote nothing (``consumer.py`` repeats
    it per job), which makes it part of the behaviour and not decoration.
    """
    monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", "1")
    with caplog.at_level(logging.WARNING, logger="fel_workers"):
        assert resolve_extraction_memory_stores() is True
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "FEL_EXTRACTION_MEMORY_STORES" in message
    assert "DISCARDED" in message
    assert "succeeded" in message


def test_extraction_memory_stores_rejects_falsy_and_typo_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``0``/``false``/``no``/``off`` and typos like ``ture`` fail closed.

    Falsy spellings are rejected rather than read as unset for the same
    reason as the other mode flags: ``FEL_EXTRACTION_MEMORY_STORES=false``
    from an operator who believes they configured something must not become
    indistinguishable from an unset variable. The error names the variable
    and the value received so the deploy log says which one to fix.

    ``no`` is the entry that matters most, and is listed as rejected by
    ``_read_mode_flag`` itself. It is the one spelling whose mis-parse fails
    in the *dangerous* direction: were it ever admitted to the truthy set — by
    a "be lenient with booleans" change, or by swapping in a generic parser
    that recognises it — an operator writing "no, don't use memory stores"
    would select exactly the stores that discard everything. ``0``/``false``/
    ``off`` flipping truthy is caught by the entries beside it.

    The padded ``' ture '`` pins a separate property: the message echoes the
    raw value, whitespace and all, so an operator sees the stray padding that
    a stripped echo would hide.
    """
    for value in ("0", "false", "no", "off", "ture", " ture "):
        monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", value)
        with pytest.raises(RuntimeError) as excinfo:
            resolve_extraction_memory_stores()
        assert "FEL_EXTRACTION_MEMORY_STORES" in str(excinfo.value), value
        assert repr(value) in str(excinfo.value), value


def test_extraction_memory_stores_blank_value_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty / whitespace-only reads as unset, not as an unrecognized value:
    an env var declared but left blank (compose files, Railway variables) is
    the ordinary way to say 'not configured' and must take the durable path
    rather than refusing to start."""
    for blank in ("", "   ", "\t\n"):
        monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", blank)
        assert resolve_extraction_memory_stores() is False, repr(blank)


def test_run_main_selects_durable_extraction_stores_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default reaches the queue loop: with a connection open and no
    opt-in, ``run_worker`` is asked for durable persistence."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.delenv("FEL_EXTRACTION_MEMORY_STORES", raising=False)
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["extraction_memory_stores"] is False


def test_run_main_forwards_the_extraction_memory_stores_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in reaches the queue loop too, not just the resolver.

    Without this, ``run_main`` could drop the resolved value on the floor and
    still look correct from the outside: the scary warning is emitted by the
    resolver, and the process still exits 0. The documented smoke run
    (``docs/runbooks/extraction-worker.md``) would quietly persist to Postgres
    instead of memory, which is the opposite of what the operator asked for.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", "1")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["extraction_memory_stores"] is True


def test_run_main_exits_two_on_unrecognized_extraction_memory_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo exits 2 before the queue loop rather than being guessed at.

    ``ture`` read as unset would be the benign direction, but the gate is
    shared with the flags where guessing is unsafe, so it refuses uniformly —
    and no job is claimed while the configuration is ambiguous.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.setenv("FEL_EXTRACTION_MEMORY_STORES", "ture")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 2
    assert captured == {}


def test_extraction_queue_literal_matches_handler_constant() -> None:
    """The entrypoint names the extraction queue as a literal (like the
    'ingestion' argparse default) — this pins it to the handler's constant so
    a rename cannot silently disarm the startup gate."""
    from fel_workers.extraction.handler import DEFAULT_EXTRACTION_QUEUE

    assert EXTRACTION_QUEUE == DEFAULT_EXTRACTION_QUEUE


@pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL") is None, reason="TEST_DATABASE_URL not configured"
)
def test_run_mode_drains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m fel_workers run` binds the mock providers by default and
    exits cleanly once the bounded iteration budget is spent."""
    monkeypatch.setenv("FEL_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    assert run_main(["--max-iterations", "1", "--queue", "entrypoint-test"]) == 0


def test_run_main_adopts_the_worker_role_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEL_WORKER_DB_ROLE must be applied to the worker's own connection.

    The rollout switch is worthless if it only reaches the heartbeat
    connection: every ingestion/extraction write in the process runs on THIS
    connection, so the SET ROLE has to happen here, before the loop starts.
    """
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", "fel_worker")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["statements"] == ["SET ROLE fel_worker"]


def test_run_main_without_the_role_switch_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.delenv("FEL_WORKER_DB_ROLE", raising=False)
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    assert captured["statements"] == []


def test_run_main_refuses_a_malformed_role_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unusable role must exit 2, not run the loop with owner privileges."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.setenv("FEL_WORKER_DB_ROLE", "fel_worker; DROP TABLE jobs")
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 2
    assert captured["statements"] == []
    assert "structured_llm" not in captured


def test_run_main_starts_the_health_endpoint_when_a_port_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint is opt-in, and the loop's liveness must reach it without
    consumer.py knowing anything about it: run_main wraps should_continue."""
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.delenv("FEL_WORKER_DB_ROLE", raising=False)
    # A free high port picked from the OS: 0 is deliberately rejected by
    # resolve_health_port (a deployment nobody can dial is a misconfiguration).
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    monkeypatch.setenv("FEL_WORKER_HEALTH_PORT", str(free_port))
    captured = _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 0
    should_continue = captured["should_continue"]
    assert should_continue() is True  # touches liveness; must not raise


def test_run_main_rejects_a_bad_health_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEL_DATABASE_URL", "postgresql://unused.invalid/never-connected")
    monkeypatch.delenv("FEL_SEC_LIVE", raising=False)
    monkeypatch.delenv("FEL_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.setenv("FEL_WORKER_HEALTH_PORT", "not-a-port")
    _capture_run_worker_kwargs(monkeypatch)
    assert run_main(["--max-iterations", "1"]) == 2
