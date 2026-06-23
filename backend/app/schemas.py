"""Pydantic request/response models for the API (validation + docs)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    url: str = Field(..., description="Starting URL of the website to crawl")
    max_pages: int | None = Field(None, ge=1, le=500)
    reset: bool = Field(False, description="Wipe existing index before crawling")


class IngestResponse(BaseModel):
    url: str
    pages_crawled: int
    chunks_stored: int
    message: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(None, ge=1, le=20)
    source_url: str | None = Field(
        None, description="Restrict retrieval to one page's URL (metadata filter)"
    )


class Source(BaseModel):
    n: int
    title: str
    url: str
    score: float
    preview: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    cached: bool = False


class StatusResponse(BaseModel):
    collection: str
    indexed_chunks: int
    embedding_model: str
    llm_provider: str
    hybrid_search: bool
    reranker: bool
