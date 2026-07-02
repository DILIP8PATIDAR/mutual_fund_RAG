"""Shared chat pipeline used by the FastAPI routes and Streamlit UI."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.rag.classifier import classify
from src.rag.generator import DISCLAIMER, GeneratedAnswer, generate_answer
from src.rag.guard import check_input
from src.rag.refusal import refusal_for
from src.rag.retriever import retrieve
from src.rag.validator import validate

logger = logging.getLogger(__name__)

VALIDATION_FALLBACK_MESSAGE = (
    "I can only share verified facts from the HDFC scheme pages, and I "
    "couldn't produce a compliant answer for that. Please check the official "
    "Groww page for the details."
)


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question")


class ChatResponse(BaseModel):
    answer: str
    source_url: str | None = None
    last_updated: str | None = None
    disclaimer: str = DISCLAIMER
    refused: bool = False


def _validation_fallback(outcome) -> GeneratedAnswer:
    return GeneratedAnswer(
        answer=VALIDATION_FALLBACK_MESSAGE,
        source_url=outcome.source_url,
        last_updated=outcome.last_updated,
        refused=False,
    )


def _to_response(generated: GeneratedAnswer) -> ChatResponse:
    return ChatResponse(
        answer=generated.answer,
        source_url=generated.source_url,
        last_updated=generated.last_updated,
        disclaimer=generated.disclaimer,
        refused=generated.refused,
    )


def process_chat(message: str) -> ChatResponse:
    """Run the full guard -> classify -> (refuse | retrieve -> generate -> validate) pipeline."""
    guard = check_input(message)
    if not guard.ok:
        logger.info("guard blocked request: pii_types=%s", guard.pii_types)
        return ChatResponse(answer=guard.message, refused=True)

    classification = classify(message)
    logger.info(
        "classify: intent=%s scheme=%s matched=%s",
        classification.intent,
        classification.scheme,
        classification.matched,
    )

    refusal = refusal_for(classification)
    if refusal is not None:
        return _to_response(refusal)

    outcome = retrieve(message)
    logger.info(
        "chat: scheme=%s section_types=%s top_sim=%.3f low_conf=%s chunks=%s",
        outcome.scheme,
        outcome.section_types,
        outcome.top_similarity,
        outcome.low_confidence,
        [r.chunk_id for r in outcome.results],
    )

    generated = generate_answer(outcome)
    result = validate(generated, outcome)
    if not result.valid:
        logger.info("validator failed %s; regenerating once", result.issues)
        result = validate(generate_answer(outcome), outcome)
        if not result.valid:
            logger.warning("validator still failing %s; using fallback", result.issues)
            return _to_response(_validation_fallback(outcome))

    return _to_response(result.answer)
