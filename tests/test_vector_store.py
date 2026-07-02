"""Tests for embedder and vector store (Phase 1.6–1.7)."""

from pathlib import Path

import pytest

from src.index.embedder import (
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    embed_passages,
    embed_query,
    prefix_text,
)
from src.index.vector_store import (
    build_where_filter,
    chunk_to_metadata,
    get_client,
    reset_collection,
    search,
    upsert_chunks,
)
from src.ingest.chunker import Chunk, make_chunk_id, read_chunks_jsonl, write_chunks_jsonl

SAMPLE_CHUNK = {
    "chunk_id": make_chunk_id("HDFC Mid Cap Fund Direct Growth", "Fund details", 0),
    "scheme": "HDFC Mid Cap Fund Direct Growth",
    "category": "mid-cap equity",
    "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "doc_type": "scheme_page",
    "section_title": "Fund details",
    "section_type": "fund_details",
    "chunk_index": 0,
    "fetched_at": "2026-07-01T12:00:00+00:00",
    "text": (
        "HDFC Mid Cap Fund Direct Growth — Fund details:\n"
        "Expense ratio 0.77%"
    ),
}

OTHER_SCHEME_CHUNK = {
    **SAMPLE_CHUNK,
    "chunk_id": make_chunk_id("HDFC Large Cap Fund Direct Growth", "Fund details", 0),
    "scheme": "HDFC Large Cap Fund Direct Growth",
    "category": "large-cap equity",
    "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "text": (
        "HDFC Large Cap Fund Direct Growth — Fund details:\n"
        "Expense ratio 0.96%"
    ),
}


@pytest.fixture
def chroma_dir(tmp_path: Path):
    return tmp_path / "chroma"


def test_prefix_text_adds_bge_instruction():
    assert prefix_text("expense ratio", "query") == f"{QUERY_PREFIX}expense ratio"
    assert prefix_text("expense ratio", "passage") == f"{PASSAGE_PREFIX}expense ratio"
    assert prefix_text(f"{QUERY_PREFIX}already", "query") == f"{QUERY_PREFIX}already"


def test_embed_query_and_passage_shapes():
    query_vec = embed_query("expense ratio HDFC Mid Cap")
    passage_vecs = embed_passages([SAMPLE_CHUNK["text"]])
    assert len(query_vec) == len(passage_vecs[0])
    assert len(query_vec) > 0


def test_chunk_to_metadata_types():
    meta = chunk_to_metadata(SAMPLE_CHUNK)
    assert meta["scheme"] == SAMPLE_CHUNK["scheme"]
    assert meta["chunk_index"] == 0
    assert isinstance(meta["fetched_at"], str)


def test_build_where_filter_single_and_and():
    assert build_where_filter(scheme="A") == {"scheme": "A"}
    assert build_where_filter(scheme="A", doc_type="scheme_page") == {
        "$and": [{"scheme": "A"}, {"doc_type": "scheme_page"}],
    }
    assert build_where_filter() is None


def test_upsert_and_search_with_scheme_filter(chroma_dir: Path):
    client = get_client(chroma_dir)
    collection = reset_collection(client=client)
    embeddings = embed_passages(
        [SAMPLE_CHUNK["text"], OTHER_SCHEME_CHUNK["text"]]
    )
    upsert_chunks(
        [SAMPLE_CHUNK, OTHER_SCHEME_CHUNK],
        embeddings,
        collection=collection,
    )

    query_embedding = embed_query("expense ratio HDFC Mid Cap")
    results = search(
        query_embedding,
        top_k=3,
        scheme="HDFC Mid Cap Fund Direct Growth",
        collection=collection,
    )
    assert results
    assert all(r.metadata["scheme"] == "HDFC Mid Cap Fund Direct Growth" for r in results)
    assert results[0].metadata["section_type"] == "fund_details"


def test_read_chunks_jsonl_roundtrip(tmp_path: Path):
    chunk = Chunk(**{k: v for k, v in SAMPLE_CHUNK.items()})  # type: ignore[arg-type]
    path = tmp_path / "chunks.jsonl"
    write_chunks_jsonl([chunk], path)
    rows = read_chunks_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["chunk_id"] == SAMPLE_CHUNK["chunk_id"]


@pytest.mark.integration
def test_live_index_expense_ratio_query(chroma_dir: Path):
    """Requires processed chunks.jsonl from a prior corpus build."""
    chunks_path = Path("data/processed/chunks.jsonl")
    if not chunks_path.is_file():
        pytest.skip("No chunks.jsonl; run build_corpus.py --skip-fetch first")

    chunks = read_chunks_jsonl(chunks_path)
    client = get_client(chroma_dir)
    collection = reset_collection(client=client)
    embeddings = embed_passages([str(c["text"]) for c in chunks])
    upsert_chunks(chunks, embeddings, collection=collection)

    results = search(
        embed_query("expense ratio HDFC Mid Cap"),
        top_k=5,
        scheme="HDFC Mid Cap Fund Direct Growth",
        collection=collection,
    )
    assert results
    top_types = {r.metadata["section_type"] for r in results[:3]}
    assert "fund_details" in top_types or "exit_load" in top_types
