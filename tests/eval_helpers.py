"""Load and assert against the Phase 5 evaluation query fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.api.chat_service import ChatResponse

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_queries.json"


def load_eval_queries() -> list[dict[str, Any]]:
    """Return evaluation rows from ``tests/fixtures/sample_queries.json``."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def assert_eval_expectation(response: ChatResponse, expect: dict[str, Any]) -> None:
    """Raise ``AssertionError`` when a response does not match ``expect``."""
    if "refused" in expect:
        assert response.refused is expect["refused"], (
            f"refused={response.refused}, expected {expect['refused']}"
        )

    if expect.get("source_url_absent"):
        assert response.source_url is None, f"expected no source_url, got {response.source_url}"

    if source_contains := expect.get("source_url_contains"):
        assert response.source_url is not None, "expected source_url to be set"
        assert source_contains in response.source_url, (
            f"source_url {response.source_url!r} missing {source_contains!r}"
        )

    if expect.get("last_updated_required"):
        assert response.last_updated is not None, "expected last_updated to be set"

    answer_lower = response.answer.lower()

    if phrases := expect.get("answer_contains_any"):
        assert any(phrase.lower() in answer_lower for phrase in phrases), (
            f"answer missing any of {phrases!r}: {response.answer!r}"
        )

    for phrase in expect.get("answer_not_contains", ()):
        assert phrase.lower() not in answer_lower, (
            f"answer must not contain {phrase!r}: {response.answer!r}"
        )
