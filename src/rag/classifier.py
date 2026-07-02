"""Rule-based query intent classifier (Phase 3.2 / 3.3).

Classifies a user query into one of five intents *before* retrieval so that
advisory / comparative / performance / out-of-scope questions never hit the
vector store or the LLM. Scheme detection is reused from the retriever.

Intents:
- ``factual``       -> answerable from the corpus (default)
- ``advisory``      -> asks for a recommendation / suitability judgement
- ``comparative``   -> asks to compare or rank schemes
- ``performance``   -> asks for returns / CAGR / performance figures
- ``out_of_scope``  -> names a fund or AMC outside the five HDFC schemes
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.rag.retriever import detect_scheme

FACTUAL = "factual"
ADVISORY = "advisory"
COMPARATIVE = "comparative"
PERFORMANCE = "performance"
OUT_OF_SCOPE = "out_of_scope"

# Advisory: user wants an opinion / recommendation / suitability judgement.
_ADVISORY_KEYWORDS: tuple[str, ...] = (
    "should i",
    "should we",
    "shall i",
    "must i",
    "recommend",
    "recommendation",
    "worth investing",
    "worth it",
    "good investment",
    "good idea to invest",
    "is it wise",
    "is it safe to invest",
    "advice",
    "advise",
    "suggest",
)

# Comparative: user wants to compare / rank funds.
_COMPARATIVE_KEYWORDS: tuple[str, ...] = (
    "vs",
    "versus",
    "compare",
    "comparison",
    "better",
    "which is better",
    "which fund",
    "difference between",
    "outperform",
)

# Performance: user wants returns / CAGR / performance figures (facts-only
# assistant does not compute or project these).
_PERFORMANCE_KEYWORDS: tuple[str, ...] = (
    "return",
    "returns",
    "cagr",
    "performance",
    "performed",
    "nav history",
    "past performance",
    "annual return",
    "annualised return",
    "annualized return",
    "trailing return",
    "rolling return",
    "last year",
)

# Competing / non-HDFC AMCs. Naming any of these puts the query out of scope
# regardless of other keywords (e.g. "SBI Bluechip" — "bluechip" would
# otherwise resolve to our Large Cap scheme).
_OTHER_AMC_KEYWORDS: tuple[str, ...] = (
    "sbi",
    "icici",
    "axis",
    "nippon",
    "kotak",
    "aditya birla",
    "absl",
    "uti",
    "dsp",
    "franklin",
    "mirae",
    "tata",
    "motilal",
    "quant",
    "parag parikh",
    "ppfas",
    "canara",
    "edelweiss",
    "invesco",
    "bandhan",
    "hsbc",
    "sundaram",
    "baroda",
    "pgim",
    "navi",
    "mahindra",
    "zerodha",
)

# HDFC fund categories that exist but are outside the five indexed schemes.
# Only treated as out-of-scope when no supported scheme is resolved.
_UNSUPPORTED_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "flexi cap",
    "flexicap",
    "multi cap",
    "multicap",
    "balanced advantage",
    "liquid fund",
    "elss",
    "tax saver",
    "index fund",
    "nifty 50",
    "sensex",
    "focused fund",
    "value fund",
    "banking and psu",
    "credit risk",
    "ultra short",
    "overnight fund",
    "dynamic bond",
    "corporate bond",
    "arbitrage",
    "hybrid fund",
)


@dataclass(frozen=True)
class Classification:
    """Query intent plus the resolved scheme (if any) and the trigger token."""

    intent: str
    scheme: str | None
    matched: str | None = None


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    """Return the first whole-word keyword found in ``text`` (else ``None``)."""
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return keyword
    return None


def classify(query: str) -> Classification:
    """Classify a user query into a single intent (see module docstring)."""
    text = query.lower()
    scheme = detect_scheme(query)

    # A named competitor AMC is unambiguously out of scope, even if a generic
    # alias like "bluechip" incidentally resolved to a supported scheme.
    other_amc = _first_keyword(text, _OTHER_AMC_KEYWORDS)
    if other_amc is not None:
        return Classification(intent=OUT_OF_SCOPE, scheme=None, matched=other_amc)

    advisory = _first_keyword(text, _ADVISORY_KEYWORDS)
    if advisory is not None:
        return Classification(intent=ADVISORY, scheme=scheme, matched=advisory)

    comparative = _first_keyword(text, _COMPARATIVE_KEYWORDS)
    if comparative is not None:
        return Classification(intent=COMPARATIVE, scheme=scheme, matched=comparative)

    performance = _first_keyword(text, _PERFORMANCE_KEYWORDS)
    if performance is not None:
        return Classification(intent=PERFORMANCE, scheme=scheme, matched=performance)

    unsupported = _first_keyword(text, _UNSUPPORTED_CATEGORY_KEYWORDS)
    if unsupported is not None and scheme is None:
        return Classification(intent=OUT_OF_SCOPE, scheme=None, matched=unsupported)

    return Classification(intent=FACTUAL, scheme=scheme)
