"""HTML parser for Groww scheme pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "meta", "link")
CHROME_TAGS = ("nav", "footer")

MAIN_CONTENT_SELECTORS = (
    "div.pw14ContentWrapper",
    "div.layout-main",
    "main",
    "article",
    "[role='main']",
)

HEADING_TAGS = ("h1", "h2", "h3", "h4")

FUND_LABELS = (
    "Expense ratio",
    "Exit load",
    "Minimum SIP",
    "Minimum investment",
    "Benchmark",
    "Riskometer",
    "NAV",
    "AUM",
    "Lock-in",
    "Fund size",
)


@dataclass(frozen=True)
class ParsedSection:
    title: str
    text: str


@dataclass
class ParsedDocument:
    """Structured text extracted from a scheme page."""

    title: str
    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    source_url: str = ""
    nav_value: str | None = None
    nav_date: str | None = None


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_nav_line(nav_value: str, nav_date: str | None = None) -> str:
    """Format NAV for fund-details text and dedicated nav chunks."""
    if nav_date:
        return f"NAV ₹{nav_value} (as on {nav_date})"
    return f"NAV ₹{nav_value}"


def extract_nav_from_next_data(html: str) -> tuple[str | None, str | None]:
    """
    Read latest NAV from Groww ``__NEXT_DATA__`` JSON embedded in scheme pages.

    Groww SSR exposes ``props.pageProps.mfServerSideData.nav`` and ``nav_date``.
    """
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None, None

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None, None

    mf_data = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("mfServerSideData", {})
    )
    nav = mf_data.get("nav")
    if nav is None:
        return None, None

    nav_date = mf_data.get("nav_date")
    return str(nav), str(nav_date) if nav_date else None


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag_name in CHROME_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()


def _find_main_container(soup: BeautifulSoup) -> Tag:
    for selector in MAIN_CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            return node

    body = soup.body
    if body is None:
        return soup
    return body


def _table_to_text(table: Tag) -> str:
    rows: list[str] = []
    for tr in table.find_all("tr"):
        cells = [
            _normalize_whitespace(cell.get_text(" ", strip=True))
            for cell in tr.find_all(["th", "td"])
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _heading_sections(container: Tag) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    headings = container.find_all(HEADING_TAGS)
    if not headings:
        return sections

    for heading in headings:
        title = _normalize_whitespace(heading.get_text(" ", strip=True))
        if not title:
            continue

        parts: list[str] = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in HEADING_TAGS:
                break
            if isinstance(sibling, Tag):
                if sibling.name == "table":
                    table_text = _table_to_text(sibling)
                    if table_text:
                        parts.append(table_text)
                else:
                    chunk = _normalize_whitespace(sibling.get_text(" ", strip=True))
                    if chunk:
                        parts.append(chunk)
            elif isinstance(sibling, NavigableString):
                chunk = _normalize_whitespace(str(sibling))
                if chunk:
                    parts.append(chunk)

        body = _normalize_whitespace("\n".join(parts))
        if body:
            sections.append(ParsedSection(title=title, text=body))

    return sections


def _extract_labeled_facts(container: Tag) -> list[str]:
    """Extract Groww-style label/value lines (e.g. 'Expense ratio 0.75%')."""
    facts: list[str] = []
    seen: set[str] = set()

    for label in FUND_LABELS:
        pattern = re.compile(rf"^{re.escape(label)}$", re.IGNORECASE)
        for node in container.find_all(string=pattern):
            parent = node.parent
            if parent is None:
                continue
            grandparent = parent.parent
            text = (
                grandparent.get_text(" ", strip=True)
                if grandparent is not None
                else parent.get_text(" ", strip=True)
            )
            text = _normalize_whitespace(text)
            if text and text not in seen:
                seen.add(text)
                facts.append(text)

    return facts


def _collect_tables(container: Tag) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for table in container.find_all("table"):
        table_text = _table_to_text(table)
        if table_text and table_text not in seen:
            seen.add(table_text)
            tables.append(table_text)
    return tables


def parse_html(html: str | bytes, *, source_url: str = "") -> ParsedDocument:
    """
    Parse Groww scheme HTML into clean text for chunking.

    Strips scripts/navigation chrome, preserves headings, paragraphs, and tables.
    """
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")

    nav_value, nav_date = extract_nav_from_next_data(html)

    soup = BeautifulSoup(html, "html.parser")
    _remove_noise(soup)

    title_tag = soup.find("title")
    page_title = _normalize_whitespace(title_tag.get_text(" ", strip=True)) if title_tag else ""

    container = _find_main_container(soup)
    sections = _heading_sections(container)
    tables = _collect_tables(container)
    labeled_facts = _extract_labeled_facts(container)
    if nav_value is not None:
        nav_line = format_nav_line(nav_value, nav_date)
        if nav_line not in labeled_facts:
            labeled_facts.insert(0, nav_line)

    blocks: list[str] = []
    h1 = container.find("h1")
    if h1 is not None:
        h1_text = _normalize_whitespace(h1.get_text(" ", strip=True))
        if h1_text:
            blocks.append(h1_text)

    if labeled_facts:
        blocks.append("## Fund details\n" + "\n".join(labeled_facts))

    for section in sections:
        blocks.append(f"## {section.title}\n{section.text}")

    for index, table in enumerate(tables, start=1):
        blocks.append(f"## Table {index}\n{table}")

    # Fallback when headings are sparse: full container text
    if len(blocks) <= 1:
        fallback = _normalize_whitespace(container.get_text("\n", strip=True))
        if fallback:
            blocks.append(fallback)

    text = _normalize_whitespace("\n\n".join(blocks))
    doc_title = h1.get_text(" ", strip=True) if h1 is not None else page_title

    return ParsedDocument(
        title=_normalize_whitespace(doc_title),
        text=text,
        sections=sections,
        tables=tables,
        source_url=source_url,
        nav_value=nav_value,
        nav_date=nav_date,
    )


def parse_html_file(path: Path, *, source_url: str = "") -> ParsedDocument:
    """Parse HTML from a saved raw snapshot file."""
    html = path.read_bytes()
    return parse_html(html, source_url=source_url)
