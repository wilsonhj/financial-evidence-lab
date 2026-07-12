"""Smoke test for the API health contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "fel-api"
    assert body["version"] == __version__
