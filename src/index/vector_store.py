"""Chroma vector store for the HDFC MF corpus (Phase 1.7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from src.config import settings

COLLECTION_NAME = "hdfc_mf_corpus"
COSINE_SPACE = "cosine"

METADATA_FIELDS = (
    "scheme",
    "category",
    "source_url",
    "doc_type",
    "section_title",
    "section_type",
    "chunk_index",
    "fetched_at",
)


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    distance: float

    @property
    def similarity(self) -> float:
        """Cosine similarity when the collection uses cosine space."""
        return max(0.0, 1.0 - self.distance)


def get_client(persist_directory: Path | None = None) -> ClientAPI:
    path = persist_directory or settings.vector_db_path
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def get_collection(
    client: ClientAPI | None = None,
    *,
    persist_directory: Path | None = None,
) -> Collection:
    chroma = client or get_client(persist_directory)
    return chroma.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": COSINE_SPACE},
    )


def chunk_to_metadata(chunk: dict[str, Any]) -> dict[str, str | int]:
    """Map a chunk row to Chroma-compatible metadata."""
    return {
        "scheme": str(chunk["scheme"]),
        "category": str(chunk["category"]),
        "source_url": str(chunk["source_url"]),
        "doc_type": str(chunk["doc_type"]),
        "section_title": str(chunk["section_title"]),
        "section_type": str(chunk["section_type"]),
        "chunk_index": int(chunk["chunk_index"]),
        "fetched_at": str(chunk["fetched_at"]),
    }


def reset_collection(
    client: ClientAPI | None = None,
    *,
    persist_directory: Path | None = None,
) -> Collection:
    """Drop and recreate the corpus collection."""
    chroma = client or get_client(persist_directory)
    try:
        chroma.delete_collection(COLLECTION_NAME)
    except (ValueError, chromadb.errors.NotFoundError):
        pass
    return chroma.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": COSINE_SPACE},
    )


def upsert_chunks(
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
    *,
    collection: Collection | None = None,
    client: ClientAPI | None = None,
    batch_size: int = 100,
) -> int:
    """Upsert chunk rows and precomputed embeddings into Chroma."""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings length mismatch")

    if not chunks:
        return 0

    target = collection or get_collection(client=client)
    total = 0

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        batch_embeddings = embeddings[start : start + batch_size]
        target.upsert(
            ids=[str(item["chunk_id"]) for item in batch],
            embeddings=batch_embeddings,
            documents=[str(item["text"]) for item in batch],
            metadatas=[chunk_to_metadata(item) for item in batch],
        )
        total += len(batch)

    return total


def build_where_filter(
    *,
    scheme: str | None = None,
    doc_type: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    """Build a Chroma metadata filter from optional fields."""
    clauses: list[dict[str, Any]] = []
    if scheme:
        clauses.append({"scheme": scheme})
    if doc_type:
        clauses.append({"doc_type": doc_type})
    if source_url:
        clauses.append({"source_url": source_url})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def search(
    query_embedding: list[float],
    *,
    top_k: int | None = None,
    scheme: str | None = None,
    doc_type: str | None = None,
    source_url: str | None = None,
    collection: Collection | None = None,
) -> list[SearchResult]:
    """Vector similarity search with optional metadata filters."""
    target = collection or get_collection()
    k = top_k if top_k is not None else settings.top_k
    where = build_where_filter(scheme=scheme, doc_type=doc_type, source_url=source_url)

    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where is not None:
        kwargs["where"] = where

    response = target.query(**kwargs)

    ids = response.get("ids", [[]])[0]
    documents = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]

    results: list[SearchResult] = []
    for chunk_id, text, metadata, distance in zip(
        ids, documents, metadatas, distances, strict=True
    ):
        results.append(
            SearchResult(
                chunk_id=chunk_id,
                text=text or "",
                metadata=metadata or {},
                distance=float(distance),
            )
        )
    return results


def collection_count(collection: Collection | None = None) -> int:
    target = collection or get_collection()
    return target.count()
