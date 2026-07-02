"""Tests for corpus chunker (Phase 1.4–1.5)."""

import json
from pathlib import Path

import pytest

from src.ingest.chunker import (
    DOC_TYPE,
    MAX_CHUNK_CHARS,
    SchemeEntry,
    chunk_latest_raw_snapshots,
    chunk_scheme_entry,
    make_chunk_id,
    split_table_rows,
)
from src.ingest.parser import parse_html

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURES_DIR / "sample_groww.html").read_text(encoding="utf-8")

MID_CAP_ENTRY = SchemeEntry(
    scheme="HDFC Mid Cap Fund Direct Growth",
    category="mid-cap equity",
    url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
)

REQUIRED_FIELDS = {
    "chunk_id",
    "scheme",
    "category",
    "source_url",
    "doc_type",
    "section_title",
    "section_type",
    "chunk_index",
    "fetched_at",
    "text",
}


def _chunk_sample() -> list:
    doc = parse_html(SAMPLE_HTML, source_url=MID_CAP_ENTRY.url)
    return chunk_scheme_entry(
        doc,
        MID_CAP_ENTRY,
        fetched_at="2026-07-01T12:00:00+00:00",
    )


def test_chunk_metadata_fields():
    chunks = _chunk_sample()
    assert chunks
    for chunk in chunks:
        data = chunk.to_dict()
        assert REQUIRED_FIELDS <= set(data.keys())
        assert data["scheme"] == MID_CAP_ENTRY.scheme
        assert data["category"] == MID_CAP_ENTRY.category
        assert data["source_url"] == MID_CAP_ENTRY.url
        assert data["doc_type"] == DOC_TYPE


def test_chunk_text_has_scheme_prefix():
    chunks = _chunk_sample()
    for chunk in chunks:
        assert chunk.text.startswith(f"{MID_CAP_ENTRY.scheme} —")


def test_chunk_token_bounds():
    chunks = _chunk_sample()
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS + 200  # prefix allowance
        assert len(chunk.text) // 4 <= 650


def test_chunker_emits_nav_chunk_from_next_data():
    doc = parse_html(SAMPLE_HTML)
    chunks = chunk_scheme_entry(doc, MID_CAP_ENTRY, fetched_at="2026-01-01T00:00:00Z")
    nav_chunks = [c for c in chunks if c.section_type == "nav"]
    assert len(nav_chunks) == 1
    assert "NAV ₹226.765 (as on 30-Jun-2026)" in nav_chunks[0].text
    assert nav_chunks[0].section_title == "NAV"


def test_excludes_boilerplate_sections():
    html = """
    <html><body><div class="pw14ContentWrapper">
      <h1>HDFC Mid Cap Fund Direct Growth</h1>
      <h2>Understand terms</h2><p>Annualised returns definition.</p>
      <h2>Stamp duty on investment: 0.005%</h2><p>from July 1st 2020</p>
      <h2>Fund management</h2><p>""" + ("Manager bio. " * 400) + """</p>
      <h2>Exit load</h2><p>Exit load of 1% if redeemed within 1 year.</p>
    </div></body></html>
    """
    doc = parse_html(html)
    chunks = chunk_scheme_entry(doc, MID_CAP_ENTRY, fetched_at="2026-01-01T00:00:00Z")
    titles = {c.section_title for c in chunks}
    types = {c.section_type for c in chunks}
    assert "Understand terms" not in titles
    assert "Fund management" not in titles
    assert "fund_management" not in types
    assert any(c.section_type == "exit_load" for c in chunks)


def test_holdings_split_repeats_header():
    table = "Name | Sector | Assets\n" + "\n".join(
        f"Fund {i} | Financial | {i}.00%" for i in range(25)
    )
    parts = split_table_rows(table, rows_per_chunk=10)
    assert len(parts) == 3
    for part in parts:
        assert part.startswith("Name | Sector | Assets")
        assert part.count("\n") <= 10


def test_holdings_section_uses_pipe_table_when_oversized():
    html = f"""
    <html><body><div class="pw14ContentWrapper">
      <h1>HDFC Mid Cap Fund Direct Growth</h1>
      <h2>Holdings ( 80 )</h2>
      <table><tr><th>Name</th><th>Sector</th><th>Instruments</th><th>Assets</th></tr>
      {"".join(f"<tr><td>Company {i} Holdings Name</td><td>Financial</td><td>Equity</td><td>{i}.00%</td></tr>" for i in range(80))}
      </table>
    </div></body></html>
    """
    doc = parse_html(html)
    chunks = chunk_scheme_entry(doc, MID_CAP_ENTRY, fetched_at="2026-01-01T00:00:00Z")
    holdings = [c for c in chunks if c.section_type == "holdings"]
    assert len(holdings) >= 2
    assert all("Name | Sector" in c.text for c in holdings)


def test_deterministic_chunk_id():
    assert make_chunk_id("Scheme A", "Exit load", 0) == make_chunk_id(
        "Scheme A", "Exit load", 0
    )
    assert make_chunk_id("Scheme A", "Exit load", 0) != make_chunk_id(
        "Scheme A", "Exit load", 1
    )


@pytest.mark.integration
def test_standalone_table_chunk_for_category_returns():
    """Category returns tables are not embedded in parser sections on live pages."""
    raw_dir = Path("data/raw")
    if not raw_dir.exists():
        pytest.skip("No raw corpus fetched")

    chunks = chunk_latest_raw_snapshots()
    table_chunks = [c for c in chunks if c.section_type == "table"]
    assert len(table_chunks) == 5
    assert all("Fund returns" in c.text for c in table_chunks)


@pytest.mark.integration
def test_live_corpus_chunk_inventory():
    raw_dir = Path("data/raw")
    if not raw_dir.exists():
        pytest.skip("No raw corpus fetched")

    chunks = chunk_latest_raw_snapshots()
    assert 55 <= len(chunks) <= 70

    schemes = {c.scheme for c in chunks}
    assert len(schemes) == 5

    for chunk in chunks:
        assert chunk.doc_type == DOC_TYPE
        assert chunk.section_type
        assert chunk.scheme in schemes
        assert len(chunk.text) // 4 <= 650

    types = {c.section_type for c in chunks}
    assert "fund_management" not in types
    assert "fund_details" in types
    assert "exit_load" in types
    assert "table" in types

    by_scheme: dict[str, list] = {}
    for chunk in chunks:
        by_scheme.setdefault(chunk.scheme, []).append(chunk)
    for scheme, scheme_chunks in by_scheme.items():
        assert 8 <= len(scheme_chunks) <= 18, f"{scheme}: {len(scheme_chunks)} chunks"


def test_write_chunks_jsonl_roundtrip(tmp_path: Path):
    from src.ingest.chunker import write_chunks_jsonl

    chunks = _chunk_sample()
    out = tmp_path / "chunks.jsonl"
    write_chunks_jsonl(chunks, out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(chunks)
    row = json.loads(lines[0])
    assert row["scheme"] == MID_CAP_ENTRY.scheme
