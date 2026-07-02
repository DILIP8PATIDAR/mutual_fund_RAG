"""Phase 5 evaluation tests against ``tests/fixtures/sample_queries.json``."""

from __future__ import annotations

import pytest

from src.api.chat_service import process_chat
from src.index.vector_store import collection_count
from tests.eval_helpers import assert_eval_expectation, load_eval_queries

SAFETY_CATEGORIES = {"advisory", "comparative", "performance", "out_of_scope", "pii"}
RETRIEVAL_CATEGORIES = {"factual"}


@pytest.fixture(scope="module")
def eval_queries():
    return load_eval_queries()


@pytest.mark.parametrize(
    "case",
    [row for row in load_eval_queries() if row["category"] in SAFETY_CATEGORIES],
    ids=lambda row: row["id"],
)
def test_eval_safety_queries(case: dict):
    """Safety-path queries never need retrieval or an LLM key."""
    response = process_chat(case["query"])
    assert_eval_expectation(response, case["expect"])


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    [row for row in load_eval_queries() if row["category"] in RETRIEVAL_CATEGORIES],
    ids=lambda row: row["id"],
)
def test_eval_factual_queries(case: dict):
    """Factual queries require a built Chroma index and embedding model."""
    if collection_count() == 0:
        pytest.skip("Empty index; run scripts/build_corpus.py --skip-fetch first")

    response = process_chat(case["query"])
    assert_eval_expectation(response, case["expect"])


@pytest.mark.integration
def test_eval_fixture_has_eight_cases(eval_queries):
    assert len(eval_queries) == 8
    assert {row["category"] for row in eval_queries} == SAFETY_CATEGORIES | RETRIEVAL_CATEGORIES
