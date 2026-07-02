"""Tests for the Phase 3 rule-based query classifier."""

from src.rag.classifier import (
    ADVISORY,
    COMPARATIVE,
    FACTUAL,
    OUT_OF_SCOPE,
    PERFORMANCE,
    classify,
)


def test_factual_default():
    result = classify("What is the expense ratio of HDFC Mid Cap Fund?")
    assert result.intent == FACTUAL
    assert result.scheme == "HDFC Mid Cap Fund Direct Growth"


def test_factual_benchmark_is_not_performance():
    assert classify("What is the benchmark for HDFC Mid Cap Fund?").intent == FACTUAL


def test_advisory_intent():
    assert classify("Should I invest in HDFC Large Cap?").intent == ADVISORY
    assert classify("Would you recommend HDFC Mid Cap?").intent == ADVISORY
    assert classify("Is HDFC Small Cap worth investing in?").intent == ADVISORY


def test_comparative_intent():
    assert classify("Which is better, mid cap or small cap?").intent == COMPARATIVE
    assert classify("Compare HDFC Large Cap and Mid Cap").intent == COMPARATIVE
    assert classify("HDFC mid cap vs small cap").intent == COMPARATIVE


def test_performance_intent():
    assert classify("What returns did HDFC Silver ETF give last year?").intent == (
        PERFORMANCE
    )
    assert classify("What is the CAGR of HDFC Mid Cap?").intent == PERFORMANCE
    assert classify("Show me HDFC Large Cap performance").intent == PERFORMANCE


def test_out_of_scope_competitor_amc():
    result = classify("What is the expense ratio of SBI Bluechip?")
    assert result.intent == OUT_OF_SCOPE
    # "bluechip" must not leak a supported scheme when another AMC is named.
    assert result.scheme is None


def test_out_of_scope_unsupported_hdfc_category():
    assert classify("expense ratio of HDFC Flexi Cap Fund").intent == OUT_OF_SCOPE


def test_advisory_takes_precedence_over_scheme():
    result = classify("Should I buy HDFC Gold ETF FOF?")
    assert result.intent == ADVISORY
