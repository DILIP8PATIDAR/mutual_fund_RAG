"""Tests for API root route (no static HTML UI)."""

from fastapi.testclient import TestClient

from src.api.main import create_app


def test_root_returns_api_info():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "Mutual Fund FAQ Assistant API"
    assert "streamlit" in body["ui"]
    assert "Facts-only" in body["disclaimer"]
