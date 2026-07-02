"""Corpus ingestion pipeline entrypoint (Phase 6.1)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.ingest.chunker import chunk_latest_raw_snapshots, write_chunks_jsonl
from src.ingest.fetcher import fetch_all
from src.index.embedder import embed_passages
from src.index.vector_store import collection_count, reset_collection, upsert_chunks

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "last_ingest.json"
INGEST_STALE_HOURS = 36


@dataclass
class IngestResult:
    status: str
    started_at: str
    finished_at: str
    chunk_count: int
    indexed: int
    duration_sec: float
    chunks_path: str
    vector_db_path: str
    error: str | None = None
    workflow_run_id: str | None = None

    def to_manifest(self) -> dict[str, Any]:
        return asdict(self)


def manifest_path(processed_dir: Path | None = None) -> Path:
    base = processed_dir or settings.processed_data_dir
    return base / MANIFEST_FILENAME


def read_ingest_manifest(processed_dir: Path | None = None) -> dict[str, Any] | None:
    path = manifest_path(processed_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read ingest manifest at %s", path)
        return None


def write_ingest_manifest(
    result: IngestResult,
    *,
    processed_dir: Path | None = None,
) -> Path:
    out_dir = processed_dir or settings.processed_data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(out_dir)
    path.write_text(
        json.dumps(result.to_manifest(), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_ingest_health_info(
    *,
    processed_dir: Path | None = None,
    stale_hours: int = INGEST_STALE_HOURS,
) -> dict[str, Any]:
    """Return last_ingest_at, ingest_stale, and ingest_status for /api/health."""
    manifest = read_ingest_manifest(processed_dir)
    if manifest is None:
        return {
            "last_ingest_at": None,
            "ingest_stale": True,
            "ingest_status": None,
        }

    finished_at = manifest.get("finished_at") or manifest.get("started_at")
    status = manifest.get("status")
    finished_dt = _parse_iso_timestamp(finished_at)
    ingest_stale = True
    if finished_dt is not None:
        age_hours = (datetime.now(timezone.utc) - finished_dt).total_seconds() / 3600
        ingest_stale = age_hours > stale_hours or status != "success"
    elif status != "success":
        ingest_stale = True

    return {
        "last_ingest_at": finished_at,
        "ingest_stale": ingest_stale,
        "ingest_status": status,
    }


def run_ingestion(
    *,
    skip_fetch: bool = False,
    use_playwright_fallback: bool = True,
    chunks_path: Path | None = None,
    vector_db_path: Path | None = None,
    processed_dir: Path | None = None,
    raw_dir: Path | None = None,
    workflow_run_id: str | None = None,
) -> IngestResult:
    """Run fetch → parse → chunk → embed → upsert and write last_ingest.json."""
    started_at = _utc_now_iso()
    t0 = time.monotonic()
    run_id = workflow_run_id or os.environ.get("GITHUB_RUN_ID")
    out_chunks = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    out_processed = processed_dir or settings.processed_data_dir
    out_vector = vector_db_path or settings.vector_db_path

    result = IngestResult(
        status="failed",
        started_at=started_at,
        finished_at=started_at,
        chunk_count=0,
        indexed=0,
        duration_sec=0.0,
        chunks_path=str(out_chunks),
        vector_db_path=str(out_vector),
        workflow_run_id=run_id,
    )

    try:
        if not skip_fetch:
            logger.info("Fetching five Groww scheme pages...")
            fetch_all(use_playwright_fallback=use_playwright_fallback)
        else:
            raw_base = raw_dir or settings.raw_data_dir
            logger.info("Skipping fetch; using latest snapshots under %s", raw_base)

        logger.info("Parsing and chunking raw HTML...")
        chunks = chunk_latest_raw_snapshots(raw_dir=raw_dir or settings.raw_data_dir)
        if not chunks:
            raise RuntimeError(
                f"No chunks produced from {raw_dir or settings.raw_data_dir}. "
                "Run without --skip-fetch or verify raw HTML exists."
            )

        write_chunks_jsonl(chunks, out_chunks)
        logger.info("Wrote %s chunks to %s", len(chunks), out_chunks)

        chunk_rows = [chunk.to_dict() for chunk in chunks]
        texts = [str(row["text"]) for row in chunk_rows]

        logger.info("Embedding %s passages with %s...", len(texts), settings.embedding_model)
        embeddings = embed_passages(texts)

        logger.info("Upserting into Chroma at %s...", out_vector)
        collection = reset_collection(persist_directory=out_vector)
        upsert_chunks(chunk_rows, embeddings, collection=collection)

        indexed = collection_count(collection)
        logger.info("Index ready: %s vectors in collection 'hdfc_mf_corpus'", indexed)

        finished_at = _utc_now_iso()
        result = IngestResult(
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            chunk_count=len(chunks),
            indexed=indexed,
            duration_sec=round(time.monotonic() - t0, 3),
            chunks_path=str(out_chunks),
            vector_db_path=str(out_vector),
            workflow_run_id=run_id,
        )
        write_ingest_manifest(result, processed_dir=out_processed)
        return result
    except Exception as exc:
        finished_at = _utc_now_iso()
        result = IngestResult(
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            chunk_count=result.chunk_count,
            indexed=result.indexed,
            duration_sec=round(time.monotonic() - t0, 3),
            chunks_path=str(out_chunks),
            vector_db_path=str(out_vector),
            error=str(exc),
            workflow_run_id=run_id,
        )
        write_ingest_manifest(result, processed_dir=out_processed)
        raise
