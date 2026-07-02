"""Tests for corpus ingestion pipeline (Phase 6.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingest.chunker import SchemeEntry
from src.ingest.fetcher import scheme_slug_from_url
from src.ingest.pipeline import manifest_path, read_ingest_manifest, run_ingestion

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURES_DIR / "sample_groww.html").read_text(encoding="utf-8")

MID_CAP_ENTRY = SchemeEntry(
    scheme="HDFC Mid Cap Fund Direct Growth",
    category="mid-cap equity",
    url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
)


def _seed_raw_snapshot(raw_dir: Path) -> None:
    slug = scheme_slug_from_url(MID_CAP_ENTRY.url)
    scheme_dir = raw_dir / slug
    scheme_dir.mkdir(parents=True)
    html_path = scheme_dir / "20260701T120000Z.html"
    html_path.write_text(SAMPLE_HTML, encoding="utf-8")
    meta = {
        "url": MID_CAP_ENTRY.url,
        "scheme": MID_CAP_ENTRY.scheme,
        "fetched_at": "2026-07-01T12:00:00+00:00",
    }
    (scheme_dir / "20260701T120000Z.meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )


def test_run_ingestion_skip_fetch_builds_index_and_manifest(tmp_path: Path, monkeypatch):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    chroma_dir = tmp_path / "chroma"
    chunks_path = processed_dir / "chunks.jsonl"
    _seed_raw_snapshot(raw_dir)

    def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr("src.ingest.pipeline.embed_passages", fake_embed)

    result = run_ingestion(
        skip_fetch=True,
        raw_dir=raw_dir,
        chunks_path=chunks_path,
        vector_db_path=chroma_dir,
        processed_dir=processed_dir,
        workflow_run_id="test-run",
    )

    assert result.status == "success"
    assert result.chunk_count > 0
    assert result.indexed == result.chunk_count
    assert chunks_path.is_file()
    assert chroma_dir.exists()
    assert manifest_path(processed_dir).is_file()

    manifest = read_ingest_manifest(processed_dir)
    assert manifest is not None
    assert manifest["status"] == "success"
    assert manifest["workflow_run_id"] == "test-run"


def test_run_ingestion_failure_writes_failed_manifest(tmp_path: Path):
    processed_dir = tmp_path / "processed"
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()
    with pytest.raises(RuntimeError, match="No chunks produced"):
        run_ingestion(
            skip_fetch=True,
            raw_dir=empty_raw,
            chunks_path=processed_dir / "chunks.jsonl",
            vector_db_path=tmp_path / "chroma",
            processed_dir=processed_dir,
        )

    manifest = read_ingest_manifest(processed_dir)
    assert manifest is not None
    assert manifest["status"] == "failed"
    assert manifest["error"]
