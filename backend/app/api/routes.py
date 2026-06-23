"""
routes.py  -- the HTTP surface of the RAG system.

Endpoints:
  POST /api/ingest        -> crawl + index a website
  POST /api/chat          -> ask a question, get a full answer + sources
  POST /api/chat/stream   -> ask a question, stream the answer token-by-token (SSE)
  GET  /api/status        -> index + config info
  GET  /api/health        -> liveness probe

Heavy work (crawling, model loading) is delegated to the RAGPipeline singleton.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.cache import cache
from app.config import settings
from app.rag import get_pipeline
from app.schemas import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    pipe = get_pipeline()
    return StatusResponse(
        collection=settings.collection_name,
        indexed_chunks=pipe.store.count(),
        embedding_model=settings.embedding_model,
        llm_provider=settings.llm_provider,
        hybrid_search=settings.enable_hybrid,
        reranker=settings.enable_reranker,
    )


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    pipe = get_pipeline()
    try:
        result = pipe.ingest(req.url, max_pages=req.max_pages, reset=req.reset)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return IngestResponse(
        url=result.url,
        pages_crawled=result.pages_crawled,
        chunks_stored=result.chunks_stored,
        message=(
            f"Indexed {result.chunks_stored} chunks from {result.pages_crawled} pages."
            if result.chunks_stored
            else "No content was indexed. The site may be JS-rendered or blocked."
        ),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # 1. Cache hit?
    cached = cache.get(req.question, req.source_url)
    if cached:
        return ChatResponse(**cached, cached=True)

    # 2. Run the RAG query pipeline.
    pipe = get_pipeline()
    try:
        result = pipe.answer(req.question, top_k=req.top_k, source_url=req.source_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = {"answer": result.answer, "sources": result.sources}
    cache.set(req.question, req.source_url, payload)
    return ChatResponse(**payload, cached=False)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """
    Server-Sent Events stream. Event protocol:
      event: sources  -> JSON list of sources (sent first)
      event: token    -> one answer fragment (sent many times)
      event: done     -> end of stream

    Cache behaviour:
      - On cache HIT  : answer is replayed token-by-token from Redis (no Qdrant, no LLM)
      - On cache MISS : full RAG pipeline runs, result saved to Redis for 24 hours
    """
    pipe = get_pipeline()

    def event_generator():
        try:
            # ── 1. CACHE HIT: serve answer from Redis ────────────────────────
            cached = cache.get(req.question, req.source_url)
            if cached:
                logger.info("Cache HIT for question: %s", req.question[:60])
                yield f"event: sources\ndata: {json.dumps(cached['sources'])}\n\n"
                # Replay the full answer as a single token so the UI streams it.
                yield f"event: token\ndata: {json.dumps(cached['answer'])}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            # ── 2. CACHE MISS: run full RAG pipeline ─────────────────────────
            logger.info("Cache MISS for question: %s", req.question[:60])
            token_iter, sources = pipe.answer_stream(
                req.question, top_k=req.top_k, source_url=req.source_url
            )
            # Send sources up front so the UI can show citations immediately.
            yield f"event: sources\ndata: {json.dumps(sources)}\n\n"

            full = []
            for token in token_iter:
                full.append(token)
                yield f"event: token\ndata: {json.dumps(token)}\n\n"

            # Save assembled answer to Redis (expires in 24 hours).
            cache.set(
                req.question, req.source_url,
                {"answer": "".join(full), "sources": sources},
            )
            yield "event: done\ndata: {}\n\n"

        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming failed")
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
