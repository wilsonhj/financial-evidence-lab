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
  jobs with fabricated financials. The opt-in and the selected queue are
  cross-checked in BOTH directions at startup
  (:func:`validate_extraction_model_binding`): the ``extraction`` queue
  without the opt-in exits 2, and the opt-in on any other queue exits 2 too
  — a model bound to a non-extraction worker has no legitimate use and only
  serves to answer misrouted ``extraction_run`` jobs with fabricated output.

  Flag parsing is strict and normalized (see :func:`_read_mode_flag`):
  after stripping whitespace, case-insensitive ``1``/``true``/``yes``/``on``
  means set; absent or empty means unset; ANY other non-empty value (e.g.
  the typo ``ture``, or ``0``) exits with status 2 rather than being
  guessed at. With neither (or both) mode set, the process exits with
  status 2 before any database connection is attempted. ``--max-iterations``
  bounds the loop for tests/one-shot drains.

Three further, independent opt-ins, all off when unset:

- ``FEL_WORKER_DB_ROLE`` (#190, ADR-0013) — ``SET ROLE`` on every worker
  connection right after connect, so the job path runs as the least-privilege
  ``fel_worker`` role instead of the connection's login role. Unset keeps the
  previous behaviour exactly; a value that is not a plain SQL identifier
  exits 2.
- ``FEL_WORKER_HEALTH_PORT`` (#200) — serve ``GET /health`` (see
  :mod:`fel_workers.health`). The loop's liveness is observed here, by
  wrapping the ``should_continue`` callback the consumer already takes, so
  the consumer loop needs no knowledge of the endpoint.
- ``FEL_SENTRY_DSN`` (#203) — initialise Sentry with PII off (see
  :func:`init_sentry`); the SDK is imported lazily and its absence is a
  warning, not a startup failure.
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

from fel_workers.health import HEALTH_PORT_ENV, Liveness, start_health_server

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


def build_structured_llm(queue_name: str) -> StructuredLLMProvider | None:
    """Bind the structured-model provider for run mode from the environment.

    Returns ``None`` unless BOTH conditions hold: ``FEL_ALLOW_MOCK_LLM`` is
    set truthy (strict parsing via :func:`_read_mode_flag`) AND the worker is
    pointed at :data:`EXTRACTION_QUEUE`. The queue argument is not decoration:
    the opt-in alone used to bind the model on ANY queue, so an ``ingestion``
    worker carried a model it had no legitimate use for, and ``run_worker``
    (which never compares queue name to job kind) would answer an
    ``extraction_run`` claimed from that queue with fabricated output. Binding
    is therefore scoped to the queue that carries extraction work, and stays
    correct when the live adapter replaces the mock in #62.

    The mock is deliberately NOT implied by ``FEL_MOCK_SMOKE``: mock SEC
    ingestion fabricates documents, but the mock model fabricates complete
    financial PROPOSALS — a fixed ARR figure, period and evidence span ids —
    which the extraction persist path writes into a tenant's ``needs_review``
    queue, indistinguishable from genuine model output for a human reviewer.
    That blast radius gets its own opt-in.

    With no model bound, ``extraction_run`` jobs are failed closed at
    dispatch by :func:`fel_workers.consumer.run_worker` (missing-capability
    path) rather than answered with fabricated output.
    """
    if not _read_mode_flag("FEL_ALLOW_MOCK_LLM") or queue_name != EXTRACTION_QUEUE:
        return None
    from fel_providers.mocks import MockStructuredLLMProvider

    log.warning(
        "FEL_ALLOW_MOCK_LLM is set: extraction_run jobs will be answered by the"
        " deterministic MOCK model and will persist FABRICATED proposals into"
        " the review queue. Non-production smoke option only."
    )
    return MockStructuredLLMProvider()


def resolve_extraction_memory_stores() -> bool:
    """Whether ``extraction_run`` output goes to in-memory stores (default: no).

    Durable persistence is the default whenever the worker has a connection;
    only ``FEL_EXTRACTION_MEMORY_STORES`` set truthy (strict parsing via
    :func:`_read_mode_flag`) turns it off. This replaces a selection made from
    payload shape: a payload carrying inline ``evidence`` silently redirected
    every write to memory, so the run reported ``waiting_review``, the job was
    marked ``succeeded``, and nothing at all was written. Which output survives
    is an operator decision, not something an enqueuer can set by accident.

    Its purpose is the smoke run documented in
    ``docs/runbooks/extraction-worker.md``: exercising the pipeline end to end
    against inline evidence without seeding an ``extraction_runs`` row or a
    workspace. Every job run this way is logged as discarding its output.
    """
    if not _read_mode_flag("FEL_EXTRACTION_MEMORY_STORES"):
        return False
    log.warning(
        "FEL_EXTRACTION_MEMORY_STORES is set: extraction_run output will be"
        " written to IN-MEMORY stores and DISCARDED when the process exits —"
        " no proposals, conflicts, steps or events reach the database, and"
        " jobs still complete as succeeded. Non-production smoke option only."
    )
    return True


def validate_extraction_model_binding(queue_name: str) -> None:
    """Cross-check the model opt-in against the queue the worker will serve.

    ``extraction_run`` jobs are enqueued on :data:`EXTRACTION_QUEUE`, so the
    selected queue is the one startup-visible signal for "this worker will
    dispatch extraction". Both directions of the pairing fail closed:

    - extraction queue, no model: the worker can only fail every job it
      claims, and failing at startup puts that in the deploy log instead of
      leaving an apparently healthy service to bury it in the job table.
    - model opt-in, some OTHER queue: the operator asked for a model on a
      queue that carries no extraction work. Previously this silently bound
      the mock to an ingestion worker (the gate only looked at the extraction
      queue, and the binding only looked at the flag), which is how an
      ``extraction_run`` landing on the ingestion queue got answered with
      fabricated financial proposals. Refusing to start names the
      contradiction rather than guessing which half was intended.

    A worker with NEITHER — a live SEC ingestion worker — legitimately needs
    no model and must still start; an ``extraction_run`` that reaches it
    anyway is failed closed at dispatch.
    """
    opted_in = _read_mode_flag("FEL_ALLOW_MOCK_LLM")
    if queue_name == EXTRACTION_QUEUE:
        if opted_in:
            return
        raise RuntimeError(
            f"queue {queue_name!r} carries extraction_run jobs but no model is"
            " configured — refusing to start. Set FEL_ALLOW_MOCK_LLM=1 to opt in"
            " explicitly to the deterministic mock model. WARNING: the mock model"
            " answers every extraction with FABRICATED financial proposals that"
            " land in the review queue looking like genuine output; it must never"
            " point at a production database or queue."
        )
    if opted_in:
        raise RuntimeError(
            f"FEL_ALLOW_MOCK_LLM is set but queue {queue_name!r} does not carry"
            f" extraction_run jobs (that is queue {EXTRACTION_QUEUE!r}) — refusing"
            " to start. A model bound to a non-extraction worker has no legitimate"
            " use and turns any extraction_run misrouted onto this queue into"
            " fabricated proposals in a tenant's review queue. Point the worker at"
            f" --queue {EXTRACTION_QUEUE} or unset FEL_ALLOW_MOCK_LLM."
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


def resolve_health_port() -> int | None:
    """Port for the ``GET /health`` endpoint, or ``None`` when unset.

    Off by default: a worker with no platform health check has no use for an
    open socket. A non-numeric or out-of-range value raises rather than being
    ignored — an operator who asked for a health check and silently did not
    get one is worse off than one whose deploy fails loudly (exit 2).
    """
    raw = os.environ.get(HEALTH_PORT_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        port = int(raw.strip())
    except ValueError:
        raise RuntimeError(f"{HEALTH_PORT_ENV} must be an integer port; got {raw!r}.") from None
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{HEALTH_PORT_ENV} must be in 1..65535; got {port}.")
    return port


def init_sentry() -> bool:
    """Initialise Sentry when ``FEL_SENTRY_DSN`` is set; otherwise do nothing.

    Returns whether the SDK was initialised. The import is lazy and optional
    on purpose: ``sentry-sdk`` is not a worker dependency, so a deployment
    that has not installed it must still start — but silently swallowing the
    DSN would leave an operator believing errors are being reported when they
    are not, so the missing SDK is logged as a warning.

    ``send_default_pii=False`` is not the SDK default in every version and is
    pinned here deliberately: worker jobs carry tenant identifiers and filing
    payloads, none of which belongs in an error-tracking service.
    ``traces_sample_rate`` comes from ``FEL_SENTRY_TRACES_SAMPLE_RATE`` and
    defaults to 0 (errors only, no performance traces).
    """
    dsn = os.environ.get("FEL_SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning(
            "FEL_SENTRY_DSN is set but the sentry-sdk package is not installed;"
            " worker errors will NOT be reported. Install sentry-sdk or unset"
            " FEL_SENTRY_DSN."
        )
        return False
    raw_rate = os.environ.get("FEL_SENTRY_TRACES_SAMPLE_RATE", "").strip()
    try:
        traces_sample_rate = float(raw_rate) if raw_rate else 0.0
    except ValueError:
        log.warning(
            "FEL_SENTRY_TRACES_SAMPLE_RATE has non-numeric value %r; using 0.0",
            raw_rate,
        )
        traces_sample_rate = 0.0
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
    )
    log.info("sentry initialised (traces_sample_rate=%s)", traces_sample_rate)
    return True


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
    from fel_workers.storage import apply_worker_db_role

    _configure()
    args = parse_run_args(argv)
    database_url = os.environ.get("FEL_DATABASE_URL")
    if not database_url:
        log.error("FEL_DATABASE_URL is not configured")
        return 2
    try:
        sec, storage = build_run_providers()
        structured_llm = build_structured_llm(args.queue)
        memory_stores = resolve_extraction_memory_stores()
        health_port = resolve_health_port()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    init_sentry()
    # Liveness is owned HERE, not by the consumer loop: the loop already takes
    # a ``should_continue`` callback, so wrapping it is enough to observe every
    # iteration without touching consumer.py.
    liveness = Liveness(queue=args.queue)
    health_server = start_health_server(liveness, port=health_port)[0] if health_port else None

    def _alive() -> bool:
        liveness.touch()
        return _running

    with psycopg.connect(database_url, autocommit=True) as conn:
        # Opt-in least-privilege role for the job path (#190); no-op unless
        # FEL_WORKER_DB_ROLE is set. Applied here, before the first
        # statement, so every worker write in this process runs under it.
        try:
            apply_worker_db_role(conn)
        except RuntimeError as exc:
            log.error("%s", exc)
            return 2
        completed = run_worker(
            conn,
            storage,
            sec,
            queue_name=args.queue,
            max_iterations=args.max_iterations,
            should_continue=_alive,
            structured_llm=structured_llm,
            extraction_memory_stores=memory_stores,
        )
    if health_server is not None:
        health_server.shutdown()
        health_server.server_close()
    log.info("worker run mode finished; %d job(s) completed", completed)
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "run":
        raise SystemExit(run_entry(sys.argv[2:]))
    raise SystemExit(main())
