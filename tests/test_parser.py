"""Tests for HTML parser (Phase 1.3)."""

from pathlib import Path

from src.ingest.parser import extract_nav_from_next_data, format_nav_line, parse_html, parse_html_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURES_DIR / "sample_groww.html").read_text(encoding="utf-8")


def test_parse_html_removes_scripts_and_nav():
    doc = parse_html(SAMPLE_HTML, source_url="https://groww.in/mutual-funds/test")
    assert "window.__APP__" not in doc.text
    assert "Stocks ETFs IPOs Login" not in doc.text
    assert "Copyright Groww" not in doc.text


def test_parse_html_extracts_nav_from_next_data():
    html = """
    <html><body><div class="pw14ContentWrapper"><h1>Test Fund</h1></div>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"mfServerSideData":{"nav":226.765,"nav_date":"30-Jun-2026"}}}}
    </script></body></html>
    """
    doc = parse_html(html)
    assert doc.nav_value == "226.765"
    assert doc.nav_date == "30-Jun-2026"
    assert "NAV ₹226.765 (as on 30-Jun-2026)" in doc.text


def test_extract_nav_from_next_data_missing_payload():
    assert extract_nav_from_next_data("<html><body></body></html>") == (None, None)


def test_format_nav_line_without_date():
    assert format_nav_line("1211.25") == "NAV ₹1211.25"


def test_parse_html_extracts_fund_facts():
    doc = parse_html(SAMPLE_HTML)
    assert "HDFC Mid Cap Fund Direct Growth" in doc.text
    assert "Expense ratio: 0.76%" in doc.text
    assert "Minimum SIP" in doc.text
    assert "Exit load" in doc.text
    assert "NIFTY Midcap 150 Index" in doc.text
    assert doc.nav_value == "226.765"
    assert "NAV ₹226.765 (as on 30-Jun-2026)" in doc.text


def test_parse_html_extracts_labeled_facts_from_groww_style():
    html = """
    <html><body><div class="pw14ContentWrapper">
      <div><div>Expense ratio</div><div>0.75%</div></div>
      <div><div>Minimum SIP</div><div>₹100</div></div>
    </div></body></html>
    """
    doc = parse_html(html)
    assert "Expense ratio 0.75%" in doc.text
    assert "Minimum SIP ₹100" in doc.text


def test_parse_html_extracts_sections():
    doc = parse_html(SAMPLE_HTML)
    titles = [section.title for section in doc.sections]
    assert "Fund basics" in titles
    assert "Investment objective" in titles


def test_parse_html_extracts_tables():
    doc = parse_html(SAMPLE_HTML)
    assert len(doc.tables) >= 1
    assert "Exit load" in doc.tables[0]
    assert "Benchmark" in doc.tables[0]


def test_parse_html_file():
    path = FIXTURES_DIR / "sample_groww.html"
    doc = parse_html_file(path, source_url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth")
    assert doc.source_url.endswith("hdfc-mid-cap-fund-direct-growth")
    assert doc.title == "HDFC Mid Cap Fund Direct Growth"


def test_parse_html_handles_js_shell():
    shell = "<html><head><script>render()</script></head><body><div id='root'></div></body></html>"
    doc = parse_html(shell)
    assert doc.text == "" or len(doc.text) < 50


def test_parse_pipeline_on_rich_fetcher_sample():
    """Parser should extract facts from HTML shaped like a successful httpx fetch."""
    rich_html = (
        "<html><body><div class='pw14ContentWrapper'>"
        "<h1>HDFC Mid Cap Fund Direct Growth</h1>"
        "<h2>Fund Info</h2><p>Expense ratio: 0.76%</p>"
        "<table><tr><th>Exit load</th><td>1%</td></tr></table>"
        "</div></body></html>"
    )
    doc = parse_html(rich_html)
    assert "Expense ratio" in doc.text
    assert "Exit load" in doc.text
