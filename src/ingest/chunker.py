"""Section-aware chunker for Groww scheme pages (corpus ingestion)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.ingest.fetcher import SchemeEntry, load_scheme_urls
from src.ingest.parser import (
    ParsedDocument,
    ParsedSection,
    format_nav_line,
    parse_html_file,
)

DOC_TYPE = "scheme_page"
MAX_CHUNK_CHARS = 2400  # ~600 tokens
MIN_CHUNK_CHARS = 120  # ~30 tokens
OVERLAP_CHARS = 260  # ~65 tokens (50–80 range)
ROWS_PER_CHUNK = 10
FUND_DETAILS_TITLE = "Fund details"
FUND_DETAILS_MARKER = f"## {FUND_DETAILS_TITLE}\n"
NAV_SECTION_TITLE = "NAV"

SectionType = str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    scheme: str
    category: str
    source_url: str
    doc_type: str
    section_title: str
    section_type: SectionType
    chunk_index: int
    fetched_at: str
    text: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """Approximate token count (~4 characters per token for English)."""
    return max(1, len(text) // 4)


def make_chunk_id(scheme: str, section_title: str, chunk_index: int) -> str:
    """Deterministic id for idempotent rebuilds."""
    payload = f"{scheme}|{section_title}|{chunk_index}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def format_chunk_text(scheme: str, section_title: str, body: str) -> str:
    return f"{scheme} — {section_title}:\n{body.strip()}"


def classify_section(title: str) -> SectionType | None:
    """Map a parser section title to a chunk section_type, or None to exclude."""
    tl = title.strip().lower()
    if tl == "understand terms":
        return None
    if tl.startswith("stamp duty"):
        return None
    if "fund management" in tl:
        return None
    if "holding" in tl:
        return "holdings"
    if "return calculator" in tl:
        return "returns"
    if "minimum" in tl:
        return "minimum_investments"
    if tl == "exit load":
        return "exit_load"
    if "tax implication" in tl:
        return "tax"
    if "investment objective" in tl:
        return "investment_objective"
    if "compare similar" in tl:
        return "compare_funds"
    if "fund basics" in tl:
        return "fund_details"
    return None


def _is_page_header(title: str, doc_title: str, section_text: str) -> bool:
    title_norm = title.strip().lower()
    doc_norm = doc_title.strip().lower()
    if title_norm == doc_norm:
        return True
    if doc_norm and title_norm in doc_norm:
        return True
    if doc_norm and doc_norm in title_norm and len(section_text) < 80:
        return True
    return len(section_text) < 50 and any(
        marker in section_text for marker in ("Equity", "Commodities", "Risk")
    )


def _extract_fund_details_body(doc: ParsedDocument) -> str | None:
    if FUND_DETAILS_MARKER not in doc.text:
        return None
    start = doc.text.index(FUND_DETAILS_MARKER) + len(FUND_DETAILS_MARKER)
    end = doc.text.find("\n\n## ", start)
    body = doc.text[start:end].strip() if end > 0 else doc.text[start:].strip()
    return body or None


def _split_fund_details_lines(body: str) -> list[str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return []

    # Drop long definitional lines (e.g. "Expense ratio A fee payable to...")
    facts: list[str] = []
    for line in lines:
        if len(line) > 120 and " payable " in line.lower():
            continue
        if len(line) < 20 and line.lower() in {"exit load", "expense ratio"}:
            continue
        facts.append(line)

    if not facts:
        facts = lines

    combined = "\n".join(facts)
    if len(combined) <= MAX_CHUNK_CHARS:
        return [combined]

    return [line for line in facts if len(line) >= MIN_CHUNK_CHARS // 2]


def split_table_rows(text: str, *, rows_per_chunk: int = ROWS_PER_CHUNK) -> list[str]:
    """Split pipe-delimited table text; repeat header row in each chunk."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) <= 1:
        return [text.strip()] if text.strip() else []

    header, *rows = lines
    if not rows:
        return [header]

    chunks: list[str] = []
    for index in range(0, len(rows), rows_per_chunk):
        block = "\n".join([header, *rows[index : index + rows_per_chunk]])
        chunks.append(block)
    return chunks


def split_prose_with_overlap(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split long prose on sentence boundaries with overlap."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) == 1:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            chunks.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(end - OVERLAP_CHARS, start + 1)
        return [c for c in chunks if c]

    chunks = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        addition = len(sentence) + (1 if current else 0)
        if current and current_len + addition > max_chars:
            chunks.append(" ".join(current))
            overlap = " ".join(current)[-OVERLAP_CHARS:].strip()
            current = [overlap, sentence] if overlap else [sentence]
            current_len = sum(len(part) for part in current) + len(current) - 1
        else:
            current.append(sentence)
            current_len += addition

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS // 2]


def _find_holdings_table(doc: ParsedDocument) -> str | None:
    candidates = [
        table
        for table in doc.tables
        if table.strip().startswith("Name | Sector")
    ]
    if not candidates:
        return None
    return max(candidates, key=len)


def _split_section_body(
    body: str,
    section_type: SectionType,
    *,
    holdings_table: str | None = None,
) -> list[str]:
    body = body.strip()
    if not body:
        return []

    if section_type == "holdings" and holdings_table and len(holdings_table) > len(body):
        body = holdings_table

    if len(body) <= MAX_CHUNK_CHARS:
        return [body]

    if section_type == "holdings" or ("|" in body and "\n" in body):
        return split_table_rows(body)

    return split_prose_with_overlap(body)


def _table_covered_by_sections(table: str, sections: list[ParsedSection]) -> bool:
    lines = [line for line in table.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return True

    first_cell = lines[1].split("|")[0].strip()
    if len(first_cell) < 3:
        return True

    bodies = "\n".join(section.text for section in sections)
    return first_cell in bodies


def _standalone_table_title(table: str) -> str:
    header = table.strip().splitlines()[0]
    if "3Y" in header and "5Y" in header:
        return "Fund vs category returns"
    if "Fund Size" in header:
        return "Compare similar funds"
    if "Historic returns" in header or "Would've become" in header:
        return "Return calculator"
    if header.startswith("Name | Sector"):
        return "Holdings"
    return "Table"


def _make_chunk(
    *,
    scheme: str,
    category: str,
    source_url: str,
    fetched_at: str,
    section_title: str,
    section_type: SectionType,
    chunk_index: int,
    body: str,
) -> Chunk | None:
    body = body.strip()
    if len(body) < MIN_CHUNK_CHARS // 2 and section_type != "exit_load":
        if len(body) < 20:
            return None

    text = format_chunk_text(scheme, section_title, body)
    if estimate_tokens(text) < 30 and section_type not in {
        "exit_load",
        "minimum_investments",
        "nav",
    }:
        return None

    return Chunk(
        chunk_id=make_chunk_id(scheme, section_title, chunk_index),
        scheme=scheme,
        category=category,
        source_url=source_url,
        doc_type=DOC_TYPE,
        section_title=section_title,
        section_type=section_type,
        chunk_index=chunk_index,
        fetched_at=fetched_at,
        text=text,
    )


def chunk_document(
    doc: ParsedDocument,
    *,
    scheme: str,
    category: str,
    source_url: str,
    fetched_at: str,
) -> list[Chunk]:
    """
    Build retrieval chunks from a parsed scheme page.

    Applies section-aware boundaries, scheme/category tagging, and exclusions
    from ImplementationPlan Phase 1.4–1.5.
    """
    chunks: list[Chunk] = []
    holdings_table = _find_holdings_table(doc)

    fund_details_body = _extract_fund_details_body(doc)
    if fund_details_body:
        for index, part in enumerate(_split_fund_details_lines(fund_details_body)):
            chunk = _make_chunk(
                scheme=scheme,
                category=category,
                source_url=source_url,
                fetched_at=fetched_at,
                section_title=FUND_DETAILS_TITLE,
                section_type="fund_details",
                chunk_index=index,
                body=part,
            )
            if chunk is not None:
                chunks.append(chunk)

    if doc.nav_value is not None:
        nav_chunk = _make_chunk(
            scheme=scheme,
            category=category,
            source_url=source_url,
            fetched_at=fetched_at,
            section_title=NAV_SECTION_TITLE,
            section_type="nav",
            chunk_index=0,
            body=format_nav_line(doc.nav_value, doc.nav_date),
        )
        if nav_chunk is not None:
            chunks.append(nav_chunk)

    for section in doc.sections:
        if _is_page_header(section.title, doc.title, section.text):
            continue

        section_type = classify_section(section.title)
        if section_type is None:
            continue

        bodies = _split_section_body(
            section.text,
            section_type,
            holdings_table=holdings_table if section_type == "holdings" else None,
        )
        for index, body in enumerate(bodies):
            chunk = _make_chunk(
                scheme=scheme,
                category=category,
                source_url=source_url,
                fetched_at=fetched_at,
                section_title=section.title,
                section_type=section_type,
                chunk_index=index,
                body=body,
            )
            if chunk is not None:
                chunks.append(chunk)

    for table_index, table in enumerate(doc.tables):
        if _table_covered_by_sections(table, doc.sections):
            continue
        if len(table.strip()) < MIN_CHUNK_CHARS // 2:
            continue

        title = _standalone_table_title(table)
        for index, body in enumerate(_split_section_body(table, "table")):
            chunk = _make_chunk(
                scheme=scheme,
                category=category,
                source_url=source_url,
                fetched_at=fetched_at,
                section_title=title,
                section_type="table",
                chunk_index=table_index * 100 + index,
                body=body,
            )
            if chunk is not None:
                chunks.append(chunk)

    return chunks


def chunk_scheme_entry(
    doc: ParsedDocument,
    entry: SchemeEntry,
    *,
    fetched_at: str,
) -> list[Chunk]:
    """Chunk a document with scheme tags from ``urls.json`` (Phase 1.5)."""
    return chunk_document(
        doc,
        scheme=entry.scheme,
        category=entry.category,
        source_url=entry.url,
        fetched_at=fetched_at,
    )


def chunk_latest_raw_snapshots(
    raw_dir: Path | None = None,
    entries: list[SchemeEntry] | None = None,
) -> list[Chunk]:
    """Parse and chunk the newest HTML snapshot per scheme under ``data/raw/``."""
    base = raw_dir or Path("data/raw")
    schemes = entries if entries is not None else load_scheme_urls()
    url_by_slug = {entry.slug: entry for entry in schemes}

    all_chunks: list[Chunk] = []
    for scheme_dir in sorted(base.iterdir()):
        if not scheme_dir.is_dir():
            continue
        entry = url_by_slug.get(scheme_dir.name)
        if entry is None:
            continue

        html_files = sorted(scheme_dir.glob("*.html"), reverse=True)
        meta_files = sorted(scheme_dir.glob("*.meta.json"), reverse=True)
        if not html_files:
            continue

        meta = json.loads(meta_files[0].read_text(encoding="utf-8")) if meta_files else {}
        fetched_at = meta.get("fetched_at", "")
        doc = parse_html_file(html_files[0], source_url=entry.url)
        all_chunks.extend(
            chunk_scheme_entry(doc, entry, fetched_at=fetched_at)
        )

    return all_chunks


def write_chunks_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


def read_chunks_jsonl(path: Path) -> list[dict[str, str | int]]:
    """Load chunk rows written by ``write_chunks_jsonl``."""
    rows: list[dict[str, str | int]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
