"""BGE embedder with query/passage prefixes (Phase 1.6)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import settings

Mode = Literal["query", "passage"]

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    """Load the sentence-transformers model once per process."""
    return SentenceTransformer(settings.embedding_model)


def prefix_text(text: str, mode: Mode) -> str:
    """Apply BGE instruction prefix without double-prefixing."""
    prefix = QUERY_PREFIX if mode == "query" else PASSAGE_PREFIX
    stripped = text.strip()
    if stripped.startswith(QUERY_PREFIX) or stripped.startswith(PASSAGE_PREFIX):
        return stripped
    return f"{prefix}{stripped}"


def embed_texts(
    texts: list[str],
    *,
    mode: Mode = "passage",
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed a batch of texts with L2-normalized vectors."""
    if not texts:
        return []

    model = get_embedding_model()
    prefixed = [prefix_text(text, mode) for text in texts]
    vectors = model.encode(
        prefixed,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 50,
    )
    return np.asarray(vectors, dtype=np.float32).tolist()


def embed_query(query: str) -> list[float]:
    """Embed a user query (retrieval time)."""
    return embed_texts([query], mode="query")[0]


def embed_passages(passages: list[str], *, batch_size: int = 32) -> list[list[float]]:
    """Embed corpus chunks at index time."""
    return embed_texts(passages, mode="passage", batch_size=batch_size)
