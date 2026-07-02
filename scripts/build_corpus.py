#!/usr/bin/env python3
"""Build corpus: fetch → parse → chunk → embed → index (Phase 1.8 / 6.2)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.ingest.pipeline import run_ingestion

logger = logging.getLogger(__name__)


def build_corpus(
    *,
    skip_fetch: bool = False,
    use_playwright_fallback: bool = True,
    chunks_path: Path | None = None,
    vector_db_path: Path | None = None,
) -> dict[str, int | str]:
    """Run the full corpus pipeline and return summary stats."""
    result = run_ingestion(
        skip_fetch=skip_fetch,
        use_playwright_fallback=use_playwright_fallback,
        chunks_path=chunks_path,
        vector_db_path=vector_db_path,
    )
    return {
        "chunks": result.chunk_count,
        "indexed": result.indexed,
        "chunks_path": result.chunks_path,
        "vector_db_path": result.vector_db_path,
        "status": result.status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Groww pages, chunk, embed, and build the Chroma index.",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Reuse latest HTML under data/raw/ (no network fetch).",
    )
    parser.add_argument(
        "--no-playwright",
        action="store_true",
        help="Disable Playwright fallback when fetching sparse HTML.",
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        default=None,
        help=f"Output JSONL path (default: {settings.processed_data_dir / 'chunks.jsonl'}).",
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
        stats = build_corpus(
            skip_fetch=args.skip_fetch,
            use_playwright_fallback=not args.no_playwright,
            chunks_path=args.chunks_path,
            vector_db_path=args.vector_db_path,
        )
    except Exception:
        logger.exception("Corpus build failed")
        return 1

    print(
        f"Done: {stats['chunks']} chunks → {stats['indexed']} vectors "
        f"({stats['chunks_path']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
