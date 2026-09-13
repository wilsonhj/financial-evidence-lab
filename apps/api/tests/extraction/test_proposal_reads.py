"""Proposal display preserves persisted values and never exposes worker controls."""

import json
import uuid

import psycopg
import pytest


def _payload(entity):
    return {
        "schema_version": "extraction-payload/v1",
        "kind": "kpi",
        "entity_id": entity,
        "issuer_label": "Fixture",
        "metric_id": "revenue",
        "raw_value": "10",
        "value": "10",
        "unit": "USD",
        "currency": "USD",
        "scale": 0,
        "sign": "positive",
        "period": {"type": "instant", "instant": "2026-01-01"},
        "dimensions": {},
        "qualifiers": {},
        "reported_or_derived": "reported",
    }


def _insert(url, tenant, run_id, payload, summary=None):
    proposal = str(uuid.uuid4())
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO extraction_proposals(id,org_id,workspace_id,run_id,kind,metric_id,payload,"
            "raw_payload_hash,definition_hash,record_confidence,validation_summary)"
            " VALUES (%s,%s,%s,%s,'kpi','revenue',%s,%s,%s,NULL,%s)",
            (
                proposal,
                tenant["org"],
                tenant["workspace"],
                run_id,
                payload if isinstance(payload, str) else json.dumps(payload),
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                json.dumps(summary or {}),
            ),
        )
    return proposal


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("value", 9007199254740993, "9007199254740993"),
        ("value", "banana", '"banana"'),
        ("metric_id", None, "null"),
        ("dimensions", ["emea"], '["emea"]'),
        ("scale", 0.5, "0.5"),
        ("entity_id", "invalid", '"invalid"'),
    ],
)
def test_malformed_candidate_preserves_sql_field_text(
    extraction_client, extraction_tenant, extraction_url, seeded_runs, field, value, expected
):
    payload = _payload(extraction_tenant["entity"])
    payload[field] = value
    payload["worker_secret"] = "do not display"
    proposal = _insert(
        extraction_url,
        extraction_tenant,
        seeded_runs[0],
        payload,
        {"ok": True, "blockers": ["duplicate_candidate", "unknown field: worker_secret"]},
    )
    response = extraction_client.get(
        f"/v1/extractions/{proposal}", headers=extraction_tenant["headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payload"]["schema_version"] == "extraction-candidate-fields/v1"
    assert body["payload"]["fields"][field] == expected
    assert body["evidence"] == [] and body["record_confidence"] is None
    assert {"code": "duplicate_candidate", "status": "fail"} in body["validations"]
    assert all(v["status"] != "pass" for v in body["validations"])
    assert "worker_secret" not in response.text and "do not display" not in response.text


@pytest.mark.parametrize(
    "qualifiers", [{"safe": 9007199254740991}, {"flag": True}, {"numeric_string": "1e400"}]
)
def test_valid_payload_shape_is_unchanged_despite_financial_blockers(
    extraction_client, extraction_tenant, extraction_url, seeded_runs, qualifiers
):
    payload = _payload(extraction_tenant["entity"])
    payload["qualifiers"] = qualifiers
    proposal = _insert(
        extraction_url,
        extraction_tenant,
        seeded_runs[0],
        {**payload, "evidence": []},
        {"ok": False, "blockers": ["margin_percent_out_of_range"]},
    )
    response = extraction_client.get(
        f"/v1/extractions/{proposal}", headers=extraction_tenant["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["payload"] == payload


@pytest.mark.parametrize("exponent", [400, 5000])
def test_nested_large_exponent_stays_exact_and_missing_fields_stay_absent(
    extraction_client, extraction_tenant, extraction_url, seeded_runs, exponent
):
    proposal = _insert(
        extraction_url,
        extraction_tenant,
        seeded_runs[0],
        '{"qualifiers":{"nested":[1e' + str(exponent) + ']},"value":null}',
    )
    response = extraction_client.get(
        f"/v1/extractions/{proposal}", headers=extraction_tenant["headers"]
    )
    assert response.status_code == 200, response.text
    fields = response.json()["payload"]["fields"]
    assert fields == {"qualifiers": '{"nested": [1' + "0" * exponent + "]}", "value": "null"}


@pytest.mark.parametrize("length", [65537, 1048577])
def test_oversize_payload_is_explicit_and_names_offending_proposal(
    extraction_client, extraction_tenant, extraction_url, seeded_runs, length
):
    proposal = _insert(
        extraction_url, extraction_tenant, seeded_runs[0], {"raw_value": "x" * length}
    )
    response = extraction_client.get(
        f"/v1/extractions/{proposal}", headers=extraction_tenant["headers"]
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "EXTRACTION_TOO_LARGE"
    assert proposal in str(response.json()["error"]["details"])
    assert "xxx" not in response.text
