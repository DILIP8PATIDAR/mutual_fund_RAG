"""FastAPI app: /api/chat, /api/health, /api/schemes.

Pipeline (Phase 3): guard -> classify -> (refuse | retrieve -> generate ->
validate). The Streamlit UI in ``ui/streamlit_app.py`` calls the same
``process_chat()`` function directly.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.chat_service import ChatRequest, ChatResponse, process_chat
from src.index.vector_store import collection_count
from src.ingest.fetcher import load_scheme_urls
from src.ingest.pipeline import get_ingest_health_info
from src.rag.generator import DISCLAIMER

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    index_loaded: bool
    chunk_count: int
    last_ingest_at: str | None = None
    ingest_stale: bool = True
    ingest_status: str | None = None


class SchemeItem(BaseModel):
    scheme: str
    category: str
    url: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mutual Fund FAQ Assistant",
        description="Facts-only RAG over five HDFC Groww scheme pages.",
        version="0.4.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "Mutual Fund FAQ Assistant API",
            "docs": "/docs",
            "disclaimer": DISCLAIMER,
            "ui": "streamlit run ui/streamlit_app.py",
        }

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        try:
            count = collection_count()
        except Exception:
            logger.exception("Health check failed to read collection")
            count = 0
        ingest_info = get_ingest_health_info()
        index_loaded = count > 0
        status = "ok"
        if not index_loaded:
            status = "degraded"
        elif ingest_info["ingest_stale"]:
            status = "degraded"
        return HealthResponse(
            status=status,
            index_loaded=index_loaded,
            chunk_count=count,
            last_ingest_at=ingest_info["last_ingest_at"],
            ingest_stale=ingest_info["ingest_stale"],
            ingest_status=ingest_info["ingest_status"],
        )

    @app.get("/api/schemes", response_model=list[SchemeItem])
    def schemes() -> list[SchemeItem]:
        return [
            SchemeItem(scheme=e.scheme, category=e.category, url=e.url)
            for e in load_scheme_urls()
        ]

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        return process_chat(request.message)

    return app


app = create_app()
