"""Query retriever: scheme detection, section routing, threshold (Phase 2.1–2.2).

Implements the "Retrieval strategy (Phase 2)" from ImplementationPlan.md:

1. Scheme detection via a keyword/alias map -> Chroma ``where`` filter.
2. ``query:``-prefixed BGE-small embedding + cosine search (``top_k``).
3. Soft ``section_type`` re-rank so intent-matching sections win ties.
4. Similarity threshold -> low-confidence signal when the top hit is weak
   or when no scheme could be resolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import settings
from src.index.embedder import embed_query
from src.index.vector_store import SearchResult, search

# --- Scheme detection -------------------------------------------------------
# Alias phrases are matched case-insensitively; the longest matching alias wins
# so "small cap" is not shadowed by a bare "cap". Each alias resolves to a
# fragment that must appear in a category from ``urls.json`` (keeps the map in
# sync with the corpus without hardcoding full scheme names here).
_ALIAS_TO_CATEGORY_FRAGMENT: dict[str, str] = {
    "large cap": "large-cap",
    "largecap": "large-cap",
    "large-cap": "large-cap",
    "bluechip": "large-cap",
    "blue chip": "large-cap",
    "mid cap": "mid-cap",
    "midcap": "mid-cap",
    "mid-cap": "mid-cap",
    "small cap": "small-cap",
    "smallcap": "small-cap",
    "small-cap": "small-cap",
    "gold": "gold",
    "silver": "silver",
}

# --- Section-type intent routing -------------------------------------------
# Keyword -> preferred section_type(s). Used as a soft boost, never a filter.
_INTENT_SECTION_TYPES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("expense ratio", "expense", "ter", "charges", "fee"), ("fund_details",)),
    (("exit load", "exit", "redeem", "redemption"), ("exit_load", "fund_details")),
    (
        ("minimum", "min ", "min.", "sip amount", "lump sum", "lumpsum", "how much"),
        ("minimum_investments", "fund_details"),
    ),
    (("tax", "taxed", "ltcg", "stcg", "capital gains"), ("tax",)),
    (
        ("objective", "aim", "goal", "invests in", "strategy", "invest in units"),
        ("investment_objective",),
    ),
    (("benchmark", "benchmark index", "index tracked"), ("fund_details",)),
    (("net asset value", "latest nav", "current nav"), ("nav", "fund_details")),
    (
        ("holding", "holdings", "portfolio", "top stocks", "stocks", "invested in"),
        ("holdings",),
    ),
    (("return", "returns", "cagr", "performance"), ("returns", "table")),
]


@dataclass(frozen=True)
class RetrievalOutcome:
    """Result bundle returned to the API/generator layer."""

    query: str
    scheme: str | None
    section_types: tuple[str, ...]
    results: list[SearchResult] = field(default_factory=list)
    top_similarity: float = 0.0
    low_confidence: bool = True

    @property
    def source_url(self) -> str | None:
        for result in self.results:
            url = result.metadata.get("source_url")
            if url:
                return str(url)
        return None

    @property
    def last_updated(self) -> str | None:
        """Newest ``fetched_at`` (YYYY-MM-DD) among retrieved chunks."""
        stamps = [
            str(r.metadata["fetched_at"])
            for r in self.results
            if r.metadata.get("fetched_at")
        ]
        if not stamps:
            return None
        return max(stamps)[:10]


def _load_scheme_by_category_fragment() -> dict[str, str]:
    """Map each category fragment to its scheme name from ``urls.json``."""
    from src.ingest.fetcher import load_scheme_urls

    mapping: dict[str, str] = {}
    for entry in load_scheme_urls():
        category = entry.category.lower()
        for fragment in set(_ALIAS_TO_CATEGORY_FRAGMENT.values()):
            if fragment in category:
                mapping[fragment] = entry.scheme
    return mapping


def detect_scheme(query: str) -> str | None:
    """Resolve a single scheme from the query, longest alias first.

    Returns ``None`` when no alias matches or when aliases for *different*
    schemes both appear (ambiguous / comparative — deferred to Phase 3).
    """
    text = f" {query.lower()} "
    fragment_to_scheme = _load_scheme_by_category_fragment()

    matched_fragments: set[str] = set()
    for alias in sorted(_ALIAS_TO_CATEGORY_FRAGMENT, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            matched_fragments.add(_ALIAS_TO_CATEGORY_FRAGMENT[alias])

    resolved = {
        fragment_to_scheme[f] for f in matched_fragments if f in fragment_to_scheme
    }
    if len(resolved) == 1:
        return next(iter(resolved))
    return None


def detect_section_types(query: str) -> tuple[str, ...]:
    """Preferred ``section_type`` boosts for the query intent (may be empty)."""
    text = query.lower()
    preferred: list[str] = []
    if re.search(r"\bnav\b", text) or "net asset value" in text:
        for section_type in ("nav", "fund_details"):
            if section_type not in preferred:
                preferred.append(section_type)
    for keywords, section_types in _INTENT_SECTION_TYPES:
        if any(keyword in text for keyword in keywords):
            for section_type in section_types:
                if section_type not in preferred:
                    preferred.append(section_type)
    return tuple(preferred)


def _rerank_by_section(
    results: list[SearchResult],
    section_types: tuple[str, ...],
) -> list[SearchResult]:
    """Stable soft re-rank lifting intent-matching section types to the top."""
    if not section_types:
        return results

    priority = {section_type: rank for rank, section_type in enumerate(section_types)}

    def sort_key(item: tuple[int, SearchResult]) -> tuple[int, int]:
        index, result = item
        rank = priority.get(str(result.metadata.get("section_type")), len(priority))
        return (rank, index)

    ordered = sorted(enumerate(results), key=sort_key)
    return [result for _, result in ordered]


def retrieve(
    query: str,
    *,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> RetrievalOutcome:
    """Run the Phase 2 retrieval pipeline for a single query."""
    scheme = detect_scheme(query)
    section_types = detect_section_types(query)
    k = top_k if top_k is not None else settings.top_k
    threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else settings.similarity_threshold
    )

    query_embedding = embed_query(query)
    results = search(query_embedding, top_k=k, scheme=scheme)
    results = _rerank_by_section(results, section_types)

    top_similarity = max((r.similarity for r in results), default=0.0)

    # No scheme => ambiguous across the five near-identical pages; treat as low
    # confidence even if a raw score sneaks over the threshold.
    low_confidence = (
        not results or scheme is None or top_similarity < threshold
    )

    return RetrievalOutcome(
        query=query,
        scheme=scheme,
        section_types=section_types,
        results=results,
        top_similarity=top_similarity,
        low_confidence=low_confidence,
    )
