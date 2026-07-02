"""Answer generator: facts-only Groq completion + citation (Phase 2.3–2.4).

The generator is deliberately thin: it turns retrieved chunks into a short,
cited, facts-only answer. Safety classification/validation is added in Phase 3;
here we only enforce the generation contract via the system prompt and a small
deterministic assembly of the response fields.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from src.config import settings
from src.rag.retriever import RetrievalOutcome

if TYPE_CHECKING:
    from groq import Groq

logger = logging.getLogger(__name__)

DISCLAIMER = "Facts-only. No investment advice."

LOW_CONFIDENCE_MESSAGE = (
    "I don't have enough information from the HDFC scheme pages to answer that. "
    "Try naming one of the supported schemes (for example, HDFC Mid Cap Fund) "
    "and ask about a specific fact like NAV, expense ratio, exit load, or minimum SIP."
)

MISSING_KEY_MESSAGE = (
    "The assistant is not fully configured: set GROQ_API_KEY in your .env to "
    "enable answer generation. Retrieval is working and returned relevant "
    "source chunks."
)

RATE_LIMIT_MESSAGE = (
    "The assistant is briefly rate-limited by the language model provider. "
    "Please wait a few seconds and ask again."
)

LLM_UNAVAILABLE_MESSAGE = (
    "The language model is temporarily unavailable. Please try again shortly."
)

SYSTEM_PROMPT = (
    "You are a factual assistant for five HDFC mutual fund scheme pages from "
    "Groww. Answer ONLY using the provided context. Follow these rules "
    "strictly:\n"
    "1. State only facts found in the context. If the context does not contain "
    "the answer, say you don't have that information.\n"
    "2. Keep the answer to at most 3 short sentences.\n"
    "3. Do NOT give investment advice, opinions, recommendations, or "
    "predictions. Never say whether to buy, sell, or hold.\n"
    "4. Do NOT compute or project returns, CAGR, or future value.\n"
    "5. Do NOT include any URL in the answer body; the citation is added "
    "separately.\n"
    "6. Be precise with numbers (expense ratio, exit load, minimum amounts, "
    "tax rates) exactly as they appear in the context."
)


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    source_url: str | None
    last_updated: str | None
    disclaimer: str = DISCLAIMER
    refused: bool = False


def _build_context(outcome: RetrievalOutcome, *, max_chunks: int = 5) -> str:
    """Assemble context, capped by a char budget to bound tokens-per-request.

    Keeping the prompt small protects the Groq free-tier TPM (12K tok/min) and
    TPD (100K tok/day) limits: the highest-ranked chunks are included first and
    lower-ranked chunks are dropped once the budget is reached.
    """
    budget = settings.llm_context_char_budget
    blocks: list[str] = []
    used = 0
    for result in outcome.results[:max_chunks]:
        section = result.metadata.get("section_type", "")
        block = f"[{section}] {result.text}"
        if blocks and used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _build_user_prompt(query: str, context: str) -> str:
    return (
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        "Answer using only the context above, in at most 3 sentences."
    )


@lru_cache
def _get_groq_client() -> "Groq":
    """Cached Groq client.

    ``max_retries`` lets the SDK automatically retry HTTP 429 / 5xx responses
    with exponential backoff, honouring the ``Retry-After`` header Groq sends
    when a rate limit (RPM/TPM) is hit.
    """
    from groq import Groq

    return Groq(
        api_key=settings.groq_api_key,
        max_retries=settings.groq_max_retries,
        timeout=settings.groq_timeout_sec,
    )


def _call_groq(system_prompt: str, user_prompt: str) -> str:
    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def generate_answer(outcome: RetrievalOutcome) -> GeneratedAnswer:
    """Produce a cited, facts-only answer from a retrieval outcome."""
    if outcome.low_confidence or not outcome.results:
        return GeneratedAnswer(
            answer=LOW_CONFIDENCE_MESSAGE,
            source_url=None,
            last_updated=None,
            refused=False,
        )

    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not set; returning configuration message.")
        return GeneratedAnswer(
            answer=MISSING_KEY_MESSAGE,
            source_url=outcome.source_url,
            last_updated=outcome.last_updated,
            refused=False,
        )

    context = _build_context(outcome)
    user_prompt = _build_user_prompt(outcome.query, context)

    from groq import APIError, APIConnectionError, RateLimitError

    try:
        answer_text = _call_groq(SYSTEM_PROMPT, user_prompt)
    except RateLimitError:
        # Raised only after the SDK exhausts its automatic backoff retries.
        logger.warning("Groq rate limit hit after retries; returning fallback.")
        return GeneratedAnswer(
            answer=RATE_LIMIT_MESSAGE,
            source_url=outcome.source_url,
            last_updated=outcome.last_updated,
            refused=False,
        )
    except (APIConnectionError, APIError):
        logger.exception("Groq generation failed")
        return GeneratedAnswer(
            answer=LLM_UNAVAILABLE_MESSAGE,
            source_url=outcome.source_url,
            last_updated=outcome.last_updated,
            refused=False,
        )

    if not answer_text:
        answer_text = LOW_CONFIDENCE_MESSAGE

    return GeneratedAnswer(
        answer=answer_text,
        source_url=outcome.source_url,
        last_updated=outcome.last_updated,
        refused=False,
    )
