#!/usr/bin/env python3
"""Re-embed chunks.jsonl into Chroma without re-fetching (Phase 1.9)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.ingest.chunker import read_chunks_jsonl
from src.index.embedder import embed_passages
from src.index.vector_store import collection_count, reset_collection, upsert_chunks

logger = logging.getLogger(__name__)


def rebuild_index(
    *,
    chunks_path: Path | None = None,
    vector_db_path: Path | None = None,
) -> dict[str, int | str]:
    """Re-embed existing chunk rows and replace the vector index."""
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

    return {
        "chunks": len(chunks),
        "indexed": indexed,
        "chunks_path": str(path),
        "vector_db_path": str(vector_db_path or settings.vector_db_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the Chroma index from data/processed/chunks.jsonl.",
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        default=None,
        help=f"Input JSONL path (default: {settings.processed_data_dir / 'chunks.jsonl'}).",
    )
    parser.add_argument(
        "--vector-db-path",
        type=Path,
        default=None,
        help=f"Chroma persist directory (default: {settings.vector_db_path}).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        stats = rebuild_index(
            chunks_path=args.chunks_path,
            vector_db_path=args.vector_db_path,
        )
    except Exception:
        logger.exception("Index rebuild failed")
        return 1

    print(
        f"Done: {stats['chunks']} chunks → {stats['indexed']} vectors "
        f"({stats['vector_db_path']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
