"""
main.py  -- FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000

Interactive API docs are auto-generated at http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Website RAG Chatbot",
    description="Hand-built RAG over any website (no LangChain / LlamaIndex).",
    version="1.0.0",
)

# Allow the React dev server (Vite default port 5173) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _run_ingest():
    """Blocking ingest — runs in a thread so startup doesn't block."""
    try:
        from app.rag import get_pipeline

        pipe = get_pipeline()
        result = pipe.ingest(settings.target_url, reset=False)
        logger.info(
            "Auto-ingest complete: %d pages, %d chunks",
            result.pages_crawled,
            result.chunks_stored,
        )
    except Exception as exc:
        logger.error("Auto-ingest failed: %s", exc)


@app.on_event("startup")
async def startup_event():
    """Auto-ingest dotstark.com in the background so the server starts immediately."""
    if not settings.auto_ingest:
        return

    logger.info("Starting background auto-ingestion of %s", settings.target_url)
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, _run_ingest)


@app.get("/")
def root() -> dict:
    return {
        "name": "Website RAG Chatbot",
        "docs": "/docs",
        "endpoints": ["/api/ingest", "/api/chat", "/api/chat/stream", "/api/status"],
    }
