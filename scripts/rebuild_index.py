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
from src.index.bootstrap import rebuild_index_from_chunks

logger = logging.getLogger(__name__)


def rebuild_index(
    *,
    chunks_path: Path | None = None,
    vector_db_path: Path | None = None,
) -> dict[str, int | str]:
    """Re-embed existing chunk rows and replace the vector index."""
    path = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    chunk_count = len(read_chunks_jsonl(path))
    indexed = rebuild_index_from_chunks(path, vector_db_path=vector_db_path)
    return {
        "chunks": chunk_count,
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
