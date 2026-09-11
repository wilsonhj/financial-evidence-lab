"""Read immutable extraction run and evidence pins."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import psycopg

from fel_workers.extraction.persist_types import RunPins, SpanPin


def load_run_pins(conn: psycopg.Connection[Any], *, run_id: str, org_id: str) -> RunPins | None:
    """Read the run's immutable identity back, or ``None`` if there is no row.

    Tenant-scoped by ``org_id`` like every other read here, so a payload
    cannot reach another org's run row to bind against.
    """
    row = conn.execute(
        """
            SELECT workspace_id, entity_id, modes, as_of, corpus_version_id,
                   ontology_version, workflow_version, provider, model, policy_id,
                   input_manifest, input_hash, max_calls, max_input_tokens,
                   max_output_tokens, max_cost_usd, max_wall_seconds
              FROM extraction_runs
             WHERE id = %s AND org_id = %s
            """,
        (run_id, org_id),
    ).fetchone()
    if row is None:
        return None
    manifest = row[10]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return RunPins(
        workspace_id=str(row[0]),
        entity_id=str(row[1]),
        modes=tuple(str(mode) for mode in row[2]),
        as_of=row[3],
        corpus_version_id=str(row[4]),
        ontology_version=str(row[5]),
        workflow_version=str(row[6]),
        provider=str(row[7]),
        model=str(row[8]),
        policy_id=str(row[9]),
        input_manifest=dict(manifest or {}),
        input_hash=str(row[11]),
        max_calls=int(row[12]),
        max_input_tokens=int(row[13]),
        max_output_tokens=int(row[14]),
        max_cost_usd=Decimal(str(row[15])),
        max_wall_seconds=int(row[16]),
    )


def load_span_pins(conn: psycopg.Connection[Any], span_ids: list[str]) -> dict[str, SpanPin]:
    """Canonical ``source_spans`` rows for the cited spans, keyed by span id.

    Spans are corpus-global (no ``org_id`` column in 0002); tenancy on the
    evidence path is carried by ``extraction_proposal_evidence``'s composite
    FK and by the run's own workspace bind, not here.

    Ids that are not well-formed UUIDs are simply absent from the result
    rather than raising: the caller fails them closed as unresolvable spans,
    which is the same outcome with a message that names the span.
    """
    wanted: list[str] = []
    for span_id in span_ids:
        try:
            wanted.append(str(uuid.UUID(span_id)))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = conn.execute(
        """
            SELECT id, document_version_id, text_hash
              FROM source_spans
             WHERE id = ANY(%s::uuid[])
            """,
        (wanted,),
    ).fetchall()
    return {
        str(row[0]): SpanPin(
            source_span_id=str(row[0]),
            document_version_id=str(row[1]),
            text_hash=str(row[2]),
        )
        for row in rows
    }
