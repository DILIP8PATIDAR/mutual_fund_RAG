"""Refusal handler: templated responses for non-factual intents (Phase 3.4/3.5).

Turns a :class:`~src.rag.classifier.Classification` into a ready-to-return
:class:`~src.rag.generator.GeneratedAnswer` without touching retrieval or the
LLM. Advisory / comparative / out-of-scope refusals link to AMFI's investor
education resources (not the corpus); the performance path links to the
scheme's own Groww page so users can view historical returns there.
"""

from __future__ import annotations

from src.ingest.fetcher import load_scheme_urls
from src.rag.classifier import (
    ADVISORY,
    COMPARATIVE,
    OUT_OF_SCOPE,
    PERFORMANCE,
    Classification,
)
from src.rag.generator import DISCLAIMER, GeneratedAnswer

# AMFI investor education (educational, not part of the ingested corpus).
AMFI_EDU_URL = "https://www.amfiindia.com/investor-corner/investor-education"

SUPPORTED_SCHEMES_HINT = (
    "HDFC Large Cap, Mid Cap, Small Cap, Gold ETF FOF, and Silver ETF FOF"
)

ADVISORY_MESSAGE = (
    "I can share factual information from the HDFC scheme pages, but I can't "
    "give investment advice or recommendations. Whether a fund suits you "
    "depends on your goals and risk profile, so please consult a "
    "SEBI-registered adviser or explore AMFI's investor education resources."
)

COMPARATIVE_MESSAGE = (
    "I can't say which fund is better or compare schemes, as that would be "
    "investment advice. I can share individual facts, like the expense ratio "
    "or exit load, for one HDFC scheme at a time."
)

OUT_OF_SCOPE_MESSAGE = (
    f"I can only answer factual questions about five HDFC schemes: "
    f"{SUPPORTED_SCHEMES_HINT}. I don't have information about that fund. "
    "For general fund information, see AMFI's investor education resources."
)

PERFORMANCE_MESSAGE = (
    "I don't provide returns, CAGR, or performance figures, and I can't "
    "project future value. You can view the scheme's historical returns "
    "directly on its official Groww page."
)


def _scheme_url(scheme: str | None) -> str | None:
    """Look up the Groww URL for a resolved scheme name from ``urls.json``."""
    if not scheme:
        return None
    for entry in load_scheme_urls():
        if entry.scheme == scheme:
            return entry.url
    return None


def refusal_for(classification: Classification) -> GeneratedAnswer | None:
    """Build a refusal answer for non-factual intents; ``None`` for factual."""
    intent = classification.intent

    if intent == ADVISORY:
        return GeneratedAnswer(
            answer=ADVISORY_MESSAGE,
            source_url=AMFI_EDU_URL,
            last_updated=None,
            disclaimer=DISCLAIMER,
            refused=True,
        )

    if intent == COMPARATIVE:
        return GeneratedAnswer(
            answer=COMPARATIVE_MESSAGE,
            source_url=AMFI_EDU_URL,
            last_updated=None,
            disclaimer=DISCLAIMER,
            refused=True,
        )

    if intent == OUT_OF_SCOPE:
        return GeneratedAnswer(
            answer=OUT_OF_SCOPE_MESSAGE,
            source_url=AMFI_EDU_URL,
            last_updated=None,
            disclaimer=DISCLAIMER,
            refused=True,
        )

    if intent == PERFORMANCE:
        return GeneratedAnswer(
            answer=PERFORMANCE_MESSAGE,
            source_url=_scheme_url(classification.scheme),
            last_updated=None,
            disclaimer=DISCLAIMER,
            refused=True,
        )

    return None
