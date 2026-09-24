"""Foreign-tenant extraction resources stay hidden; DB roles authorize actions."""

import uuid

import psycopg
import pytest

from app.auth import make_mock_token
from tests.extraction.test_conflicts import alternative, decision
from tests.extraction.test_review_atomicity import command
from tests.extraction.test_run_creation import _request


def _foreign_owner(url):
    ids = {key: str(uuid.uuid4()) for key in ("org", "user", "workspace", "entity", "policy")}
    with psycopg.connect(url) as conn:
        conn.execute(
            "INSERT INTO organizations(id,name) VALUES (%s,'Foreign owner')", (ids["org"],)
        )
        conn.execute(
            "INSERT INTO memberships(org_id,user_id,role) VALUES (%s,%s,'owner')",
            (ids["org"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO workspaces(id,org_id,name,entity_id,base_currency,fiscal_calendar,as_of)"
            " VALUES (%s,%s,'Foreign',%s,'USD','FY','2026-06-30T00:00:00Z')",
            (ids["workspace"], ids["org"], ids["entity"]),
        )
        conn.execute(
            "INSERT INTO extraction_policies(id,org_id,version,created_by) VALUES (%s,%s,1,%s)",
            (ids["policy"], ids["org"], ids["user"]),
        )
    ids["headers"] = {
        "Authorization": f"Bearer {make_mock_token(ids['org'], ids['user'], 'owner')}"
    }
    return ids


def _side_effects(url, org):
    with psycopg.connect(url) as conn:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table} WHERE org_id=%s", (org,)).fetchone()[
                0
            ]
            for table in (
                "idempotency_keys",
                "extraction_runs",
                "extraction_reviews",
                "approved_extraction_versions",
                "audit_events",
            )
        }


def _hidden(response):
    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "tenant" not in error["message"].lower()
    return error


def _forbidden(response):
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def _set_role(url, tenant, role):
    with psycopg.connect(url) as conn:
        conn.execute(
            "UPDATE memberships SET role=%s WHERE org_id=%s AND user_id=%s",
            (role, tenant["org"], tenant["user"]),
        )


def _headers(tenant, claim):
    return {"Authorization": f"Bearer {make_mock_token(tenant['org'], tenant['user'], claim)}"}


def _edit_body(fixture, source):
    payload = {key: value for key, value in fixture["payload"].items() if key != "evidence"}
    payload["value"] = "101"
    payload["raw_value"] = "$101 million"
    return {
        **command(fixture["proposal"], "edit"),
        "patch": [
            {
                "extraction_id": fixture["proposal"],
                "payload": payload,
                "evidence": [
                    {
                        "source_span_id": source["span"],
                        "document_version_id": source["version"],
                        "role": "supports",
                        "citation_status": "invalid",
                    }
                ],
            }
        ],
    }


def _correction_body(original):
    return {
        "reason": "Corrected source reading.",
        "payload": {**original.json()["payload"], "value": "101", "raw_value": "$101 million"},
        "evidence": original.json()["evidence"],
    }


@pytest.fixture
def owner_resources(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    other, group = alternative(extraction_url, tenant, fixture)
    accepted = extraction_client.post(
        "/v1/extractions/review",
        json={
            **command(fixture["proposal"]),
            "conflict_resolution": [
                decision(extraction_client, tenant, group, [fixture["proposal"]])
            ],
        },
        headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    record_id = accepted.json()["approved_record_ids"][0]
    approved = extraction_client.get(
        "/v1/approved-extractions/" + record_id, headers=tenant["headers"]
    )
    run = extraction_client.get("/v1/extraction-runs/" + fixture["run"], headers=tenant["headers"])
    return {
        "tenant": tenant,
        "fixture": fixture,
        "source": source_fixture,
        "conflict": group,
        "other": other,
        "record": record_id,
        "version": approved.json()["version_id"],
        "run_etag": run.headers["ETag"],
        "approved": approved,
    }


READS = (
    "permissions",
    "run_list",
    "run_detail",
    "proposal_list",
    "proposal_detail",
    "steps",
    "conflict_list",
    "conflict_detail",
    "approved_detail",
    "approved_version",
    "approved_versions",
    "event_history",
    "events",
)


def _read(kind, resources):
    tenant, fixture = resources["tenant"], resources["fixture"]
    workspace = tenant["workspace"]
    run = fixture["run"]
    paths = {
        "permissions": f"/v1/workspaces/{workspace}/extraction-permissions",
        "run_list": f"/v1/workspaces/{workspace}/extraction-runs",
        "run_detail": f"/v1/extraction-runs/{run}",
        "proposal_list": f"/v1/workspaces/{workspace}/extractions",
        "proposal_detail": f"/v1/extractions/{fixture['proposal']}",
        "steps": f"/v1/extraction-runs/{run}/steps",
        "conflict_list": f"/v1/workspaces/{workspace}/extraction-conflicts",
        "conflict_detail": f"/v1/extraction-conflicts/{resources['conflict']}",
        "approved_detail": f"/v1/approved-extractions/{resources['record']}",
        "approved_version": (
            f"/v1/approved-extractions/{resources['record']}/versions/{resources['version']}"
        ),
        "approved_versions": f"/v1/approved-extractions/{resources['record']}/versions",
        "event_history": f"/v1/extraction-runs/{run}/event-history",
        "events": f"/v1/extraction-runs/{run}/events",
    }
    return paths[kind]


@pytest.mark.parametrize("kind", READS)
def test_foreign_owner_reads_are_hidden_404(
    extraction_client, extraction_url, owner_resources, kind
):
    owner = owner_resources["tenant"]
    stranger = _foreign_owner(extraction_url)
    before_owner = _side_effects(extraction_url, owner["org"])
    before_stranger = _side_effects(extraction_url, stranger["org"])
    response = extraction_client.get(_read(kind, owner_resources), headers=stranger["headers"])
    _hidden(response)
    assert _side_effects(extraction_url, owner["org"]) == before_owner
    assert _side_effects(extraction_url, stranger["org"]) == before_stranger
    own = extraction_client.get(
        f"/v1/workspaces/{stranger['workspace']}/extraction-runs", headers=stranger["headers"]
    )
    assert own.status_code == 200, own.text
    assert own.json()["items"] == []


FOREIGN_MUTATIONS = ("create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct")


def _mutation(action, client, resources, headers):
    tenant, fixture, source = resources["tenant"], resources["fixture"], resources["source"]
    key = str(uuid.uuid4())
    if action == "create":
        return client.post(
            f"/v1/workspaces/{tenant['workspace']}/extraction-runs",
            json=_request(tenant, source),
            headers={**headers, "Idempotency-Key": key},
        )
    if action == "cancel":
        return client.delete(
            "/v1/extraction-runs/" + fixture["run"],
            headers={**headers, "Idempotency-Key": key, "If-Match": resources["run_etag"]},
        )
    if action == "rerun":
        return client.post(
            f"/v1/extraction-runs/{fixture['run']}/rerun",
            json={"reason": "Repeat extraction"},
            headers={**headers, "Idempotency-Key": key},
        )
    if action == "correct":
        return client.post(
            f"/v1/approved-extractions/{resources['record']}/corrections",
            json=_correction_body(resources["approved"]),
            headers={
                **headers,
                "Idempotency-Key": key,
                "If-Match": resources["approved"].headers["ETag"],
            },
        )
    if action == "edit":
        body = _edit_body(fixture, source)
    elif action == "reject":
        body = command(fixture["proposal"], "reject")
    elif action == "merge":
        body = {
            "action": "merge",
            "extraction_ids": [fixture["proposal"], resources["other"]],
            "expected_versions": dict.fromkeys([fixture["proposal"], resources["other"]], 1),
            "reason": "Merge source evidence.",
            "patch": {"payload_source_id": fixture["proposal"]},
            "conflict_resolution": [
                decision(client, tenant, resources["conflict"], [fixture["proposal"]])
            ],
        }
    elif action == "accept":
        body = command(fixture["proposal"])
    else:
        raise AssertionError(action)
    return client.post(
        "/v1/extractions/review", json=body, headers={**headers, "Idempotency-Key": key}
    )


@pytest.mark.parametrize("action", FOREIGN_MUTATIONS)
def test_foreign_owner_mutations_are_hidden_404(
    extraction_client, extraction_url, owner_resources, action
):
    owner = owner_resources["tenant"]
    stranger = _foreign_owner(extraction_url)
    before_owner = _side_effects(extraction_url, owner["org"])
    before_stranger = _side_effects(extraction_url, stranger["org"])
    response = _mutation(action, extraction_client, owner_resources, stranger["headers"])
    _hidden(response)
    assert _side_effects(extraction_url, owner["org"]) == before_owner
    assert _side_effects(extraction_url, stranger["org"]) == before_stranger


DENIED = (
    ("viewer", "create"),
    ("viewer", "cancel"),
    ("viewer", "rerun"),
    ("viewer", "accept"),
    ("viewer", "edit"),
    ("viewer", "reject"),
    ("viewer", "merge"),
    ("viewer", "correct"),
    ("reviewer", "create"),
    ("reviewer", "cancel"),
    ("reviewer", "rerun"),
)


@pytest.mark.parametrize(("role", "action"), DENIED)
@pytest.mark.parametrize("claim", ["authentic", "forged_owner"])
def test_denied_actions_with_valid_bodies_are_403(
    extraction_client,
    extraction_tenant,
    extraction_url,
    waiting_review_fixture,
    source_fixture,
    role,
    action,
    claim,
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    other, group = alternative(extraction_url, tenant, fixture)
    resources = {
        "tenant": tenant,
        "fixture": fixture,
        "source": source_fixture,
        "conflict": group,
        "other": other,
        "record": None,
        "run_etag": None,
        "approved": None,
    }
    if action == "correct":
        accepted = extraction_client.post(
            "/v1/extractions/review",
            json={
                **command(fixture["proposal"]),
                "conflict_resolution": [
                    decision(extraction_client, tenant, group, [fixture["proposal"]])
                ],
            },
            headers={**tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
        )
        assert accepted.status_code == 200, accepted.text
        record_id = accepted.json()["approved_record_ids"][0]
        resources["record"] = record_id
        resources["approved"] = extraction_client.get(
            "/v1/approved-extractions/" + record_id, headers=tenant["headers"]
        )
    run = extraction_client.get("/v1/extraction-runs/" + fixture["run"], headers=tenant["headers"])
    resources["run_etag"] = run.headers["ETag"]
    _set_role(extraction_url, tenant, role)
    token_role = role if claim == "authentic" else "owner"
    before = _side_effects(extraction_url, tenant["org"])
    response = _mutation(action, extraction_client, resources, _headers(tenant, token_role))
    _forbidden(response)
    assert _side_effects(extraction_url, tenant["org"]) == before


@pytest.mark.parametrize("role", ["owner", "editor", "reviewer", "viewer"])
def test_every_role_can_read_own_extraction_resources(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, role
):
    tenant, fixture = extraction_tenant, waiting_review_fixture
    _set_role(extraction_url, tenant, role)
    headers = _headers(tenant, "owner")
    for path in (
        f"/v1/workspaces/{tenant['workspace']}/extraction-permissions",
        f"/v1/workspaces/{tenant['workspace']}/extraction-runs",
        f"/v1/extraction-runs/{fixture['run']}",
        f"/v1/extractions/{fixture['proposal']}",
        f"/v1/extraction-runs/{fixture['run']}/event-history",
    ):
        response = extraction_client.get(path, headers=headers)
        assert response.status_code == 200, response.text
    permissions = extraction_client.get(
        f"/v1/workspaces/{tenant['workspace']}/extraction-permissions", headers=headers
    ).json()["allowed_actions"]
    if role == "viewer":
        assert permissions == []
    elif role == "reviewer":
        assert permissions == ["accept", "edit", "reject", "merge", "correct"]
    else:
        assert permissions == [
            "create",
            "cancel",
            "rerun",
            "accept",
            "edit",
            "reject",
            "merge",
            "correct",
        ]
