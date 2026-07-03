"""Tests for production index bootstrap."""

from unittest.mock import patch

import pytest

from src.index.bootstrap import (
    chunks_jsonl_fingerprint,
    ensure_search_index,
    rebuild_index_from_chunks,
)


def test_ensure_search_index_skips_when_nav_chunks_present():
    with (
        patch("src.index.bootstrap.collection_count", return_value=67),
        patch("src.index.bootstrap._has_nav_chunks", return_value=True),
        patch("src.index.bootstrap.rebuild_index_from_chunks") as rebuild,
    ):
        assert ensure_search_index() == 67
        rebuild.assert_not_called()


def test_ensure_search_index_rebuilds_from_jsonl(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text(
        '{"chunk_id":"a","scheme":"S","category":"c","source_url":"u",'
        '"doc_type":"scheme_page","section_title":"NAV","section_type":"nav",'
        '"chunk_index":0,"fetched_at":"2026-07-01T00:00:00+00:00",'
        '"text":"NAV chunk"}\n',
        encoding="utf-8",
    )
    with (
        patch("src.index.bootstrap.collection_count", side_effect=[0, 1]),
        patch("src.index.bootstrap._has_nav_chunks", return_value=False),
        patch(
            "src.index.bootstrap.rebuild_index_from_chunks",
            return_value=1,
        ) as rebuild,
        patch("src.index.bootstrap.settings.processed_data_dir", tmp_path),
    ):
        chunks_path = tmp_path / "chunks.jsonl"
        assert ensure_search_index() == 1
        rebuild.assert_called_once_with(chunks_path)


def test_ensure_search_index_rebuilds_when_fingerprint_changes():
    with (
        patch("src.index.bootstrap.collection_count", return_value=67),
        patch("src.index.bootstrap._has_nav_chunks", return_value=True),
        patch("src.index.bootstrap.chunks_jsonl_fingerprint", return_value="new"),
        patch(
            "src.index.bootstrap.rebuild_index_from_chunks",
            return_value=68,
        ) as rebuild,
    ):
        assert ensure_search_index(expected_fingerprint="old") == 68
        rebuild.assert_called_once()


def test_ensure_search_index_cloud_deploy_requires_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_DEPLOY", "true")
    from src.config import get_settings

    get_settings.cache_clear()
    with (
        patch("src.index.bootstrap.collection_count", return_value=0),
        patch("src.index.bootstrap._has_nav_chunks", return_value=False),
        patch("src.index.bootstrap.settings.processed_data_dir", tmp_path),
        patch("src.index.bootstrap.settings.cloud_deploy", True),
    ):
        with pytest.raises(FileNotFoundError, match="chunks.jsonl"):
            ensure_search_index()


def test_chunks_jsonl_fingerprint_missing(tmp_path):
    with patch("src.index.bootstrap.settings.processed_data_dir", tmp_path):
        assert chunks_jsonl_fingerprint() == "missing"


def test_chunks_jsonl_fingerprint_stable(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text('{"text":"hello"}\n', encoding="utf-8")
    with patch("src.index.bootstrap.settings.processed_data_dir", tmp_path):
        first = chunks_jsonl_fingerprint()
        second = chunks_jsonl_fingerprint()
    assert first == second
    assert len(first) == 64


@pytest.mark.integration
def test_rebuild_index_from_chunks_live():
    from src.config import settings
    from src.index.vector_store import collection_count

    chunks_path = settings.processed_data_dir / "chunks.jsonl"
    if not chunks_path.is_file():
        pytest.skip("chunks.jsonl missing")

    indexed = rebuild_index_from_chunks(chunks_path)
    assert indexed > 0
    assert collection_count() == indexed
