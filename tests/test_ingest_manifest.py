"""Tests for ingest manifest helpers (Phase 6.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ingest.pipeline import (
    IngestResult,
    get_ingest_health_info,
    manifest_path,
    nav_summary_from_chunks,
    read_ingest_manifest,
    write_ingest_manifest,
)
from src.ingest.chunker import Chunk


def test_manifest_path_under_processed_dir(tmp_path: Path):
    assert manifest_path(tmp_path) == tmp_path / "last_ingest.json"


def test_write_and_read_manifest(tmp_path: Path):
    started = "2026-07-01T00:00:00+00:00"
    finished = "2026-07-01T00:05:00+00:00"
    result = IngestResult(
        status="success",
        started_at=started,
        finished_at=finished,
        chunk_count=62,
        indexed=62,
        duration_sec=300.0,
        chunks_path=str(tmp_path / "chunks.jsonl"),
        vector_db_path=str(tmp_path / "chroma"),
        workflow_run_id="12345",
    )
    write_ingest_manifest(result, processed_dir=tmp_path)
    loaded = read_ingest_manifest(tmp_path)
    assert loaded is not None
    assert loaded["status"] == "success"
    assert loaded["chunk_count"] == 62
    assert loaded["workflow_run_id"] == "12345"
    assert loaded["finished_at"] >= loaded["started_at"]


def test_get_ingest_health_info_includes_nav_snapshots(tmp_path: Path):
    finished = datetime.now(timezone.utc).isoformat()
    write_ingest_manifest(
        IngestResult(
            status="success",
            started_at=finished,
            finished_at=finished,
            chunk_count=1,
            indexed=1,
            duration_sec=1.0,
            chunks_path=str(tmp_path / "chunks.jsonl"),
            vector_db_path=str(tmp_path / "chroma"),
            nav_snapshots={
                "HDFC Large Cap Fund Direct Growth": "NAV ₹1228.50 (as on 02-Jul-2026)"
            },
        ),
        processed_dir=tmp_path,
    )
    info = get_ingest_health_info(processed_dir=tmp_path)
    assert "HDFC Large Cap Fund Direct Growth" in info["nav_snapshots"]


def test_nav_summary_from_chunks():
    chunks = [
        Chunk(
            chunk_id="abc",
            scheme="HDFC Large Cap Fund Direct Growth",
            category="large-cap equity",
            source_url="https://example.com",
            doc_type="scheme_page",
            section_title="NAV",
            section_type="nav",
            chunk_index=0,
            fetched_at="2026-07-03T00:00:00+00:00",
            text="HDFC Large Cap Fund Direct Growth — NAV:\nNAV ₹1228.50 (as on 02-Jul-2026)",
        )
    ]
    summary = nav_summary_from_chunks(chunks)
    assert summary["HDFC Large Cap Fund Direct Growth"] == "NAV ₹1228.50 (as on 02-Jul-2026)"


def test_get_ingest_health_info_missing_manifest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "src.ingest.pipeline.settings.processed_data_dir",
        tmp_path,
    )
    info = get_ingest_health_info(processed_dir=tmp_path)
    assert info["last_ingest_at"] is None
    assert info["ingest_stale"] is True
    assert info["ingest_status"] is None


def test_get_ingest_health_info_fresh_success(tmp_path: Path):
    finished = datetime.now(timezone.utc).isoformat()
    write_ingest_manifest(
        IngestResult(
            status="success",
            started_at=finished,
            finished_at=finished,
            chunk_count=10,
            indexed=10,
            duration_sec=1.0,
            chunks_path=str(tmp_path / "chunks.jsonl"),
            vector_db_path=str(tmp_path / "chroma"),
        ),
        processed_dir=tmp_path,
    )
    info = get_ingest_health_info(processed_dir=tmp_path)
    assert info["ingest_stale"] is False
    assert info["ingest_status"] == "success"


def test_get_ingest_health_info_stale_after_threshold(tmp_path: Path):
    old = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    write_ingest_manifest(
        IngestResult(
            status="success",
            started_at=old,
            finished_at=old,
            chunk_count=10,
            indexed=10,
            duration_sec=1.0,
            chunks_path=str(tmp_path / "chunks.jsonl"),
            vector_db_path=str(tmp_path / "chroma"),
        ),
        processed_dir=tmp_path,
    )
    info = get_ingest_health_info(processed_dir=tmp_path, stale_hours=36)
    assert info["ingest_stale"] is True


def test_get_ingest_health_info_failed_run_is_stale(tmp_path: Path):
    finished = datetime.now(timezone.utc).isoformat()
    write_ingest_manifest(
        IngestResult(
            status="failed",
            started_at=finished,
            finished_at=finished,
            chunk_count=0,
            indexed=0,
            duration_sec=1.0,
            chunks_path=str(tmp_path / "chunks.jsonl"),
            vector_db_path=str(tmp_path / "chroma"),
            error="fetch failed",
        ),
        processed_dir=tmp_path,
    )
    info = get_ingest_health_info(processed_dir=tmp_path)
    assert info["ingest_stale"] is True
    assert info["ingest_status"] == "failed"
