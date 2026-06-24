"""
retriever.py  -- the heart of the QUERY pipeline.

Given a user question, return the most relevant chunks. Supports:

  * DENSE / SEMANTIC search  -- vector similarity in Qdrant (meaning-based).
  * SPARSE / KEYWORD search  -- BM25 over the text corpus (exact-term based).
  * HYBRID                   -- fuse both rankings with Reciprocal Rank Fusion
                                (RRF), then optionally RERANK with a cross-encoder.

WHY HYBRID?
  Dense search is great at meaning ("car" ~ "automobile") but can miss exact
  identifiers ("error code 0x80070005", product SKUs, rare names). BM25 nails
  exact terms but is blind to synonyms. Fusing both gives the best of each.

RECIPROCAL RANK FUSION:
  Each result list contributes 1 / (k + rank) to a chunk's combined score.
  Items ranked high in EITHER list bubble to the top. k=60 is the common
  default. RRF needs only ranks, not comparable raw scores -- which is why it's
  the go-to way to merge a cosine list with a BM25 list.
"""

from __future__ import annotations

import re

from app.embeddings import Embedder
from app.vectorstore import QdrantStore, StoredChunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class Retriever:
    def __init__(
        self,
        store: QdrantStore,
        embedder: Embedder,
        enable_hybrid: bool = True,
        reranker=None,
        rrf_k: int = 60,
    ):
        self.store = store
        self.embedder = embedder
        self.enable_hybrid = enable_hybrid
        self.reranker = reranker
        self.rrf_k = rrf_k

        # BM25 index is built lazily from the stored corpus and cached.
        self._bm25 = None
        self._bm25_chunks: list[StoredChunk] = []

    # ----- BM25 index (lazy) ---------------------------------------------
    def invalidate_cache(self) -> None:
        """Call after ingesting new content so BM25 rebuilds next query."""
        self._bm25 = None
        
        self._bm25_chunks = []

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        from rank_bm25 import BM25Okapi

        self._bm25_chunks = self.store.scroll_all()
        corpus = [_tokenize(c.text) for c in self._bm25_chunks]
        # BM25 needs at least one document; guard the empty case.
        self._bm25 = BM25Okapi(corpus) if corpus else None

    # ----- individual search strategies ----------------------------------
    def _dense_search(self, query: str, k: int, source_url: str | None) -> list[StoredChunk]:
        qvec = self.embedder.embed_query(query)
        return self.store.search(qvec, top_k=k, source_url=source_url)

    def _sparse_search(self, query: str, k: int, source_url: str | None) -> list[StoredChunk]:
        self._ensure_bm25()
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(
            zip(self._bm25_chunks, scores), key=lambda x: x[1], reverse=True
        )
        results: list[StoredChunk] = []
        for chunk, score in ranked:
            if source_url and chunk.source_url != source_url:
                continue
            c = StoredChunk(
                id=chunk.id, text=chunk.text, source_url=chunk.source_url,
                title=chunk.title, chunk_index=chunk.chunk_index, score=float(score),
            )
            results.append(c)
            if len(results) >= k:
                break
        return results

    # ----- fusion ---------------------------------------------------------
    def _rrf_fuse(
        self, dense: list[StoredChunk], sparse: list[StoredChunk]
    ) -> list[StoredChunk]:
        scores: dict[str, float] = {}
        by_id: dict[str, StoredChunk] = {}

        for ranking in (dense, sparse):
            for rank, chunk in enumerate(ranking):
                by_id[chunk.id] = chunk
                scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        fused = []
        for cid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            chunk = by_id[cid]
            chunk.score = score
            fused.append(chunk)
        return fused

    # ----- public API -----------------------------------------------------
    def retrieve(
        self, query: str, top_k: int = 5, source_url: str | None = None
    ) -> list[StoredChunk]:
        """
        Full retrieval pipeline:
          1. Pull a wider candidate pool (top_k * 4) from each strategy.
          2. Fuse (if hybrid) or use dense alone.
          3. Rerank with the cross-encoder (if enabled) for final precision.
          4. Return the top_k.
        """
        # SPEED OPTIMISATION: reduced candidate pool from top_k*4 (20 chunks)
        # to top_k*2 (10 chunks). The reranker cross-encoder scores each candidate
        # on CPU — fewer candidates = fewer inference passes = faster response.
        # Quality impact is minimal because hybrid search (BM25 + dense + RRF)
        # already surfaces the best chunks before reranking.
        candidate_k = max(top_k * 2, 8)

        dense = self._dense_search(query, candidate_k, source_url)

        if self.enable_hybrid:
            sparse = self._sparse_search(query, candidate_k, source_url)
            candidates = self._rrf_fuse(dense, sparse)
        else:
            candidates = dense

        if self.reranker is not None and candidates:
            return self.reranker.rerank(query, candidates, top_k)

        return candidates[:top_k]
