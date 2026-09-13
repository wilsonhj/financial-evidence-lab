"""New decisions validate durable current heads, including merged winners."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fel_workers.extraction.hashing import hash_json
from tests.extraction.test_conflicts import alternative, decision
from tests.extraction.test_review_atomicity import command


def proposal(url, fixture, payload, run_id=None):
    identity = str(uuid.uuid4())
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO extraction_proposals(id,org_id,workspace_id,run_id,kind,metric_id,"
            "payload,raw_payload_hash,definition_hash,comparability_key,validation_summary,state) "
            "SELECT %s,org_id,workspace_id,COALESCE(%s::uuid,run_id),kind,%s,%s,%s,definition_hash,"
            "comparability_key,'{}'::jsonb,'needs_review' FROM extraction_proposals WHERE id=%s",
            (
                identity,
                run_id,
                payload["metric_id"],
                Jsonb(payload),
                hash_json(payload),
                fixture["proposal"],
            ),
        )
        conn.execute(
            "INSERT INTO extraction_proposal_evidence(proposal_id,org_id,source_span_id,"
            "document_version_id,role,citation_status) SELECT %s,org_id,source_span_id,"
            "document_version_id,role,citation_status FROM extraction_proposal_evidence "
            "WHERE proposal_id=%s",
            (identity, fixture["proposal"]),
        )
    return identity


def submit(client, tenant, body):
    return client.post(
        "/v1/extractions/review",
        json=body,
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )


def correct(client, tenant, record, value):
    path = "/v1/approved-extractions/" + record
    current = client.get(path, headers=tenant["headers"])
    assert current.status_code == 200, current.text
    return client.post(
        path + "/corrections",
        json={
            "reason": "Reconcile the current source reading.",
            "payload": {**current.json()["payload"], "value": value, "raw_value": value},
            "evidence": current.json()["evidence"],
        },
        headers={
            **tenant["headers"],
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": current.headers["ETag"],
        },
    )


def approved_balances(client, tenant, url, fixture):
    ids = []
    for metric, value, qualifiers, dimensions in (
        ("rpo", "1000", {"currency": "USD", "usage_exemption": "none", "label_family": "rpo"}, {}),
        ("crpo", "400", {"currency": "USD", "horizon_months": "12"}, {"horizon": "12m"}),
    ):
        payload = {
            **fixture["payload"],
            "metric_id": metric,
            "value": value,
            "raw_value": value,
            "scale": 0,
            "definition": None,
            "qualifiers": qualifiers,
            "dimensions": dimensions,
        }
        ids.append(proposal(url, fixture, payload))
    accepted = submit(
        client,
        tenant,
        {
            "action": "accept",
            "extraction_ids": ids,
            "expected_versions": dict.fromkeys(ids, 1),
            "reason": "Approve the supported balances.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    records = {}
    for record in accepted.json()["approved_record_ids"]:
        detail = client.get("/v1/approved-extractions/" + record, headers=tenant["headers"])
        records[detail.json()["metric_id"]] = record
    return records


def test_correction_uses_current_accounting_peer(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
):
    records = approved_balances(
        extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
    )
    first = correct(extraction_client, extraction_tenant, records["rpo"], "500")
    assert first.status_code == 201, first.text
    second = correct(extraction_client, extraction_tenant, records["crpo"], "600")
    assert second.status_code == 422, second.text
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT version FROM approved_extraction_records WHERE id=%s", (records["crpo"],)
            ).fetchone()[0]
            == 1
        )


def test_merged_winner_blocks_remaining_alternative_and_allows_explicit_alignment(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    client, tenant, fixture = extraction_client, extraction_tenant, waiting_review_fixture
    other, group = alternative(extraction_url, tenant, fixture)
    pending = proposal(
        extraction_url, fixture, {**fixture["payload"], "value": "120", "raw_value": "$120 million"}
    )
    with psycopg.connect(extraction_url) as conn:
        conn.execute(
            "INSERT INTO extraction_conflict_members(conflict_id,org_id,proposal_id) "
            "VALUES (%s,%s,%s)",
            (group, tenant["org"], pending),
        )
    ids = [fixture["proposal"], other]
    merged = submit(
        client,
        tenant,
        {
            "action": "merge",
            "extraction_ids": ids,
            "expected_versions": dict.fromkeys(ids, 1),
            "reason": "Keep the first supported reading.",
            "patch": {"payload_source_id": fixture["proposal"]},
            "conflict_resolution": [decision(client, tenant, group, [fixture["proposal"]])],
        },
    )
    assert merged.status_code == 200, merged.text
    rejected = submit(client, tenant, command(pending))
    assert rejected.status_code == 409, rejected.text
    # An explicit edit removing the disagreement remains legal and retains
    # both the old proposal bytes and the previously adjudicated merge.
    record = merged.json()["approved_record_ids"][0]
    path = "/v1/approved-extractions/" + record
    original = client.get(path, headers=tenant["headers"])
    same_value = {**original.json()["payload"], "value": "100", "raw_value": "$100 million"}
    edited = submit(
        client,
        tenant,
        {
            **command(pending, "edit"),
            "patch": [
                {
                    "extraction_id": pending,
                    "payload": same_value,
                    "evidence": original.json()["evidence"],
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.text


def test_later_edit_compares_with_approved_edit_not_original_proposal(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    client, tenant, fixture = extraction_client, extraction_tenant, waiting_review_fixture
    other, group = alternative(extraction_url, tenant, fixture)
    original = {key: value for key, value in fixture["payload"].items() if key != "evidence"}
    edges = [
        {
            "source_span_id": source_fixture["span"],
            "document_version_id": source_fixture["version"],
            "role": "supports",
        }
    ]
    edited = submit(
        client,
        tenant,
        {
            **command(fixture["proposal"], "edit"),
            "patch": [
                {
                    "extraction_id": fixture["proposal"],
                    "payload": {**original, "value": "105", "raw_value": "$105 million"},
                    "evidence": edges,
                }
            ],
            "conflict_resolution": [decision(client, tenant, group, [fixture["proposal"]])],
        },
    )
    assert edited.status_code == 200, edited.text
    obsolete = submit(
        client,
        tenant,
        {
            **command(other, "edit"),
            "patch": [{"extraction_id": other, "payload": original, "evidence": edges}],
        },
    )
    assert obsolete.status_code == 409, obsolete.text
    aligned = submit(
        client,
        tenant,
        {
            **command(other, "edit"),
            "patch": [
                {
                    "extraction_id": other,
                    "payload": {**original, "value": "105", "raw_value": "$105 million"},
                    "evidence": edges,
                }
            ],
        },
    )
    assert aligned.status_code == 200, aligned.text


def test_concurrent_accounting_corrections_serialize_on_peer_runs(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, monkeypatch
):
    from app.extraction import review

    records = approved_balances(
        extraction_client, extraction_tenant, extraction_url, waiting_review_fixture
    )
    entered, release, once = Event(), Event(), Lock()
    original = review._locked_rows

    def pause_first(*args):
        rows = original(*args)
        if once.acquire(blocking=False):
            entered.set()
            assert release.wait(10)
        return rows

    monkeypatch.setattr(review, "_locked_rows", pause_first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(correct, extraction_client, extraction_tenant, records["rpo"], "500")
        assert entered.wait(5)
        second = pool.submit(correct, extraction_client, extraction_tenant, records["crpo"], "600")
        blocked = False
        try:
            with psycopg.connect(extraction_url, autocommit=True) as conn:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    blocked = conn.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid))>0)"
                    ).fetchone()[0]
                    if blocked:
                        break
                    time.sleep(0.01)
        finally:
            release.set()
        a, b = first.result(5), second.result(5)
    assert blocked, "Competing correction never waited for the shared source run"
    assert a.status_code == 201, a.text
    assert b.status_code == 422, b.text


def test_non_origin_source_run_discovers_merged_accounting_peer(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    from fel_workers.extraction.handler import handle_extraction_run
    from tests.extraction.test_mock_lifecycle import ScopedMock
    from tests.extraction.test_run_creation import _create

    client, tenant, fixture = extraction_client, extraction_tenant, waiting_review_fixture
    created = _create(client, tenant, source_fixture)
    assert created.status_code == 202, created.text
    other_run = created.json()["id"]
    with psycopg.connect(extraction_url, row_factory=dict_row) as conn:
        job = conn.execute("SELECT payload FROM jobs WHERE id=%s", (other_run,)).fetchone()
    with psycopg.connect(extraction_url, autocommit=True) as conn:
        conn.execute("SET ROLE fel_worker")
        state = handle_extraction_run(
            conn, ScopedMock(tenant, source_fixture), job["payload"], job_org_id=tenant["org"]
        )
    assert state.status == "waiting_review"
    rpo = {
        **fixture["payload"],
        "metric_id": "rpo",
        "value": "1000",
        "raw_value": "1000",
        "scale": 0,
        "definition": None,
        "qualifiers": {"currency": "USD", "usage_exemption": "none", "label_family": "rpo"},
    }
    a = proposal(extraction_url, fixture, rpo)
    b = proposal(extraction_url, fixture, {**rpo, "value": "2000", "raw_value": "2000"}, other_run)
    c = proposal(
        extraction_url,
        fixture,
        {
            **rpo,
            "metric_id": "crpo",
            "value": "400",
            "raw_value": "400",
            "qualifiers": {"currency": "USD", "horizon_months": "12"},
            "dimensions": {"horizon": "12m"},
        },
        other_run,
    )
    group = str(uuid.uuid4())
    with psycopg.connect(extraction_url) as conn:
        # Select the worker ARR rather than either manually seeded balance.
        other_arr = str(
            conn.execute(
                "SELECT id FROM extraction_proposals WHERE run_id=%s AND metric_id='arr'",
                (other_run,),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO extraction_conflicts(id,org_id,workspace_id,conflict_key,reason_codes) "
            "VALUES (%s,%s,%s,%s,ARRAY['value_disagreement'])",
            (group, tenant["org"], tenant["workspace"], hash_json({"legacy_group": group})),
        )
        for pid in (a, b):
            conn.execute(
                "INSERT INTO extraction_conflict_members(conflict_id,org_id,proposal_id) "
                "VALUES (%s,%s,%s)",
                (group, tenant["org"], pid),
            )
    # Dispose the duplicate mock ARR; it is unrelated to the balance identity.
    rejected = submit(client, tenant, command(other_arr, "reject"))
    assert rejected.status_code == 200, rejected.text
    merged = submit(
        client,
        tenant,
        {
            "action": "merge",
            "extraction_ids": [a, b],
            "expected_versions": {a: 1, b: 1},
            "reason": "Keep supported RPO across legacy source runs.",
            "patch": {"payload_source_id": a},
            "conflict_resolution": [decision(client, tenant, group, [a])],
        },
    )
    assert merged.status_code == 200, merged.text
    accepted = submit(client, tenant, command(c))
    assert accepted.status_code == 200, accepted.text
    corrected = correct(client, tenant, accepted.json()["approved_record_ids"][0], "1500")
    assert corrected.status_code == 422, corrected.text
