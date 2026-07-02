"""Tests for the Phase 3 refusal handler."""

from src.rag.classifier import Classification, classify
from src.rag.generator import DISCLAIMER
from src.rag.refusal import AMFI_EDU_URL, refusal_for


def test_factual_returns_no_refusal():
    assert refusal_for(classify("expense ratio of HDFC Mid Cap")) is None


def test_advisory_refusal_links_amfi():
    answer = refusal_for(classify("Should I invest in HDFC Large Cap?"))
    assert answer is not None
    assert answer.refused is True
    assert answer.source_url == AMFI_EDU_URL
    assert answer.disclaimer == DISCLAIMER
    assert "advice" in answer.answer.lower()


def test_comparative_refusal():
    answer = refusal_for(classify("Which is better, mid cap or small cap?"))
    assert answer is not None
    assert answer.refused is True
    assert answer.source_url == AMFI_EDU_URL


def test_out_of_scope_refusal():
    answer = refusal_for(classify("What is the expense ratio of SBI Bluechip?"))
    assert answer is not None
    assert answer.refused is True
    assert answer.source_url == AMFI_EDU_URL


def test_performance_links_scheme_groww_page():
    answer = refusal_for(classify("What returns did HDFC Silver ETF give last year?"))
    assert answer is not None
    assert answer.refused is True
    assert answer.source_url is not None
    assert answer.source_url.startswith("https://groww.in/mutual-funds/")


def test_performance_without_scheme_has_no_url():
    answer = refusal_for(Classification(intent="performance", scheme=None))
    assert answer is not None
    assert answer.source_url is None
