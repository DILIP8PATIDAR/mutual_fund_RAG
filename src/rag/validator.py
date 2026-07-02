"""Response validator: post-generation facts-only checks (Phase 3.6).

Validates a generated factual answer against the response contract and applies
cheap deterministic fixes where possible:

Auto-fixed (answer stays ``valid``):
- URLs leaking into the answer body (citation is a separate field) -> stripped.
- More than three sentences -> truncated to the first three.
- Missing ``source_url`` / ``last_updated`` -> patched from the top chunk.

Hard failures (``valid=False`` -> caller regenerates once, then falls back):
- Advisory / recommendation language.
- Return / CAGR math or projections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from src.rag.generator import GeneratedAnswer
from src.rag.retriever import RetrievalOutcome

MAX_SENTENCES = 3

_URL_RE = re.compile(r"https?://\S+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Advisory / recommendation language that must never appear in a factual answer.
_ADVISORY_RE = re.compile(
    r"\b("
    r"you should|i recommend|we recommend|i'd recommend|i suggest|we suggest|"
    r"you must invest|is a good investment|good investment for you|"
    r"better option|better choice|worth investing|ideal for you|advise you|"
    r"my advice"
    r")\b",
    re.IGNORECASE,
)

# Computed / projected returns — the assistant states facts, never math.
_RETURN_MATH_RE = re.compile(
    r"\b("
    r"cagr|compound annual|annualis?ed return|will grow to|would grow to|"
    r"projected to|expected to return|future value|your returns would"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationResult:
    """A (possibly fixed) answer plus validity and the list of issues found."""

    answer: GeneratedAnswer
    valid: bool
    issues: tuple[str, ...]


def _split_sentences(text: str) -> list[str]:
    """Split into sentences on ``. ! ?`` boundaries, ignoring in-number dots."""
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip()) if part.strip()]


def _truncate_sentences(text: str, limit: int = MAX_SENTENCES) -> tuple[str, bool]:
    """Return ``(text, was_truncated)`` keeping at most ``limit`` sentences."""
    parts = _split_sentences(text)
    if len(parts) <= limit:
        return text, False
    return " ".join(parts[:limit]), True


def validate(generated: GeneratedAnswer, outcome: RetrievalOutcome) -> ValidationResult:
    """Validate and lightly repair a generated answer against the contract."""
    issues: list[str] = []
    answer_text = generated.answer
    source_url = generated.source_url
    last_updated = generated.last_updated

    # 1. Strip any URL that leaked into the answer body (citation is separate).
    if _URL_RE.search(answer_text):
        answer_text = _URL_RE.sub("", answer_text)
        answer_text = re.sub(r"\s{2,}", " ", answer_text).strip()
        issues.append("url_in_body")

    # 2. Enforce the three-sentence ceiling.
    truncated, was_truncated = _truncate_sentences(answer_text)
    if was_truncated:
        answer_text = truncated
        issues.append("too_many_sentences")

    # 3. Patch citation metadata from the top retrieved chunk when missing.
    #    Only expected when retrieval actually returned chunks (not for the
    #    low-confidence path, which legitimately has no citation).
    expected_url = outcome.source_url
    if source_url is None and expected_url is not None:
        source_url = expected_url
        issues.append("missing_source_url")

    expected_updated = outcome.last_updated
    if last_updated is None and expected_updated is not None:
        last_updated = expected_updated
        issues.append("missing_footer")

    # 4. Hard failures: advisory language or return math cannot be auto-fixed.
    hard_invalid = False
    if _ADVISORY_RE.search(answer_text):
        issues.append("advisory_language")
        hard_invalid = True
    if _RETURN_MATH_RE.search(answer_text):
        issues.append("return_math")
        hard_invalid = True

    fixed = replace(
        generated,
        answer=answer_text,
        source_url=source_url,
        last_updated=last_updated,
    )
    return ValidationResult(answer=fixed, valid=not hard_invalid, issues=tuple(issues))
