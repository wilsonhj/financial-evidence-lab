"""extraction_run job handler (M3-102)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import psycopg

from fel_providers.interfaces import StructuredLLMProvider
from fel_workers.extraction.errors import IntegrityError, StepFailed
from fel_workers.extraction.hashing import canonical_json, hash_json, sha256_hex
from fel_workers.extraction.persist import (
    MemoryPersistStore,
    PostgresPersistStore,
    RunPins,
    assert_workspace_ownership,
)
from fel_workers.extraction.types import (
    WORKFLOW_VERSION,
    EvidenceBlock,
    ExtractionMode,
    ExtractionRunRequest,
    WorkflowState,
)
from fel_workers.extraction.workflow import WorkflowDeps, run_extraction_workflow

JOB_KIND_EXTRACTION_RUN = "extraction_run"
DEFAULT_EXTRACTION_QUEUE = "extraction"

__all__ = [
    "DEFAULT_EXTRACTION_QUEUE",
    "JOB_KIND_EXTRACTION_RUN",
    "handle_extraction_run",
    "request_from_payload",
]


def handle_extraction_run(
    conn: psycopg.Connection[Any] | None,
    structured_llm: StructuredLLMProvider,
    payload: dict[str, Any],
    *,
    lease_check: Callable[[], bool] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    use_memory_stores: bool | None = None,
    job_org_id: str | None = None,
) -> WorkflowState:
    """Dispatch one ``extraction_run`` job.

    Store selection never depends on payload SHAPE. A live ``conn`` means the
    durable Postgres stores; memory stores are used only when there is no
    connection to write to, or when a caller forces them with an explicit
    ``use_memory_stores=True``. Inline ``evidence``/``spans`` blocks supply the
    text for the run and nothing else — they used to also (silently) redirect
    every write to in-memory stores, so a run with a live connection returned
    ``waiting_review``, the job was marked ``succeeded``, and not one row was
    written. The two spellings are exact synonyms on every path.

    Tenancy on the durable path comes from the JOB, never from the payload:
    ``job_org_id`` (``ClaimedJob.org_id``) must be present AND equal the payload
    ``org_id``. A NULL job org is not "no constraint" — read that way, the
    payload self-asserts its own tenant, and the remaining control does not
    close the gap: ``assert_workspace_ownership`` only checks that workspace and
    org agree with each other, not that the enqueuer was entitled to that org.
    ``jobs.org_id`` is nullable by design for platform jobs (``sec_discovery``
    and friends legitimately have none); ``extraction_run`` writes tenant data
    and is not one of them. The requirement is scoped to the durable path —
    memory stores write nothing, so there is no tenant to protect.

    A durable run is also BOUND to its own ``extraction_runs`` row and to the
    canonical ``source_spans`` behind its evidence, before the first write. See
    :func:`_bind_request_to_run` and :func:`_bind_evidence_to_spans`: on this
    path the payload proposes and the record disposes. Both binds are scoped to
    the durable path because the memory path has neither a run row nor a corpus
    to bind against.
    """
    request = request_from_payload(payload)
    memory = use_memory_stores if use_memory_stores is not None else conn is None
    if job_org_id is not None and request.org_id != job_org_id:
        raise ValueError(
            f"extraction_run payload org_id {request.org_id} does not match "
            f"job org_id {job_org_id}"
        )
    evidence = _evidence_from_payload(payload)
    if not memory:
        if conn is None:
            raise RuntimeError("database persistence selected without a connection")
        if job_org_id is None:
            raise ValueError(
                "extraction_run reached the durable path with no job org_id: "
                f"refusing to persist run {request.run_id} on the payload's own "
                f"claim to org {request.org_id}. Enqueue extraction_run jobs "
                "tenant-bound — queue.enqueue(..., org_id=<tenant>)."
            )
        persist: Any = PostgresPersistStore(conn)
        # Bind BEFORE mark_running: a payload that contradicts its run row must
        # leave the row exactly as it found it, still claimable by a correct one.
        request = _bind_request_to_run(request, persist, payload)
        evidence = _bind_evidence_to_spans(evidence, persist)
        # Assert ownership of the BOUND workspace — the one that will be written.
        assert_workspace_ownership(conn, org_id=request.org_id, workspace_id=request.workspace_id)
        persist.mark_running(run_id=request.run_id, org_id=request.org_id)
        from fel_workers.extraction.persist import PostgresCheckpointStore, PostgresEventStore

        checkpoint: Any = PostgresCheckpointStore(conn)
        events: Any = PostgresEventStore(conn)
    else:
        persist = MemoryPersistStore()
        from fel_workers.extraction.checkpoint import MemoryCheckpointStore
        from fel_workers.extraction.events import MemoryEventStore

        checkpoint = MemoryCheckpointStore()
        events = MemoryEventStore()

    state = WorkflowState(request=request, evidence=evidence)
    deps = WorkflowDeps(
        structured_llm=structured_llm,
        checkpoint=checkpoint,
        events=events,
        persist=persist,
        lease_check=lease_check or (lambda: True),
        cancel_check=cancel_check or (lambda: False),
        evidence_loader=(lambda _req: list(evidence)),
    )
    return run_extraction_workflow(state, deps)


def _normalize_uuid(value: Any) -> str:
    return str(UUID(str(value)))


def _normalize_datetime(value: Any) -> datetime:
    moment = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    # A naive payload literal is read as UTC so it compares against the row's
    # timestamptz on instants rather than failing on tzinfo alone.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _normalize_modes(value: Any) -> tuple[str, ...]:
    return tuple(sorted(str(mode) for mode in value))


# Every pin ``fel_guard_extraction_run`` declares immutable, paired with the
# comparison that decides whether a payload's spelling of it agrees. The run row
# is the authority for all of them; ``run_id``/``org_id`` are absent because they
# are the lookup keys, and ``issuer_label`` because 0004 stores no such column.
_RUN_PIN_FIELDS: tuple[tuple[str, Callable[[Any], Any]], ...] = (
    ("workspace_id", _normalize_uuid),
    ("entity_id", _normalize_uuid),
    ("modes", _normalize_modes),
    ("as_of", _normalize_datetime),
    ("corpus_version_id", _normalize_uuid),
    ("ontology_version", str),
    ("workflow_version", str),
    ("provider", str),
    ("model", str),
    ("policy_id", _normalize_uuid),
    ("input_manifest", canonical_json),
    ("input_hash", str),
    ("max_calls", int),
    ("max_input_tokens", int),
    ("max_output_tokens", int),
    ("max_cost_usd", lambda v: Decimal(str(v))),
    ("max_wall_seconds", int),
)


def _bind_request_to_run(
    request: ExtractionRunRequest,
    persist: PostgresPersistStore,
    payload: dict[str, Any],
) -> ExtractionRunRequest:
    """Rebuild the request from the run's immutable record, refusing divergence.

    The durable path used to take EVERY pin from the payload — cutoff, corpus,
    ontology, provider, model, policy and all five ``max_*`` budgets — while the
    only read of ``extraction_runs`` selected four usage counters. Nothing
    compared a pin, so under a real ``run_id`` a payload could declare a cutoff a
    year later, a different corpus and a 250x budget, run to ``waiting_review``
    and persist proposals, while the row a reviewer reads still advertised the
    original pins. Two harms, both silent: evidence published past the run's true
    cutoff becomes admissible (look-ahead bias in a run whose whole value is
    being pinned), and 0004's ``CHECK (max_calls BETWEEN 1 AND 10)`` /
    ``CHECK (max_cost_usd <= 2.0)`` stop bounding anything, because the columns
    carrying them are never read.

    Binding runs in both directions. A pin the payload DECLARES must match the
    row, or the run is refused with ``run_pin_mismatch`` naming every divergence.
    A pin the payload OMITS is taken from the row rather than from
    :func:`request_from_payload`'s defaults — those defaults (``as_of`` = now,
    ``provider`` = mock, budgets = the ADR-0007 maximum) describe no particular
    run, and silently substituting them for a real run's pins is the same defect
    in a quieter form.
    """
    pins: RunPins | None = persist.load_run_pins(run_id=request.run_id, org_id=request.org_id)
    if pins is None:
        raise StepFailed(
            f"extraction_run {request.run_id} has no extraction_runs row in org "
            f"{request.org_id}: refusing to extract against a run that does not "
            "exist. Durable runs are created queued by the producer.",
            code="run_not_found",
        )

    data = _payload_data(payload)
    diverged: list[str] = []
    for field_name, normalize in _RUN_PIN_FIELDS:
        declared = data.get(field_name)
        if declared is None or (isinstance(declared, (str, list, dict)) and not declared):
            continue  # absent (or empty, as request_from_payload reads it): bind the row's
        pinned = getattr(pins, field_name)
        try:
            agrees = normalize(declared) == normalize(pinned)
        except (ArithmeticError, TypeError, ValueError):
            # An unparseable spelling cannot be shown to agree, so it does not.
            agrees = False
        if not agrees:
            diverged.append(f"{field_name}: payload {declared!r} != run {pinned!r}")

    if diverged:
        raise StepFailed(
            f"extraction_run {request.run_id} payload contradicts its immutable "
            "run record on " + "; ".join(diverged) + ". The run row is the "
            "authority for these pins; re-enqueue against a run whose pins match, "
            "or create a new run.",
            code="run_pin_mismatch",
        )

    return replace(
        request,
        workspace_id=pins.workspace_id,
        entity_id=pins.entity_id,
        modes=cast(tuple[ExtractionMode, ...], pins.modes),
        as_of=pins.as_of,
        corpus_version_id=pins.corpus_version_id,
        ontology_version=pins.ontology_version,
        workflow_version=pins.workflow_version,
        provider=pins.provider,
        model=pins.model,
        policy_id=pins.policy_id,
        input_manifest=dict(pins.input_manifest),
        input_hash=pins.input_hash,
        max_calls=pins.max_calls,
        max_input_tokens=pins.max_input_tokens,
        max_output_tokens=pins.max_output_tokens,
        max_cost_usd=pins.max_cost_usd,
        max_wall_seconds=pins.max_wall_seconds,
    )


def _bind_evidence_to_spans(
    evidence: list[EvidenceBlock],
    persist: PostgresPersistStore,
) -> list[EvidenceBlock]:
    """Verify supplied evidence against the canonical ``source_spans`` rows.

    ``_evidence_from_payload`` derives ``text_hash`` from the payload's OWN text
    when the payload does not supply one, so the integrity check in
    ``_stage_assemble_evidence`` compared a payload against itself and could only
    ever pass. ``source_spans`` was never SELECTed anywhere in ``workers/src`` —
    ingestion INSERTs the rows and nothing read them back — so the stored
    ``text_hash``, which IS the citation's content address, never entered the
    decision. Fabricated text under a real span id was therefore accepted and
    persisted as a cited proposal; the composite FK on
    ``extraction_proposal_evidence`` proves the span exists, never what it says.

    Each block is verified against its canonical row and rebuilt from it, so the
    hash that reaches ``extraction_proposal_evidence`` is the corpus's, not the
    payload's. Anything unresolvable or contradictory fails closed as
    ``integrity_error`` rather than degrading to the self-hash.
    """
    if not evidence:
        return evidence
    pins = persist.load_span_pins([block.source_span_id for block in evidence])
    bound: list[EvidenceBlock] = []
    for block in evidence:
        pin = pins.get(block.source_span_id)
        if pin is None:
            raise IntegrityError(
                f"evidence span {block.source_span_id} has no source_spans row: "
                "refusing to cite a span this corpus cannot resolve"
            )
        if block.document_version_id != pin.document_version_id:
            raise IntegrityError(
                f"evidence span {block.source_span_id} declares document_version_id "
                f"{block.document_version_id} but the span belongs to "
                f"{pin.document_version_id}"
            )
        actual = sha256_hex(block.text)
        if actual != pin.text_hash:
            raise IntegrityError(
                f"evidence text for span {block.source_span_id} does not match the "
                f"canonical source_spans text_hash ({actual} != {pin.text_hash}): "
                "refusing to extract from text this span does not address"
            )
        bound.append(replace(block, text_hash=pin.text_hash))
    return bound


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    """The pin-carrying dict: a nested ``request`` block, else the payload itself."""
    return dict(payload["request"]) if isinstance(payload.get("request"), dict) else dict(payload)


def request_from_payload(payload: dict[str, Any]) -> ExtractionRunRequest:
    """Build a pinned run request from a queue payload or inline test dict."""
    data = _payload_data(payload)

    modes_raw = data.get("modes") or ["kpi"]
    if not isinstance(modes_raw, (list, tuple)):
        raise ValueError("extraction_run modes must be a list")
    allowed = {"kpi", "guidance", "revenue_driver"}
    modes_list: list[ExtractionMode] = []
    for mode in modes_raw:
        mode_s = str(mode)
        if mode_s not in allowed:
            raise ValueError(f"unsupported extraction mode: {mode_s!r}")
        modes_list.append(cast(ExtractionMode, mode_s))
    modes: tuple[ExtractionMode, ...] = tuple(modes_list)
    as_of_raw = data.get("as_of") or datetime.now().isoformat()
    as_of = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))

    run_id = str(data.get("run_id") or data.get("id") or "")
    org_id = str(data.get("org_id") or "")
    workspace_id = str(data.get("workspace_id") or "")
    entity_id = str(data.get("entity_id") or "")
    for label, value in (
        ("run_id", run_id),
        ("org_id", org_id),
        ("workspace_id", workspace_id),
        ("entity_id", entity_id),
    ):
        if not value:
            raise ValueError(f"extraction_run payload missing {label}")
        UUID(value)

    input_manifest = data.get("input_manifest") or {}
    input_hash = str(data.get("input_hash") or hash_json(input_manifest))
    if not input_hash.startswith("sha256:"):
        input_hash = sha256_hex(input_hash)

    return ExtractionRunRequest(
        run_id=run_id,
        org_id=org_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        modes=modes,
        as_of=as_of,
        corpus_version_id=str(data.get("corpus_version_id") or entity_id),
        ontology_version=str(data.get("ontology_version") or "saas-metrics/v1"),
        workflow_version=str(data.get("workflow_version") or WORKFLOW_VERSION),
        provider=str(data.get("provider") or "mock"),
        model=str(data.get("model") or "mock-structured-v1"),
        policy_id=str(data.get("policy_id") or run_id),
        input_manifest=dict(input_manifest),
        input_hash=input_hash,
        max_calls=int(data.get("max_calls") or 10),
        max_input_tokens=int(data.get("max_input_tokens") or 100_000),
        max_output_tokens=int(data.get("max_output_tokens") or 20_000),
        max_cost_usd=Decimal(str(data.get("max_cost_usd") or "2.00")),
        max_wall_seconds=int(data.get("max_wall_seconds") or 600),
        issuer_label=str(data.get("issuer_label") or "Unknown Issuer"),
    )


def _evidence_from_payload(payload: dict[str, Any]) -> list[EvidenceBlock]:
    raw_blocks = payload.get("evidence") or payload.get("spans") or []
    blocks: list[EvidenceBlock] = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        span_id = str(item.get("source_span_id") or item.get("id") or "")
        if not span_id:
            continue
        text = str(item.get("text") or "")
        text_hash = str(item.get("text_hash") or sha256_hex(text))
        document_version_id = str(item.get("document_version_id") or "")
        if not document_version_id:
            raise ValueError(
                f"evidence span {span_id} missing document_version_id "
                "(must not default to source_span_id)"
            )
        published = item.get("published_at")
        published_at = None
        if published:
            published_at = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        blocks.append(
            EvidenceBlock(
                source_span_id=span_id,
                document_version_id=document_version_id,
                text=text,
                text_hash=text_hash,
                published_at=published_at,
            )
        )
    return blocks
