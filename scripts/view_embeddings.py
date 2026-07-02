#!/usr/bin/env python3
"""Inspect and verify embeddings for every corpus chunk."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.ingest.chunker import read_chunks_jsonl
from src.index.embedder import embed_passages
from src.index.vector_store import COLLECTION_NAME, get_collection

DEFAULT_PREVIEW_DIMS = 8
DEFAULT_MATCH_TOLERANCE = 1e-4


@dataclass
class EmbeddingRecord:
    chunk_id: str
    scheme: str
    section_type: str
    section_title: str
    text_preview: str
    dims: int
    norm: float
    preview: list[float]
    stored: bool
    recomputed_cosine: float | None = None
    issues: list[str] | None = None


def vector_norm(values: list[float]) -> float:
    arr = np.asarray(values, dtype=np.float64)
    return float(np.linalg.norm(arr))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def load_stored_embeddings(
    *,
    vector_db_path: Path | None = None,
) -> dict[str, list[float]]:
    collection = get_collection(persist_directory=vector_db_path)
    response = collection.get(include=["embeddings"])
    ids = response.get("ids", [])
    embeddings = response.get("embeddings", [])

    stored: dict[str, list[float]] = {}
    for chunk_id, embedding in zip(ids, embeddings, strict=True):
        if embedding is None:
            continue
        stored[str(chunk_id)] = [float(v) for v in embedding]
    return stored


def verify_embeddings(
    *,
    chunks_path: Path | None = None,
    vector_db_path: Path | None = None,
    recompute: bool = True,
    preview_dims: int = DEFAULT_PREVIEW_DIMS,
    match_tolerance: float = DEFAULT_MATCH_TOLERANCE,
) -> tuple[list[EmbeddingRecord], dict[str, int | list[str]]]:
    path = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/build_corpus.py first."
        )

    chunks = read_chunks_jsonl(path)
    stored_by_id = load_stored_embeddings(vector_db_path=vector_db_path)
    chunk_ids = {str(chunk["chunk_id"]) for chunk in chunks}

    recomputed_by_id: dict[str, list[float]] = {}
    if recompute and chunks:
        texts = [str(chunk["text"]) for chunk in chunks]
        recomputed = embed_passages(texts)
        recomputed_by_id = {
            str(chunk["chunk_id"]): vector
            for chunk, vector in zip(chunks, recomputed, strict=True)
        }

    records: list[EmbeddingRecord] = []
    failed_ids: list[str] = []
    missing_in_index: list[str] = []
    norm_issues: list[str] = []
    mismatch_issues: list[str] = []

    expected_dims: int | None = None

    for chunk in chunks:
        chunk_id = str(chunk["chunk_id"])
        issues: list[str] = []
        text = str(chunk["text"])
        stored = stored_by_id.get(chunk_id)

        if stored is None:
            issues.append("missing in Chroma index")
            missing_in_index.append(chunk_id)
            records.append(
                EmbeddingRecord(
                    chunk_id=chunk_id,
                    scheme=str(chunk["scheme"]),
                    section_type=str(chunk["section_type"]),
                    section_title=str(chunk["section_title"]),
                    text_preview=text[:80].replace("\n", " "),
                    dims=0,
                    norm=0.0,
                    preview=[],
                    stored=False,
                    issues=issues,
                )
            )
            failed_ids.append(chunk_id)
            continue

        dims = len(stored)
        if expected_dims is None:
            expected_dims = dims
        elif dims != expected_dims:
            issues.append(f"unexpected dims {dims} (expected {expected_dims})")

        norm = vector_norm(stored)
        if not math.isfinite(norm):
            issues.append("non-finite norm")
            norm_issues.append(chunk_id)
        elif abs(norm - 1.0) > 0.01:
            issues.append(f"norm {norm:.6f} (expected ~1.0)")
            norm_issues.append(chunk_id)

        recomputed_cosine: float | None = None
        if recompute:
            fresh = recomputed_by_id.get(chunk_id)
            if fresh is None:
                issues.append("recompute missing")
            else:
                recomputed_cosine = cosine_similarity(stored, fresh)
                if recomputed_cosine < (1.0 - match_tolerance):
                    issues.append(
                        f"stored vs recomputed cosine {recomputed_cosine:.6f}"
                    )
                    mismatch_issues.append(chunk_id)

        if issues:
            failed_ids.append(chunk_id)

        records.append(
            EmbeddingRecord(
                chunk_id=chunk_id,
                scheme=str(chunk["scheme"]),
                section_type=str(chunk["section_type"]),
                section_title=str(chunk["section_title"]),
                text_preview=text[:80].replace("\n", " "),
                dims=dims,
                norm=norm,
                preview=[round(v, 6) for v in stored[:preview_dims]],
                stored=True,
                recomputed_cosine=recomputed_cosine,
                issues=issues or None,
            )
        )

    orphan_ids = sorted(set(stored_by_id) - chunk_ids)

    summary: dict[str, int | list[str]] = {
        "chunks_in_jsonl": len(chunks),
        "embeddings_in_chroma": len(stored_by_id),
        "expected_dims": expected_dims or 0,
        "verified_ok": len(chunks) - len(failed_ids),
        "failed": len(failed_ids),
        "missing_in_index": missing_in_index,
        "orphan_in_index": orphan_ids,
        "norm_issues": norm_issues,
        "mismatch_issues": mismatch_issues,
        "failed_ids": failed_ids,
        "collection": COLLECTION_NAME,
        "embedding_model": settings.embedding_model,
    }
    return records, summary


def print_table(records: list[EmbeddingRecord], *, preview_dims: int) -> None:
    header = (
        f"{'chunk_id':<18} {'scheme':<28} {'section':<18} "
        f"{'dims':>4} {'norm':>6} {'match':>6}  preview[{preview_dims}]"
    )
    print(header)
    print("-" * len(header))

    for record in records:
        scheme = record.scheme
        if len(scheme) > 26:
            scheme = scheme[:23] + "..."

        section = record.section_type
        if len(section) > 16:
            section = section[:13] + "..."

        match = (
            f"{record.recomputed_cosine:.4f}"
            if record.recomputed_cosine is not None
            else "n/a"
        )
        preview = ", ".join(f"{v:+.4f}" for v in record.preview)
        status = " OK" if not record.issues else " FAIL"

        print(
            f"{record.chunk_id:<18} {scheme:<28} {section:<18} "
            f"{record.dims:>4} {record.norm:>6.4f} {match:>6}  [{preview}]{status}"
        )
        if record.issues:
            for issue in record.issues:
                print(f"  ! {issue}")


def write_json_output(
    path: Path,
    records: list[EmbeddingRecord],
    summary: dict[str, int | list[str]],
    *,
    include_vectors: bool,
    stored_by_id: dict[str, list[float]],
) -> None:
    rows = []
    for record in records:
        row = {
            "chunk_id": record.chunk_id,
            "scheme": record.scheme,
            "section_type": record.section_type,
            "section_title": record.section_title,
            "text_preview": record.text_preview,
            "dims": record.dims,
            "norm": record.norm,
            "preview": record.preview,
            "stored": record.stored,
            "recomputed_cosine": record.recomputed_cosine,
            "issues": record.issues,
        }
        if include_vectors and record.stored:
            row["embedding"] = stored_by_id[record.chunk_id]
        rows.append(row)

    payload = {"summary": summary, "records": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_parquet_output(
    path: Path,
    records: list[EmbeddingRecord],
    *,
    chunks_path: Path | None,
    stored_by_id: dict[str, list[float]],
    expand_dims: bool = False,
) -> int:
    """Write all chunks + full embedding vectors to a Parquet file.

    Columns are chosen so the file is readable in the Parquet viewer extension:
    chunk metadata + text, verification stats, an ``embedding`` list column, and
    (optionally) one float column per dimension (``dim_000``…).
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required for Parquet export. Run: pip install pyarrow"
        ) from exc

    source = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    chunks_by_id = {str(c["chunk_id"]): c for c in read_chunks_jsonl(source)}
    record_by_id = {r.chunk_id: r for r in records}

    dims = next((len(v) for v in stored_by_id.values()), 0)

    columns: dict[str, list] = {
        "chunk_id": [],
        "scheme": [],
        "category": [],
        "source_url": [],
        "doc_type": [],
        "section_title": [],
        "section_type": [],
        "chunk_index": [],
        "fetched_at": [],
        "text": [],
        "dims": [],
        "norm": [],
        "recomputed_cosine": [],
        "stored": [],
        "issues": [],
        "embedding": [],
    }

    zero_vector = [0.0] * dims
    for chunk_id, chunk in chunks_by_id.items():
        record = record_by_id.get(chunk_id)
        embedding = stored_by_id.get(chunk_id, zero_vector)

        columns["chunk_id"].append(chunk_id)
        columns["scheme"].append(str(chunk.get("scheme", "")))
        columns["category"].append(str(chunk.get("category", "")))
        columns["source_url"].append(str(chunk.get("source_url", "")))
        columns["doc_type"].append(str(chunk.get("doc_type", "")))
        columns["section_title"].append(str(chunk.get("section_title", "")))
        columns["section_type"].append(str(chunk.get("section_type", "")))
        columns["chunk_index"].append(int(chunk.get("chunk_index", 0)))
        columns["fetched_at"].append(str(chunk.get("fetched_at", "")))
        columns["text"].append(str(chunk.get("text", "")))
        columns["dims"].append(record.dims if record else len(embedding))
        columns["norm"].append(record.norm if record else 0.0)
        columns["recomputed_cosine"].append(
            record.recomputed_cosine if record else None
        )
        columns["stored"].append(bool(record.stored) if record else False)
        columns["issues"].append("; ".join(record.issues) if record and record.issues else "")
        columns["embedding"].append([float(v) for v in embedding])

    arrays = {
        "chunk_id": pa.array(columns["chunk_id"], pa.string()),
        "scheme": pa.array(columns["scheme"], pa.string()),
        "category": pa.array(columns["category"], pa.string()),
        "source_url": pa.array(columns["source_url"], pa.string()),
        "doc_type": pa.array(columns["doc_type"], pa.string()),
        "section_title": pa.array(columns["section_title"], pa.string()),
        "section_type": pa.array(columns["section_type"], pa.string()),
        "chunk_index": pa.array(columns["chunk_index"], pa.int32()),
        "fetched_at": pa.array(columns["fetched_at"], pa.string()),
        "text": pa.array(columns["text"], pa.string()),
        "dims": pa.array(columns["dims"], pa.int32()),
        "norm": pa.array(columns["norm"], pa.float64()),
        "recomputed_cosine": pa.array(columns["recomputed_cosine"], pa.float64()),
        "stored": pa.array(columns["stored"], pa.bool_()),
        "issues": pa.array(columns["issues"], pa.string()),
        "embedding": pa.array(
            columns["embedding"], pa.list_(pa.float32(), dims if dims else -1)
        ),
    }

    if expand_dims and dims:
        matrix = np.asarray(columns["embedding"], dtype=np.float32)
        for index in range(dims):
            arrays[f"dim_{index:03d}"] = pa.array(matrix[:, index], pa.float32())

    table = pa.table(arrays)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return table.num_rows


def write_csv_output(
    path: Path,
    records: list[EmbeddingRecord],
    *,
    chunks_path: Path | None,
    stored_by_id: dict[str, list[float]],
    preview_dims: int = DEFAULT_PREVIEW_DIMS,
) -> int:
    """Write a spreadsheet-friendly CSV (metadata + preview dims, no full vector).

    Opens in any editor without a Parquet extension. The full vector stays in the
    Parquet/JSON exports; here each embedding is summarized by its first
    ``preview_dims`` values so rows stay readable.
    """
    import csv

    source = chunks_path or (settings.processed_data_dir / "chunks.jsonl")
    chunks_by_id = {str(c["chunk_id"]): c for c in read_chunks_jsonl(source)}
    record_by_id = {r.chunk_id: r for r in records}

    dim_headers = [f"dim_{i:03d}" for i in range(preview_dims)]
    header = [
        "chunk_id",
        "scheme",
        "category",
        "section_type",
        "section_title",
        "chunk_index",
        "dims",
        "norm",
        "recomputed_cosine",
        "stored",
        "issues",
        "text",
        *dim_headers,
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for chunk_id, chunk in chunks_by_id.items():
            record = record_by_id.get(chunk_id)
            embedding = stored_by_id.get(chunk_id, [])
            preview = [f"{v:.6f}" for v in embedding[:preview_dims]]
            preview += [""] * (preview_dims - len(preview))
            writer.writerow(
                [
                    chunk_id,
                    chunk.get("scheme", ""),
                    chunk.get("category", ""),
                    chunk.get("section_type", ""),
                    chunk.get("section_title", ""),
                    chunk.get("chunk_index", 0),
                    record.dims if record else len(embedding),
                    f"{record.norm:.6f}" if record else "",
                    f"{record.recomputed_cosine:.6f}"
                    if record and record.recomputed_cosine is not None
                    else "",
                    bool(record.stored) if record else False,
                    "; ".join(record.issues) if record and record.issues else "",
                    str(chunk.get("text", "")).replace("\n", " "),
                    *preview,
                ]
            )
    return len(chunks_by_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="View and verify embeddings for all chunks in chunks.jsonl.",
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        default=None,
        help=f"Input JSONL (default: {settings.processed_data_dir / 'chunks.jsonl'}).",
    )
    parser.add_argument(
        "--vector-db-path",
        type=Path,
        default=None,
        help=f"Chroma directory (default: {settings.vector_db_path}).",
    )
    parser.add_argument(
        "--no-recompute",
        action="store_true",
        help="Skip re-embedding check (only inspect stored vectors).",
    )
    parser.add_argument(
        "--preview-dims",
        type=int,
        default=DEFAULT_PREVIEW_DIMS,
        help=f"Number of embedding dimensions to preview (default: {DEFAULT_PREVIEW_DIMS}).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_MATCH_TOLERANCE,
        help=f"Max allowed stored/recomputed drift (default: {DEFAULT_MATCH_TOLERANCE}).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write full report to JSON (use --include-vectors for complete vectors).",
    )
    parser.add_argument(
        "--include-vectors",
        action="store_true",
        help="Include full embedding vectors in --json-out.",
    )
    parser.add_argument(
        "--parquet-out",
        type=Path,
        default=None,
        help="Write all chunks + full embeddings to a Parquet file (viewable "
        "with the Parquet extension).",
    )
    parser.add_argument(
        "--expand-dims",
        action="store_true",
        help="Also add one float column per dimension (dim_000…) in the Parquet file.",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Write a spreadsheet-friendly CSV (metadata + preview dims, no full "
        "vector) that opens without a Parquet extension.",
    )
    args = parser.parse_args()

    try:
        records, summary = verify_embeddings(
            chunks_path=args.chunks_path,
            vector_db_path=args.vector_db_path,
            recompute=not args.no_recompute,
            preview_dims=args.preview_dims,
            match_tolerance=args.tolerance,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Model: {summary['embedding_model']}")
    print(f"Collection: {summary['collection']}")
    print(
        f"Chunks: {summary['chunks_in_jsonl']} | "
        f"Chroma vectors: {summary['embeddings_in_chroma']} | "
        f"Dims: {summary['expected_dims']}"
    )
    print()

    print_table(records, preview_dims=args.preview_dims)
    print()

    print("Summary")
    print(f"  Verified OK: {summary['verified_ok']}/{summary['chunks_in_jsonl']}")
    if summary["missing_in_index"]:
        print(f"  Missing in index: {len(summary['missing_in_index'])}")
    if summary["orphan_in_index"]:
        print(f"  Orphan vectors in index: {len(summary['orphan_in_index'])}")
    if summary["norm_issues"]:
        print(f"  Norm issues: {len(summary['norm_issues'])}")
    if summary["mismatch_issues"]:
        print(f"  Recompute mismatches: {len(summary['mismatch_issues'])}")

    stored_by_id: dict[str, list[float]] | None = None
    if args.json_out or args.parquet_out or args.csv_out:
        stored_by_id = load_stored_embeddings(vector_db_path=args.vector_db_path)

    if args.json_out:
        write_json_output(
            args.json_out,
            records,
            summary,
            include_vectors=args.include_vectors,
            stored_by_id=stored_by_id,
        )
        print(f"\nWrote report to {args.json_out}")

    if args.parquet_out:
        rows = write_parquet_output(
            args.parquet_out,
            records,
            chunks_path=args.chunks_path,
            stored_by_id=stored_by_id,
            expand_dims=args.expand_dims,
        )
        print(f"Wrote {rows} rows with full embeddings to {args.parquet_out}")

    if args.csv_out:
        rows = write_csv_output(
            args.csv_out,
            records,
            chunks_path=args.chunks_path,
            stored_by_id=stored_by_id,
            preview_dims=args.preview_dims,
        )
        print(f"Wrote {rows} rows to {args.csv_out}")

    return 0 if summary["failed"] == 0 and not summary["orphan_in_index"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
