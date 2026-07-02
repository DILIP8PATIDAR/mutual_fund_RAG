"""Tests for the FastAPI chat routes."""

import pytest
from fastapi.testclient import TestClient

import src.api.chat_service as chat_service
import src.api.main as api_main
from src.api.chat_service import ChatResponse
from src.api.main import create_app
from src.rag.generator import DISCLAIMER

GROWW_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_schemes_route_returns_five(client: TestClient):
    response = client.get("/api/schemes")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    for item in body:
        assert item["url"].startswith("https://groww.in/mutual-funds/")


def test_health_route_shape(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "status",
        "index_loaded",
        "chunk_count",
        "last_ingest_at",
        "ingest_stale",
        "ingest_status",
    }
    assert isinstance(body["index_loaded"], bool)
    assert isinstance(body["ingest_stale"], bool)


def test_chat_returns_contract(client: TestClient, monkeypatch):
    """Mocked pipeline: response matches the chat contract."""

    def fake_process_chat(message: str) -> ChatResponse:
        return ChatResponse(
            answer="The expense ratio of HDFC Mid Cap Fund is 0.75%.",
            source_url=GROWW_URL,
            last_updated="2026-07-01",
            refused=False,
        )

    monkeypatch.setattr(api_main, "process_chat", fake_process_chat)

    response = client.post("/api/chat", json={"message": "expense ratio HDFC Mid Cap"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "answer",
        "source_url",
        "last_updated",
        "disclaimer",
        "refused",
    }
    assert body["source_url"].startswith("https://groww.in/mutual-funds/")
    assert body["disclaimer"] == DISCLAIMER
    assert body["refused"] is False
    assert body["answer"].count(".") <= 3


def test_chat_guards_overlong_message(client: TestClient):
    response = client.post("/api/chat", json={"message": "x" * 501})
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert "too long" in body["answer"].lower()


def test_chat_guards_empty_message(client: TestClient):
    response = client.post("/api/chat", json={"message": " "})
    assert response.status_code == 200
    assert response.json()["refused"] is True


def test_chat_blocks_pii(client: TestClient):
    response = client.post(
        "/api/chat", json={"message": "My PAN is ABCDE1234F, HDFC Mid Cap ratio?"}
    )
    assert response.status_code == 200
    assert response.json()["refused"] is True


def _assert_no_llm(monkeypatch):
    """Ensure the refusal path never reaches retrieval or generation."""

    def boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("retrieval/generation should not run for refusals")

    monkeypatch.setattr(chat_service, "retrieve", boom)
    monkeypatch.setattr(chat_service, "generate_answer", boom)


def test_chat_refuses_advisory_without_retrieval(client: TestClient, monkeypatch):
    _assert_no_llm(monkeypatch)
    response = client.post(
        "/api/chat", json={"message": "Should I invest in HDFC Large Cap?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert "amfiindia.com" in (body["source_url"] or "")


def test_chat_refuses_comparative(client: TestClient, monkeypatch):
    _assert_no_llm(monkeypatch)
    response = client.post(
        "/api/chat", json={"message": "Which is better, mid cap or small cap?"}
    )
    assert response.json()["refused"] is True


def test_chat_out_of_scope(client: TestClient, monkeypatch):
    _assert_no_llm(monkeypatch)
    response = client.post(
        "/api/chat", json={"message": "What is the expense ratio of SBI Bluechip?"}
    )
    assert response.json()["refused"] is True


def test_chat_performance_links_groww_no_math(client: TestClient, monkeypatch):
    _assert_no_llm(monkeypatch)
    response = client.post(
        "/api/chat",
        json={"message": "What returns did HDFC Silver ETF give last year?"},
    )
    body = response.json()
    assert body["refused"] is True
    assert body["source_url"].startswith("https://groww.in/mutual-funds/")
