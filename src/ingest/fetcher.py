"""HTTP fetcher for Groww scheme pages (corpus ingestion)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from src.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "MF-RAG-Bot/1.0 (educational mutual-fund FAQ corpus; "
    "+https://groww.in/mutual-funds)"
)
DEFAULT_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SEC = 2.0
DEFAULT_RATE_LIMIT_DELAY_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 30.0
MIN_HTML_BYTES = 1024
MIN_TEXT_CHARS = 500
PLAYWRIGHT_TIMEOUT_MS = 30_000

FetchMethod = Literal["httpx", "playwright"]


@dataclass(frozen=True)
class SchemeEntry:
    scheme: str
    category: str
    url: str

    @property
    def slug(self) -> str:
        return scheme_slug_from_url(self.url)


@dataclass(frozen=True)
class FetchResult:
    scheme: str
    category: str
    url: str
    html_path: Path
    meta_path: Path
    fetched_at: str
    content_hash: str
    status_code: int
    html_size: int
    fetch_method: FetchMethod = "httpx"


def scheme_slug_from_url(url: str) -> str:
    """Derive directory slug from a Groww scheme URL."""
    return url.rstrip("/").split("/")[-1]


def load_scheme_urls(urls_file: Path | None = None) -> list[SchemeEntry]:
    """Load the five corpus URLs from ``data/urls.json``."""
    path = urls_file or settings.urls_file
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        SchemeEntry(
            scheme=item["scheme"],
            category=item["category"],
            url=item["url"],
        )
        for item in raw
    ]
    if len(entries) != 5:
        raise ValueError(f"Expected 5 scheme URLs in {path}, found {len(entries)}")
    return entries


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_metadata(meta_path: Path, metadata: dict[str, Any]) -> None:
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _visible_text_length(content: bytes) -> int:
    """Estimate visible text length after stripping scripts/styles."""
    html = content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return len(soup.get_text(" ", strip=True))


def is_sparse_html(
    content: bytes,
    *,
    min_html_bytes: int = MIN_HTML_BYTES,
    min_text_chars: int = MIN_TEXT_CHARS,
) -> bool:
    """Return True when httpx HTML is likely incomplete (e.g. JS-rendered shell)."""
    if len(content) < min_html_bytes:
        return True
    return _visible_text_length(content) < min_text_chars


def fetch_with_playwright(
    url: str,
    *,
    timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS,
) -> bytes:
    """
    Fetch fully rendered HTML using headless Chromium.

    Requires: ``pip install playwright`` and ``playwright install chromium``.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && "
            "playwright install chromium"
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            html = page.content()
        finally:
            browser.close()

    return html.encode("utf-8")


def _fetch_with_httpx(
    entry: SchemeEntry,
    client: httpx.Client,
    *,
    retries: int,
    retry_backoff_sec: float,
) -> tuple[bytes, int]:
    last_error: Exception | None = None
    response: httpx.Response | None = None

    for attempt in range(1, retries + 1):
        try:
            response = client.get(entry.url)
            if response.status_code == 200:
                return response.content, response.status_code
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
        except httpx.HTTPError as exc:
            last_error = exc

        if attempt < retries:
            sleep_sec = retry_backoff_sec * attempt
            logger.warning(
                "Fetch attempt %s/%s failed for %s: %s; retrying in %ss",
                attempt,
                retries,
                entry.url,
                last_error,
                sleep_sec,
            )
            time.sleep(sleep_sec)

    status = response.status_code if response is not None else "n/a"
    raise RuntimeError(
        f"Failed to fetch {entry.url} after {retries} attempts "
        f"(last status: {status}): {last_error}"
    )


def _resolve_html_content(
    entry: SchemeEntry,
    client: httpx.Client,
    *,
    retries: int,
    retry_backoff_sec: float,
    min_html_bytes: int,
    min_text_chars: int,
    use_playwright_fallback: bool,
) -> tuple[bytes, int, FetchMethod]:
    content, status_code = _fetch_with_httpx(
        entry,
        client,
        retries=retries,
        retry_backoff_sec=retry_backoff_sec,
    )

    if not is_sparse_html(
        content,
        min_html_bytes=min_html_bytes,
        min_text_chars=min_text_chars,
    ):
        return content, status_code, "httpx"

    logger.warning(
        "Sparse httpx HTML for %s (%s bytes, %s visible chars); trying Playwright",
        entry.url,
        len(content),
        _visible_text_length(content),
    )

    if not use_playwright_fallback:
        raise RuntimeError(
            f"Sparse HTML for {entry.url}: {len(content)} bytes. "
            "Enable Playwright fallback or check the page."
        )

    playwright_content = fetch_with_playwright(entry.url)
    if is_sparse_html(
        playwright_content,
        min_html_bytes=min_html_bytes,
        min_text_chars=min_text_chars,
    ):
        raise RuntimeError(
            f"Sparse HTML after Playwright for {entry.url}: "
            f"{len(playwright_content)} bytes, "
            f"{_visible_text_length(playwright_content)} visible chars."
        )

    return playwright_content, status_code, "playwright"


def fetch_page(
    entry: SchemeEntry,
    *,
    raw_dir: Path | None = None,
    client: httpx.Client | None = None,
    retries: int = DEFAULT_RETRIES,
    retry_backoff_sec: float = DEFAULT_RETRY_BACKOFF_SEC,
    min_html_bytes: int = MIN_HTML_BYTES,
    min_text_chars: int = MIN_TEXT_CHARS,
    use_playwright_fallback: bool = True,
) -> FetchResult:
    """
    Fetch a single scheme page and persist HTML + metadata.

    Uses httpx first; falls back to Playwright when HTML is sparse (Phase 1.2).

    Saves:
      ``data/raw/<scheme_slug>/<timestamp>.html``
      ``data/raw/<scheme_slug>/<timestamp>.meta.json``
    """
    base_dir = raw_dir or settings.raw_data_dir
    scheme_dir = base_dir / entry.slug
    scheme_dir.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(timezone.utc).isoformat()
    timestamp = _utc_timestamp()
    html_path = scheme_dir / f"{timestamp}.html"
    meta_path = scheme_dir / f"{timestamp}.meta.json"

    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=DEFAULT_TIMEOUT_SEC,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    try:
        content, status_code, fetch_method = _resolve_html_content(
            entry,
            client,
            retries=retries,
            retry_backoff_sec=retry_backoff_sec,
            min_html_bytes=min_html_bytes,
            min_text_chars=min_text_chars,
            use_playwright_fallback=use_playwright_fallback,
        )
    finally:
        if owns_client and client is not None:
            client.close()

    html_path.write_bytes(content)
    content_hash = _content_hash(content)

    metadata = {
        "scheme": entry.scheme,
        "category": entry.category,
        "url": entry.url,
        "scheme_name": entry.scheme,
        "fetched_at": fetched_at,
        "content_hash": content_hash,
        "status_code": status_code,
        "fetch_method": fetch_method,
        "html_path": str(html_path),
        "html_size": len(content),
        "visible_text_chars": _visible_text_length(content),
    }
    _write_metadata(meta_path, metadata)

    logger.info(
        "Fetched %s via %s -> %s (%s bytes)",
        entry.url,
        fetch_method,
        html_path,
        len(content),
    )

    return FetchResult(
        scheme=entry.scheme,
        category=entry.category,
        url=entry.url,
        html_path=html_path,
        meta_path=meta_path,
        fetched_at=fetched_at,
        content_hash=content_hash,
        status_code=status_code,
        html_size=len(content),
        fetch_method=fetch_method,
    )


def fetch_all(
    entries: list[SchemeEntry] | None = None,
    *,
    raw_dir: Path | None = None,
    rate_limit_delay_sec: float = DEFAULT_RATE_LIMIT_DELAY_SEC,
    retries: int = DEFAULT_RETRIES,
    use_playwright_fallback: bool = True,
) -> list[FetchResult]:
    """
    Fetch all corpus URLs sequentially with rate limiting.

    Only URLs from ``urls.json`` are fetched; no link discovery.
    """
    schemes = entries if entries is not None else load_scheme_urls()
    results: list[FetchResult] = []

    with httpx.Client(
        timeout=DEFAULT_TIMEOUT_SEC,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        for index, entry in enumerate(schemes):
            if index > 0 and rate_limit_delay_sec > 0:
                time.sleep(rate_limit_delay_sec)
            results.append(
                fetch_page(
                    entry,
                    raw_dir=raw_dir,
                    client=client,
                    retries=retries,
                    use_playwright_fallback=use_playwright_fallback,
                )
            )

    return results


def validate_groww_url(url: str) -> bool:
    """Ensure URL is a Groww mutual-fund scheme page (corpus allowlist pattern)."""
    pattern = re.compile(
        r"^https://groww\.in/mutual-funds/hdfc-[a-z0-9-]+$"
    )
    return bool(pattern.match(url.rstrip("/")))
