"""
embedder.py  -- turn text into vectors.

An EMBEDDING is a list of numbers (here: 384 of them) that captures the
*meaning* of a piece of text. Texts with similar meaning get vectors that
point in similar directions. That's what lets us do "semantic search":
find chunks whose meaning is close to the question's meaning, even when they
share no exact keywords.

MODEL: BAAI/bge-small-en-v1.5
  - small + fast + strong for its size, runs fine on CPU.
  - IMPORTANT QUIRK: bge models were trained so that QUERIES should be prefixed
    with a short instruction, while passages/documents are embedded as-is.
    We honor that with embed_query() vs embed_documents().

We L2-normalize all vectors (length = 1). With normalized vectors, the dot
product EQUALS cosine similarity, which is what we want for semantic search.
"""

from __future__ import annotations

import numpy as np

# Recommended retrieval instruction for bge-*-en-v1.5 query embeddings.
_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        # Imported lazily so the heavy torch/sentence-transformers stack only
        # loads when embeddings are actually needed.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed passages/chunks. Returns shape (n, dim), L2-normalized."""
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            batch_size=32,
            show_progress_bar=False,
        ).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a user question (with the bge query instruction). Shape (dim,)."""
        vec = self.model.encode(
            _QUERY_INSTRUCTION + text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vec.astype(np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two vectors, in [-1, 1].
    1.0 = identical direction (same meaning), 0 = unrelated, -1 = opposite.
    For already-normalized vectors this is just the dot product, but we
    normalize here too so it's correct for any input.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-10
    return float(np.dot(a, b) / denom)
