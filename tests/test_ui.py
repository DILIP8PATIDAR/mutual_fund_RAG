"""Tests for Phase 4 Streamlit UI module."""

from ui import streamlit_app


def test_example_questions_defined():
    assert len(streamlit_app.EXAMPLE_QUESTIONS) == 4
    labels = [label for label, _ in streamlit_app.EXAMPLE_QUESTIONS]
    assert "Min SIP Large Cap" in labels
    assert "Exit load Small Cap" in labels
    assert "Benchmark Mid Cap" in labels


def test_example_questions_are_full_sentences():
    for _, question in streamlit_app.EXAMPLE_QUESTIONS:
        assert question.endswith("?")
        assert "HDFC" in question


def test_source_label_mapping():
    assert streamlit_app._source_label("https://groww.in/mutual-funds/foo") == (
        "View on Groww"
    )
    assert "AMFI" in streamlit_app._source_label(
        "https://www.amfiindia.com/investor-corner/investor-education"
    )


def test_welcome_and_disclaimer_present():
    assert "five HDFC" in streamlit_app.WELCOME_TEXT
    assert "Facts-only" in streamlit_app.DISCLAIMER
