"""Tests for corpus fetcher (Phase 1.1)."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.ingest.fetcher import (
    FetchResult,
    SchemeEntry,
    USER_AGENT,
    fetch_all,
    fetch_page,
    is_sparse_html,
    load_scheme_urls,
    scheme_slug_from_url,
    validate_groww_url,
)

SAMPLE_HTML = b"<html><body><h1>HDFC Mid Cap Fund</h1>" + (b"x" * 2000) + b"</body></html>"

SAMPLE_ENTRY = SchemeEntry(
    scheme="HDFC Mid Cap Fund Direct Growth",
    category="mid-cap equity",
    url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
)


def test_scheme_slug_from_url():
    assert (
        scheme_slug_from_url(
            "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
        )
        == "hdfc-mid-cap-fund-direct-growth"
    )


def test_load_scheme_urls_has_five_entries():
    entries = load_scheme_urls()
    assert len(entries) == 5
    for entry in entries:
        assert validate_groww_url(entry.url)


def test_fetch_page_saves_html_and_metadata(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent", "").startswith("MF-RAG-Bot/")
        return httpx.Response(200, content=SAMPLE_HTML)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT},
    )

    result = fetch_page(SAMPLE_ENTRY, raw_dir=tmp_path, client=client)

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    assert result.html_size == len(SAMPLE_HTML)
    assert result.html_path.exists()
    assert result.meta_path.exists()
    assert result.html_path.read_bytes() == SAMPLE_HTML

    meta = json.loads(result.meta_path.read_text())
    assert meta["url"] == SAMPLE_ENTRY.url
    assert meta["scheme_name"] == SAMPLE_ENTRY.scheme
    assert meta["fetched_at"] == result.fetched_at
    assert meta["content_hash"] == result.content_hash
    assert meta["content_hash"] == hashlib.sha256(SAMPLE_HTML).hexdigest()
    assert result.fetch_method == "httpx"
    assert meta["fetch_method"] == "httpx"


def test_fetch_page_retries_on_failure(tmp_path: Path):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(503, content=b"unavailable")
        return httpx.Response(200, content=SAMPLE_HTML)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT},
    )

    with patch("src.ingest.fetcher.time.sleep"):
        result = fetch_page(
            SAMPLE_ENTRY,
            raw_dir=tmp_path,
            client=client,
            retries=3,
            retry_backoff_sec=0,
        )

    assert calls["count"] == 2
    assert result.status_code == 200


def test_is_sparse_html_detects_shell():
    shell = b"<html><body><div id='root'></div></body></html>"
    assert is_sparse_html(shell)


def test_fetch_page_rejects_sparse_html_without_playwright(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html></html>")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT},
    )

    with pytest.raises(RuntimeError, match="Sparse HTML"):
        fetch_page(
            SAMPLE_ENTRY,
            raw_dir=tmp_path,
            client=client,
            min_html_bytes=1024,
            use_playwright_fallback=False,
        )


def test_fetch_page_playwright_fallback(tmp_path: Path):
    sparse = b"<html><head><script>app()</script></head><body><div id='root'></div></body></html>"
    rich = b"<html><body><h1>HDFC Mid Cap Fund</h1><p>Expense ratio 0.76%</p>" + (b"x" * 2000) + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sparse)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT},
    )

    with patch("src.ingest.fetcher.fetch_with_playwright", return_value=rich):
        result = fetch_page(SAMPLE_ENTRY, raw_dir=tmp_path, client=client)

    assert result.fetch_method == "playwright"
    assert result.html_path.read_bytes() == rich
    meta = json.loads(result.meta_path.read_text())
    assert meta["fetch_method"] == "playwright"


def test_fetch_all_rate_limits(tmp_path: Path):
    entries = load_scheme_urls()[:2]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=SAMPLE_HTML)
    )
    real_client = httpx.Client

    def make_client(**kwargs):
        return real_client(
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    with patch("src.ingest.fetcher.httpx.Client", side_effect=make_client):
        with patch("src.ingest.fetcher.time.sleep") as mock_sleep:
            results = fetch_all(entries, raw_dir=tmp_path, rate_limit_delay_sec=1.0)

    assert len(results) == 2
    assert mock_sleep.call_count == 1


@pytest.mark.integration
def test_live_fetch_all_groww_pages(tmp_path: Path):
    """Integration: five Groww URLs return HTTP 200 and non-empty HTML."""
    results = fetch_all(raw_dir=tmp_path, rate_limit_delay_sec=1.0)
    assert len(results) == 5
    for result in results:
        assert result.status_code == 200
        assert result.html_size >= 1024
        assert result.html_path.parent.name == scheme_slug_from_url(result.url)
