"""Bootstrap the Chroma index when missing (e.g. Streamlit Cloud deploys)."""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings
from src.ingest.chunker import read_chunks_jsonl
from src.index.embedder import embed_passages
from src.index.vector_store import (
    collection_count,
    get_collection,
    reset_collection,
    upsert_chunks,
)

logger = logging.getLogger(__name__)


def _has_nav_chunks() -> bool:
    try:
        nav_ids = get_collection().get(
            where={"section_type": "nav"},
            include=[],
        )["ids"]
        return bool(nav_ids)
    except Exception:
        return False


def rebuild_index_from_chunks(
    chunks_path: Path | None = None,
    *,
    vector_db_path: Path | None = None,
) -> int:
    """Embed chunk rows from JSONL and replace the vector index."""
    path = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/build_corpus.py first."
        )

    chunks = read_chunks_jsonl(path)
    if not chunks:
        raise RuntimeError(f"No chunk rows found in {path}")

    texts = [str(row["text"]) for row in chunks]
    logger.info(
        "Re-embedding %s chunks from %s with %s...",
        len(texts),
        path,
        settings.embedding_model,
    )
    embeddings = embed_passages(texts)

    collection = reset_collection(persist_directory=vector_db_path)
    upsert_chunks(chunks, embeddings, collection=collection)
    indexed = collection_count(collection)
    logger.info("Rebuilt index: %s vectors in collection 'hdfc_mf_corpus'", indexed)
    return indexed


def ensure_search_index() -> int:
    """Return chunk count, building the index from JSONL when absent."""
    try:
        count = collection_count()
        if count > 0 and _has_nav_chunks():
            return count
    except Exception:
        logger.exception("Could not read existing vector index")

    chunks_path = settings.processed_data_dir / "chunks.jsonl"
    if chunks_path.is_file():
        return rebuild_index_from_chunks(chunks_path)

    # Last resort: fetch Groww pages over the network (no Playwright on cloud hosts).
    from src.ingest.pipeline import run_ingestion

    logger.warning(
        "chunks.jsonl missing; running full ingestion fetch for empty deploy."
    )
    result = run_ingestion(skip_fetch=False, use_playwright_fallback=False)
    return result.indexed
