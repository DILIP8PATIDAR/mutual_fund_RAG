"""Phase 5 end-to-end API integration tests (indexed corpus required)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.index.vector_store import collection_count
from tests.eval_helpers import assert_eval_expectation, load_eval_queries


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.integration
def test_api_health_with_index(client: TestClient):
    if collection_count() == 0:
        pytest.skip("Empty index; run scripts/build_corpus.py --skip-fetch first")

    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["index_loaded"] is True
    assert body["chunk_count"] >= 55


@pytest.mark.integration
@pytest.mark.parametrize("case", load_eval_queries(), ids=lambda row: row["id"])
def test_api_chat_eval_set(client: TestClient, case: dict):
    """POST /api/chat for every evaluation query in the fixture."""
    if case["category"] == "factual" and collection_count() == 0:
        pytest.skip("Empty index; run scripts/build_corpus.py --skip-fetch first")

    response = client.post("/api/chat", json={"message": case["query"]})
    assert response.status_code == 200
    from src.api.chat_service import ChatResponse

    chat = ChatResponse.model_validate(response.json())
    assert_eval_expectation(chat, case["expect"])
