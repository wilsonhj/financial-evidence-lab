"""Review uses real worker candidates, RLS and one atomic receipt transaction."""

import uuid

import psycopg
import pytest


def command(proposal, action="accept"):
    return {
        "action": action,
        "extraction_ids": [proposal],
        "expected_versions": {proposal: 1},
        "reason": "Checked the source.",
    }


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_atomic_review_and_exact_replay(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, action
):
    fixture = waiting_review_fixture
    headers = {**extraction_tenant["headers"], "Idempotency-Key": str(uuid.uuid4())}
    body = command(fixture["proposal"], action)
    result = extraction_client.post("/v1/extractions/review", json=body, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["proposal_states"] == {
        fixture["proposal"]: "accepted" if action == "accept" else "rejected"
    }
    assert data["proposal_versions"] == {fixture["proposal"]: 2}
    assert len(data["approved_record_ids"]) == (1 if action == "accept" else 0)
    replay = extraction_client.post("/v1/extractions/review", json=body, headers=headers)
    assert replay.content == result.content
    with psycopg.connect(extraction_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM extraction_reviews WHERE org_id=%s",
                (extraction_tenant["org"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT status FROM extraction_runs WHERE id=%s", (fixture["run"],)
            ).fetchone()[0]
            == "succeeded"
        )
        assert (
            conn.execute(
                "SELECT payload FROM extraction_proposals WHERE id=%s", (fixture["proposal"],)
            ).fetchone()[0]
            == fixture["payload"]
        )


def test_invalid_bytes_roll_back_whole_review(
    extraction_client, extraction_tenant, extraction_url, waiting_review_fixture, source_fixture
):
    fixture = waiting_review_fixture
    source_fixture["path"].write_text("changed source")
    result = extraction_client.post(
        "/v1/extractions/review",
        json=command(fixture["proposal"]),
        headers={**extraction_tenant["headers"], "Idempotency-Key": str(uuid.uuid4())},
    )
    assert result.status_code == 422, result.text
    with psycopg.connect(extraction_url) as conn:
        assert conn.execute(
            "SELECT state,version FROM extraction_proposals WHERE id=%s", (fixture["proposal"],)
        ).fetchone() == ("needs_review", 1)
        for table in (
            "extraction_reviews",
            "approved_extraction_records",
            "approved_extraction_versions",
        ):
            assert (
                conn.execute(
                    f"SELECT count(*) FROM {table} WHERE org_id=%s", (extraction_tenant["org"],)
                ).fetchone()[0]
                == 0
            )
