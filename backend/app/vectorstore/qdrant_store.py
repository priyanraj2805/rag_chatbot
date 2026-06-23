"""
qdrant_store.py  -- persistence + vector search layer (Qdrant).

A VECTOR DATABASE stores our chunk vectors and, given a query vector, returns
the nearest ones FAST (approximate nearest neighbor / HNSW index). Without it
you'd compute cosine similarity against every chunk by hand (fine for 100
chunks, hopeless for 1,000,000).

We support two modes via config:
  - Embedded/local mode (default): QdrantClient(path=...) -- no Docker, data
    is persisted to a local folder. Great for development.
  - Server/cloud mode: QdrantClient(url=..., api_key=...) -- for production.

Each stored point carries a PAYLOAD (metadata): the chunk text, its source URL,
the page title, and a chunk index. Payload is what powers citations and
metadata filtering.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)


@dataclass
class StoredChunk:
    id: str
    text: str
    source_url: str
    title: str
    chunk_index: int
    score: float = 0.0  # populated by search results


class QdrantStore:
    def __init__(
        self,
        collection_name: str,
        embedding_dim: int,
        path: str | None = "./qdrant_data",
        url: str | None = None,
        api_key: str | None = None,
    ):
        if url:
            self.client = QdrantClient(url=url, api_key=api_key, timeout=60)
        else:
            # Embedded mode -- persists to a local folder, no server needed.
            self.client = QdrantClient(path=path)
        self.collection = collection_name
        self.dim = embedding_dim

    # ----- collection management -----------------------------------------
    def ensure_collection(self) -> None:
        """Create the collection if it doesn't already exist."""
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    def recreate_collection(self) -> None:
        """Drop and recreate -- used when re-ingesting a site from scratch."""
        self.client.recreate_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )

    def count(self) -> int:
        try:
            return self.client.count(self.collection, exact=True).count
        except Exception:  # collection may not exist yet
            return 0

    # ----- writes ---------------------------------------------------------
    def upsert(
        self,
        vectors: np.ndarray,
        texts: list[str],
        source_url: str,
        title: str,
        start_index: int = 0,
    ) -> int:
        """Insert (or overwrite) chunk vectors + payloads. Returns count added."""
        points: list[PointStruct] = []
        for i, (vec, text) in enumerate(zip(vectors, texts)):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec.tolist(),
                    payload={
                        "text": text,
                        "source_url": source_url,
                        "title": title,
                        "chunk_index": start_index + i,
                    },
                )
            )
        if points:
            self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    # ----- reads ----------------------------------------------------------
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        source_url: str | None = None,
    ) -> list[StoredChunk]:
        """
        Return the `top_k` nearest chunks to the query vector.

        If `source_url` is given, results are restricted to that page/site
        (metadata filtering) -- handy when one Qdrant collection holds chunks
        from many different websites.
        """
        query_filter = None
        if source_url:
            query_filter = Filter(
                must=[FieldCondition(key="source_url", match=MatchValue(value=source_url))]
            )

        hits = self.client.search(
            collection_name=self.collection,
            query_vector=query_vector.tolist(),
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        return [self._to_chunk(h.payload, h.id, h.score) for h in hits]

    def scroll_all(self, batch_size: int = 256) -> list[StoredChunk]:
        """
        Stream every stored chunk (no vectors). Used to build the BM25 index
        for hybrid search, since BM25 needs the raw text corpus.
        """
        results: list[StoredChunk] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                results.append(self._to_chunk(p.payload, p.id, 0.0))
            if offset is None:
                break
        return results

    @staticmethod
    def _to_chunk(payload: dict, point_id, score: float) -> StoredChunk:
        return StoredChunk(
            id=str(point_id),
            text=payload.get("text", ""),
            source_url=payload.get("source_url", ""),
            title=payload.get("title", ""),
            chunk_index=payload.get("chunk_index", 0),
            score=float(score),
        )
