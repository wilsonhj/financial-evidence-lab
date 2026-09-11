"""ADR-0021 explicit pagination preserves legacy response shapes."""

from pathlib import Path

import yaml

CONTRACT = Path(__file__).resolve().parents[3] / "packages/contracts/openapi/openapi.yaml"


def test_pagination_contract_is_explicit_and_preserves_arrays() -> None:
    spec = yaml.safe_load(CONTRACT.read_text())
    for route in ("/v1/workspaces", "/v1/entities/{entityId}/documents", "/v1/queries/{queryId}"):
        operation = spec["paths"][route]["get"]
        refs = {p.get("$ref") for p in operation["parameters"]}
        assert {
            "#/components/parameters/PageLimit",
            "#/components/parameters/PageCursor",
            "#/components/parameters/PageOrder",
        } <= refs
        assert {"409", "422"} <= operation["responses"].keys()
        assert {"X-FEL-Next-Cursor", "X-FEL-Previous-Cursor", "X-FEL-Page-Limit"} <= operation[
            "responses"
        ]["200"]["headers"].keys()
    for route in ("/v1/workspaces", "/v1/entities/{entityId}/documents"):
        assert (
            spec["paths"][route]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["type"]
            == "array"
        )


def test_bounded_evidence_contracts_are_declared() -> None:
    spec = yaml.safe_load(CONTRACT.read_text())
    assert spec["info"]["version"] == "0.7.0"
    assert "/v1/document-versions/resolve" in spec["paths"]
    assert "/v1/retrieval-runs/{runId}/event-history" in spec["paths"]
    reader = spec["paths"]["/v1/documents/{documentId}/reader"]["get"]
    assert {"sibling_limit", "sibling_cursor", "sibling_order", "include_siblings"} <= {
        p.get("name") for p in reader["parameters"]
    }
    assert "413" in reader["responses"]
    assert "sibling_page" in spec["components"]["schemas"]["ReaderResponse"]["properties"]
