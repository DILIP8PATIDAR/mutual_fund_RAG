"""Tests for the Phase 2 retriever: scheme detection, routing, threshold."""

import pytest

from src.index.vector_store import SearchResult, collection_count
from src.rag.retriever import (
    detect_scheme,
    detect_section_types,
    retrieve,
    _rerank_by_section,
)


def _result(section_type: str, distance: float = 0.2) -> SearchResult:
    return SearchResult(
        chunk_id=f"id-{section_type}",
        text=f"chunk {section_type}",
        metadata={"section_type": section_type, "source_url": "u", "fetched_at": "x"},
        distance=distance,
    )


def test_detect_scheme_resolves_single_scheme():
    assert detect_scheme("expense ratio of HDFC Mid Cap") == (
        "HDFC Mid Cap Fund Direct Growth"
    )
    assert detect_scheme("minimum SIP for large cap fund") == (
        "HDFC Large Cap Fund Direct Growth"
    )
    assert detect_scheme("exit load on HDFC small cap") == (
        "HDFC Small Cap Fund Direct Growth"
    )
    assert detect_scheme("tax on HDFC Gold ETF FOF") == (
        "HDFC Gold ETF Fund of Fund Direct Plan Growth"
    )
    assert detect_scheme("HDFC Silver ETF objective") == (
        "HDFC Silver ETF FOF Direct Growth"
    )


def test_detect_scheme_ambiguous_or_missing_returns_none():
    assert detect_scheme("which is better, large cap or mid cap?") is None
    assert detect_scheme("what is the expense ratio?") is None
    assert detect_scheme("tell me about mutual funds") is None


def test_detect_section_types_intents():
    assert detect_section_types("what is the expense ratio") == ("fund_details",)
    assert detect_section_types("exit load details") == ("exit_load", "fund_details")
    assert detect_section_types("top holdings of the fund") == ("holdings",)
    assert detect_section_types("tax implication") == ("tax",)
    assert detect_section_types("what is the benchmark") == ("fund_details",)
    assert detect_section_types("random question") == ()


def test_rerank_lifts_intent_section_to_top():
    results = [_result("fund_details"), _result("holdings"), _result("tax")]
    reranked = _rerank_by_section(results, ("holdings",))
    assert reranked[0].metadata["section_type"] == "holdings"
    # non-matching order is preserved (stable) after the boosted item
    assert [r.metadata["section_type"] for r in reranked[1:]] == [
        "fund_details",
        "tax",
    ]


def test_rerank_noop_without_section_types():
    results = [_result("fund_details"), _result("holdings")]
    assert _rerank_by_section(results, ()) == results


@pytest.mark.integration
def test_retrieve_live_expense_ratio():
    """Requires a built Chroma index (run build_corpus.py first)."""
    if collection_count() == 0:
        pytest.skip("Empty index; run scripts/build_corpus.py --skip-fetch first")

    outcome = retrieve("What is the expense ratio of HDFC Mid Cap Fund?")
    assert outcome.scheme == "HDFC Mid Cap Fund Direct Growth"
    assert not outcome.low_confidence
    assert outcome.results
    assert all(
        r.metadata["scheme"] == "HDFC Mid Cap Fund Direct Growth"
        for r in outcome.results
    )
    assert outcome.results[0].metadata["section_type"] in {"fund_details", "exit_load"}
    assert outcome.source_url.startswith("https://groww.in/mutual-funds/")


@pytest.mark.integration
def test_retrieve_no_scheme_is_low_confidence():
    """A query with no resolvable scheme must be flagged low-confidence."""
    if collection_count() == 0:
        pytest.skip("Empty index; run scripts/build_corpus.py --skip-fetch first")

    outcome = retrieve("What is the expense ratio?")
    assert outcome.scheme is None
    assert outcome.low_confidence
