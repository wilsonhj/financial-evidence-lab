"""Process entrypoint for the worker service (`python -m fel_workers`).

Two modes:

- ``python -m fel_workers`` — heartbeat loop (default, unchanged): a real,
  observable process for the Railway worker service.
- ``python -m fel_workers run [--max-iterations N] [--queue NAME]`` — the
  job-queue consumer: claims queued jobs (FEL_DATABASE_URL) and dispatches
  SEC discovery/fetch work through :mod:`fel_workers.consumer`. Provider
  mode is EXPLICIT and fails closed (see :func:`run_entry`): exactly one of

  - ``FEL_SEC_LIVE`` set truthy — live EDGAR client (fair-access compliant).
    REQUIRES ``FEL_STORAGE_DIR`` (durable local-disk storage via
    :class:`fel_workers.storage.LocalDirStorageProvider`, because pairing
    live ingestion with in-memory mock storage would persist storage keys
    in the database while the blobs die with the process, leaving
    citations unresolvable) and ``FEL_SEC_USER_AGENT`` (the deployment's
    SEC fair-access identity; the in-code default is for library/tests
    only).
  - ``FEL_MOCK_SMOKE`` set truthy — deterministic mock providers, an
    explicit NON-PRODUCTION smoke option: mock runs claim real queued jobs
    and complete them with fabricated output, so they must never point at
    a production database or queue.

  The structured MODEL binding is a separate, equally explicit opt-in:
  ``FEL_ALLOW_MOCK_LLM`` (see :func:`build_structured_llm`). Nothing else
  binds a model, so an unconfigured worker cannot answer ``extraction_run``
  jobs with fabricated financials; a worker pointed at the ``extraction``
  queue without it exits 2 at startup (:func:`validate_extraction_model_binding`).

  Flag parsing is strict and normalized (see :func:`_read_mode_flag`):
  after stripping whitespace, case-insensitive ``1``/``true``/``yes``/``on``
  means set; absent or empty means unset; ANY other non-empty value (e.g.
  the typo ``ture``, or ``0``) exits with status 2 rather than being
  guessed at. With neither (or both) mode set, the process exits with
  status 2 before any database connection is attempted. ``--max-iterations``
  bounds the loop for tests/one-shot drains.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import time
from types import FrameType
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from fel_providers.interfaces import SecClient, StorageProvider, StructuredLLMProvider

log = logging.getLogger("fel_workers")

_running = True


def _request_stop(signum: int, frame: FrameType | None) -> None:
    global _running
    _running = False


def _configure() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)


def main(max_beats: int | None = None, interval_seconds: float = 30.0) -> int:
    """Log a heartbeat until stopped (SIGTERM/SIGINT) or max_beats is reached."""
    _configure()
    log.info("worker started in heartbeat mode; use 'run' for the job consumer")
    beats = 0
    while _running and (max_beats is None or beats < max_beats):
        log.info("heartbeat %d", beats)
        beats += 1
        if _running and (max_beats is None or beats < max_beats):
            time.sleep(interval_seconds)
    log.info("worker stopped after %d heartbeats", beats)
    return 0


# Accepted "set" spellings for mode flags, after strip + casefold.
_TRUTHY_FLAG_VALUES = frozenset({"1", "true", "yes", "on"})


def _read_mode_flag(name: str) -> bool:
    """Strict, normalized parse of a boolean mode flag from the environment.

    Semantics (fail closed on typos):

    - variable absent, or empty/whitespace-only after strip -> unset (False)
    - case-insensitive ``1``/``true``/``yes``/``on`` (after strip) -> set
    - ANY other non-empty value -> ``RuntimeError`` naming the variable and
      the received value (exit 2 upstream)

    ``0``/``false``/``no``/``off`` are deliberately REJECTED rather than
    treated as unset: the explicit way to unset a mode is to remove the
    variable. Accepting "falsy" spellings would mean guessing operator
    intent — e.g. ``FEL_SEC_LIVE=0`` alongside an unset ``FEL_MOCK_SMOKE``
    would silently produce the "no mode configured" outcome while the
    operator believes the service is configured. Rejecting them (like any
    other unrecognized value, e.g. the typo ``ture``) keeps the gate
    fail-closed instead of fail-open.
    """
    raw = os.environ.get(name)
    if raw is None:
        return False
    value = raw.strip()
    if not value:
        return False
    if value.lower() in _TRUTHY_FLAG_VALUES:
        return True
    raise RuntimeError(
        f"{name} has unrecognized value {raw!r} — expected 1/true/yes/on"
        " (case-insensitive) or unset (remove the variable). Refusing to"
        " guess: fix or remove the variable and restart."
    )


def parse_run_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m fel_workers run")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--queue", default="ingestion")
    return parser.parse_args(argv)


def build_run_providers() -> tuple[SecClient, StorageProvider]:
    """Bind (sec, storage) providers for run mode from the environment.

    Direct (library/test) calls default to the deterministic mocks when
    ``FEL_SEC_LIVE`` is unset; the DEPLOYMENT path never relies on that
    default — :func:`run_entry` gates provider mode explicitly (exit 2
    unless exactly one of ``FEL_SEC_LIVE``/``FEL_MOCK_SMOKE`` is set truthy;
    see :func:`_read_mode_flag`) before this function is reached.

    Live mode (``FEL_SEC_LIVE`` truthy): fails closed unless ``FEL_STORAGE_DIR``
    is set — live ingestion with in-memory mock storage would record
    storage_key/canonical_text_key rows whose blobs vanish with the process,
    silently breaking citation resolution. Raises ``RuntimeError`` naming
    both variables when the pairing is invalid. When ``FEL_SEC_USER_AGENT``
    is set, it is passed to :class:`LiveSecClient` as the SEC fair-access
    identity (required on the deployment path, enforced by
    :func:`run_entry`; the in-code default identity is for library/tests
    only).
    """
    from fel_providers.mocks import MockSecClient, MockStorageProvider
    from fel_workers.ingestion.sec_client import LiveSecClient
    from fel_workers.storage import LocalDirStorageProvider

    if not _read_mode_flag("FEL_SEC_LIVE"):
        return MockSecClient(), MockStorageProvider()
    storage_dir = os.environ.get("FEL_STORAGE_DIR")
    if not storage_dir:
        raise RuntimeError(
            "FEL_SEC_LIVE requires FEL_STORAGE_DIR: live SEC ingestion must"
            " write blobs to durable storage (LocalDirStorageProvider), not the"
            " in-memory mock — otherwise persisted storage keys become"
            " unresolvable when the process exits. Set FEL_STORAGE_DIR to a"
            " writable directory or unset FEL_SEC_LIVE."
        )
    user_agent = os.environ.get("FEL_SEC_USER_AGENT", "").strip()
    sec = LiveSecClient(user_agent=user_agent) if user_agent else LiveSecClient()
    return sec, LocalDirStorageProvider(storage_dir)


# Queue that carries extraction_run jobs. Named here as a literal, like the
# 'ingestion' argparse default above, so the configuration gates stay free of
# the extraction package's import graph; pinned to
# fel_workers.extraction.handler.DEFAULT_EXTRACTION_QUEUE by a test.
EXTRACTION_QUEUE = "extraction"


def build_structured_llm() -> StructuredLLMProvider | None:
    """Bind the structured-model provider for run mode from the environment.

    Returns ``None`` unless ``FEL_ALLOW_MOCK_LLM`` is set truthy (strict
    parsing via :func:`_read_mode_flag`). The mock is deliberately NOT
    implied by ``FEL_MOCK_SMOKE``: mock SEC ingestion fabricates documents,
    but the mock model fabricates complete financial PROPOSALS — a fixed
    ARR figure, period and evidence span ids — which the extraction persist
    path writes into a tenant's ``needs_review`` queue, indistinguishable
    from genuine model output for a human reviewer. That blast radius gets
    its own opt-in. The live OpenAI adapter lands with #62 credentials.

    With no model bound, ``extraction_run`` jobs are failed closed at
    dispatch by :func:`fel_workers.consumer.run_worker` (missing-capability
    path) rather than answered with fabricated output.
    """
    if not _read_mode_flag("FEL_ALLOW_MOCK_LLM"):
        return None
    from fel_providers.mocks import MockStructuredLLMProvider

    log.warning(
        "FEL_ALLOW_MOCK_LLM is set: extraction_run jobs will be answered by the"
        " deterministic MOCK model and will persist FABRICATED proposals into"
        " the review queue. Non-production smoke option only."
    )
    return MockStructuredLLMProvider()


def validate_extraction_model_binding(queue_name: str) -> None:
    """Refuse to start an extraction worker that has no model bound.

    ``extraction_run`` jobs are enqueued on :data:`EXTRACTION_QUEUE`, so the
    selected queue is the one startup-visible signal for "this worker will
    dispatch extraction". Such a worker with no model can only fail every
    job it claims, and failing at startup puts that in the deploy log
    instead of leaving an apparently healthy service to bury it in the job
    table. The gate is scoped to that queue on purpose: a live SEC ingestion
    worker legitimately needs no model and must still start, and an
    ``extraction_run`` that reaches it anyway is failed closed at dispatch.
    """
    if queue_name != EXTRACTION_QUEUE or _read_mode_flag("FEL_ALLOW_MOCK_LLM"):
        return
    raise RuntimeError(
        f"queue {queue_name!r} carries extraction_run jobs but no model is"
        " configured — refusing to start. Set FEL_ALLOW_MOCK_LLM=1 to opt in"
        " explicitly to the deterministic mock model. WARNING: the mock model"
        " answers every extraction with FABRICATED financial proposals that"
        " land in the review queue looking like genuine output; it must never"
        " point at a production database or queue."
    )


def resolve_provider_mode() -> str:
    """Resolve the explicit provider mode: ``"live"`` or ``"mock"``.

    The consumer never guesses: an unconfigured worker attached to a real
    database/queue with mock providers would mark real ``sec_discovery``
    jobs successful with empty output and could persist mock bytes under
    real accessions. Raises ``RuntimeError`` when neither — or both — of
    ``FEL_SEC_LIVE`` / ``FEL_MOCK_SMOKE`` is set truthy, or when either
    carries an unrecognized value (strict parsing via
    :func:`_read_mode_flag`; a typo like ``FEL_SEC_LIVE=ture`` fails closed
    instead of silently reading as unset).
    """
    live = _read_mode_flag("FEL_SEC_LIVE")
    mock = _read_mode_flag("FEL_MOCK_SMOKE")
    if live and mock:
        raise RuntimeError(
            "both FEL_SEC_LIVE and FEL_MOCK_SMOKE are set — provider mode"
            " is ambiguous; set exactly one and restart."
        )
    if live:
        return "live"
    if mock:
        return "mock"
    raise RuntimeError(
        "provider mode is not configured — refusing to start. Set"
        " FEL_SEC_LIVE=1 for live SEC ingestion (also requires"
        " FEL_STORAGE_DIR and FEL_SEC_USER_AGENT), or FEL_MOCK_SMOKE=1 to"
        " explicitly opt in to the deterministic mock providers. WARNING:"
        " mock mode claims real queued jobs and completes them with"
        " fabricated output; it must never point at a production database"
        " or queue."
    )


# Conservative contact-address check for the SEC fair-access identity:
# at least one non-'@'/non-space character before the '@', and after it a
# domain that contains a dot followed by an alphabetic TLD of >= 2 chars.
# This is NOT full RFC 5322 validation — it only rejects degenerate values
# ('@', 'x@', 'ops@example') that would pass a bare "contains '@'" test
# while giving the SEC no usable contact.
_CONTACT_MARKER_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def validate_live_user_agent() -> str:
    """Return the deployment SEC identity from ``FEL_SEC_USER_AGENT``.

    Live mode must not fall back to the in-code default User-Agent (a
    personal contact literal kept only for library/tests). Raises
    ``RuntimeError`` unless the stripped value is at least 8 characters
    long and contains a plausible contact address (``_CONTACT_MARKER_RE``:
    local part, ``@``, and a dotted domain with a >= 2-letter TLD).
    """
    user_agent = os.environ.get("FEL_SEC_USER_AGENT", "").strip()
    if len(user_agent) < 8 or not _CONTACT_MARKER_RE.search(user_agent):
        raise RuntimeError(
            "FEL_SEC_LIVE requires FEL_SEC_USER_AGENT: an SEC fair-access"
            " identity of the shape 'org-or-app name (contact@example.com)'"
            " — at least 8 characters, containing a plausible contact"
            " address ('@' with a dotted domain, e.g. ops@example.com;"
            " degenerate values like '@', 'x@', or 'ops@example' are"
            " rejected). The in-code default identity is for library/tests"
            " only; the production identity always comes from this variable."
        )
    return user_agent


def run_entry(argv: list[str]) -> int:
    """Deployment entrypoint for ``python -m fel_workers run``.

    Argument parsing runs FIRST so argparse's ``-h``/``--help`` contract
    (usage to stdout, exit 0) works even on an unconfigured service; the
    fail-closed gate runs immediately after, still before any database
    connection: it enforces an explicit provider mode
    (:func:`resolve_provider_mode`), in live mode a configured SEC identity
    (:func:`validate_live_user_agent`), and on the extraction queue a
    configured model (:func:`validate_extraction_model_binding`), then
    delegates to :func:`run_main`. Exits 2 on any configuration error.
    """
    args = parse_run_args(argv)  # -h/--help (and usage errors) resolve here
    _configure()
    try:
        if resolve_provider_mode() == "live":
            validate_live_user_agent()
        validate_extraction_model_binding(args.queue)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    return run_main(argv)


def run_main(argv: list[str]) -> int:
    """Run the job consumer against FEL_DATABASE_URL.

    In-process helper: assumes the provider mode was already gated by
    :func:`run_entry` (the only deployment path). Called directly, it keeps
    the legacy library/test contract of defaulting to mock providers via
    :func:`build_run_providers` — never expose this function as a service
    entrypoint without the :func:`run_entry` gate in front of it. The
    structured-model binding has no such default: it is ``None`` unless
    :func:`build_structured_llm` sees the explicit opt-in, on every path.
    """
    from fel_workers.consumer import run_worker

    _configure()
    args = parse_run_args(argv)
    database_url = os.environ.get("FEL_DATABASE_URL")
    if not database_url:
        log.error("FEL_DATABASE_URL is not configured")
        return 2
    try:
        sec, storage = build_run_providers()
        structured_llm = build_structured_llm()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    with psycopg.connect(database_url, autocommit=True) as conn:
        completed = run_worker(
            conn,
            storage,
            sec,
            queue_name=args.queue,
            max_iterations=args.max_iterations,
            should_continue=lambda: _running,
            structured_llm=structured_llm,
        )
    log.info("worker run mode finished; %d job(s) completed", completed)
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        raise SystemExit(run_entry(sys.argv[2:]))
    raise SystemExit(main())
