"""The frozen list contract has no limit parameter until pagination is approved."""

from app.main import app


def test_runtime_does_not_declare_unpublished_list_limits() -> None:
    paths = app.openapi()["paths"]
    for route in (
        "/v1/entities/{entity_id}/documents",
        "/v1/workspaces",
        "/v1/queries/{query_id}",
    ):
        parameters = paths[route]["get"].get("parameters", [])
        assert not any(p["name"] == "limit" for p in parameters), route
