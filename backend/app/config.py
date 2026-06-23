"""
Central configuration.

We use pydantic-settings so that every value can be overridden from a `.env`
file or real environment variables, with type validation for free. Think of
this as the single source of truth for "knobs" in the whole RAG system.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load from a local .env file; ignore unknown keys instead of crashing.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- LLM ----
    llm_provider: str = "groq"            # "groq" or "openai"
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # ---- Embeddings ----
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384              # bge-small outputs 384-dim vectors

    # ---- Reranker ----
    enable_reranker: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ---- Qdrant ----
    qdrant_url: Optional[str] = None      # empty -> embedded local mode
    qdrant_api_key: Optional[str] = None
    qdrant_path: str = "./qdrant_data"
    collection_name: str = "website_chunks"

    # ---- Chunking ----
    chunk_size: int = 800                 # max characters per chunk
    chunk_overlap: int = 150              # characters carried into next chunk

    # ---- Retrieval ----
    top_k: int = 5                        # how many chunks feed the LLM
    enable_hybrid: bool = True            # BM25 + vector fusion

    # ---- Crawling ----
    max_pages: int = 40
    request_timeout: int = 15
    crawl_delay: float = 0.5              # seconds between requests (politeness)

    # ---- Cache ----
    redis_url: Optional[str] = None       # empty -> caching disabled

    # ---- DotStark specific ----
    target_url: str = "https://dotstark.com"
    auto_ingest: bool = True


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so we build Settings only once per process."""
    return Settings()


# Convenient module-level singleton.
settings = get_settings()
