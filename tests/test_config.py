"""Phase 0 config and urls.json checks."""

import json
from pathlib import Path

from src.config import PROJECT_ROOT, get_settings


def test_settings_load_with_defaults():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.llm_model == "llama-3.3-70b-versatile"
    assert settings.top_k == 5
    assert settings.similarity_threshold == 0.65


def test_relative_paths_resolve_from_project_root(monkeypatch, tmp_path):
    """Paths from .env must not depend on the process working directory."""
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.vector_db_path.is_absolute()
    assert settings.vector_db_path == (PROJECT_ROOT / "data" / "chroma").resolve()
    assert settings.processed_data_dir == (PROJECT_ROOT / "data" / "processed").resolve()


def test_urls_json_has_five_groww_schemes():
    urls_path = PROJECT_ROOT / "data" / "urls.json"
    schemes = json.loads(urls_path.read_text(encoding="utf-8"))
    assert len(schemes) == 5
    for entry in schemes:
        assert entry["scheme"]
        assert entry["category"]
        assert entry["url"].startswith("https://groww.in/mutual-funds/")
