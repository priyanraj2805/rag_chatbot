"""
reranker.py  -- second-stage precision ranking with a cross-encoder.

THE TWO-STAGE RETRIEVAL PATTERN (industry standard):
  1. RETRIEVE (cheap, recall-focused): vector + BM25 search over the whole
     corpus pulls, say, the top 20 candidate chunks. Fast but approximate --
     the embedding compares query and chunk SEPARATELY.
  2. RERANK (expensive, precision-focused): a CROSS-ENCODER reads the query
     and each candidate chunk TOGETHER and scores their true relevance. Much
     more accurate, but too slow to run over thousands of chunks -- so we only
     run it on the ~20 survivors from stage 1.

PyTorch 2.x note: CrossEncoder internally calls model.to(device) during
predict(), which fails with "Cannot copy out of meta tensor" when PyTorch
uses lazy/meta tensor initialisation. We bypass this by loading the
tokenizer and model directly via transformers with low_cpu_mem_usage=False,
which forces eager tensor allocation and avoids meta tensors entirely.
"""

from __future__ import annotations

import logging

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.vectorstore import StoredChunk

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            # Load tokenizer and model directly — bypasses CrossEncoder.predict()
            # which calls model.to(device) internally and triggers the meta-tensor
            # bug on PyTorch 2.x.
            # low_cpu_mem_usage=False forces eager tensor allocation (no meta tensors).
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                model_name,
                low_cpu_mem_usage=False,
            )
            self._model.eval()
            self._available = True
            logger.info("Reranker loaded: %s", model_name)
        except Exception as exc:
            # Graceful degradation: retrieval still works, just without reranking.
            logger.warning("Reranker failed to load (%s) -- running without it.", exc)
            self._tokenizer = None
            self._model = None
            self._available = False

    def rerank(
        self, query: str, chunks: list[StoredChunk], top_k: int
    ) -> list[StoredChunk]:
        if not chunks:
            return []

        # If the model didn't load, return chunks in their original vector order.
        if not self._available or self._model is None:
            return chunks[:top_k]

        # Score each (query, chunk_text) pair jointly using the cross-encoder.
        pairs = [(query, c.text) for c in chunks]
        with torch.no_grad():
            inputs = self._tokenizer(
                [p[0] for p in pairs],
                [p[1] for p in pairs],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            logits = self._model(**inputs).logits
            # For binary classification models, take the positive-class logit.
            if logits.shape[-1] == 1:
                scores = logits.squeeze(-1).tolist()
            else:
                scores = logits[:, 1].tolist()

        for chunk, score in zip(chunks, scores):
            chunk.score = float(score)

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]
