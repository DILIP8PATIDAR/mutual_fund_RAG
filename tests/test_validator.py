"""Tests for the Phase 3 response validator."""

from src.index.vector_store import SearchResult
from src.rag.generator import GeneratedAnswer
from src.rag.retriever import RetrievalOutcome
from src.rag.validator import validate

GROWW_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


def _outcome(*, with_chunk: bool = True) -> RetrievalOutcome:
    results = []
    if with_chunk:
        results = [
            SearchResult(
                chunk_id="c1",
                text="HDFC Mid Cap — Fund details",
                metadata={
                    "scheme": "HDFC Mid Cap Fund Direct Growth",
                    "section_type": "fund_details",
                    "source_url": GROWW_URL,
                    "fetched_at": "2026-07-01T12:30:04Z",
                },
                distance=0.16,
            )
        ]
    return RetrievalOutcome(
        query="expense ratio HDFC Mid Cap",
        scheme="HDFC Mid Cap Fund Direct Growth",
        section_types=("fund_details",),
        results=results,
        top_similarity=0.84,
        low_confidence=False,
    )


def _answer(text: str, *, source_url=None, last_updated=None) -> GeneratedAnswer:
    return GeneratedAnswer(
        answer=text,
        source_url=source_url,
        last_updated=last_updated,
        refused=False,
    )


def test_valid_answer_passes_unchanged():
    result = validate(
        _answer(
            "The expense ratio is 0.75%.",
            source_url=GROWW_URL,
            last_updated="2026-07-01",
        ),
        _outcome(),
    )
    assert result.valid is True
    assert result.issues == ()
    assert result.answer.answer == "The expense ratio is 0.75%."


def test_four_sentences_truncated_to_three():
    text = "One fact. Two fact. Three fact. Four fact."
    result = validate(_answer(text, source_url=GROWW_URL, last_updated="2026-07-01"), _outcome())
    assert "too_many_sentences" in result.issues
    assert result.valid is True
    assert len(result.answer.answer.split(". ")) <= 3
    assert "Four fact" not in result.answer.answer


def test_missing_url_patched_from_top_chunk():
    result = validate(_answer("The expense ratio is 0.75%."), _outcome())
    assert "missing_source_url" in result.issues
    assert result.answer.source_url == GROWW_URL
    assert result.answer.last_updated == "2026-07-01"


def test_url_stripped_from_body():
    result = validate(
        _answer(f"The expense ratio is 0.75%. See {GROWW_URL}", source_url=GROWW_URL),
        _outcome(),
    )
    assert "url_in_body" in result.issues
    assert "http" not in result.answer.answer


def test_advisory_language_is_hard_invalid():
    result = validate(
        _answer("You should invest in this fund.", source_url=GROWW_URL),
        _outcome(),
    )
    assert result.valid is False
    assert "advisory_language" in result.issues


def test_return_math_is_hard_invalid():
    result = validate(
        _answer("The CAGR is 15% and your money will grow to 2x.", source_url=GROWW_URL),
        _outcome(),
    )
    assert result.valid is False
    assert "return_math" in result.issues


def test_no_citation_expected_without_chunks():
    """Low-confidence path: no chunks means missing citation is not an issue."""
    result = validate(_answer("I don't have that information."), _outcome(with_chunk=False))
    assert "missing_source_url" not in result.issues
    assert result.valid is True
