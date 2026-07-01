"""
cache.py  -- two-layer Redis answer cache with version-based invalidation.

LAYER 1  (exact cache)  --  key = hash(version + question)
  Skips everything: Qdrant, reranker, AND LLM.
  HIT condition: exact same question asked again.
  Speed on hit: ~50ms.

LAYER 2  (LLM cache)  --  key = hash(version + question + chunk_ids)
  Skips only the LLM. Qdrant + reranker still run every time.
  HIT condition: Qdrant returns the same chunks for a similar question.
  Speed on hit: ~400ms (Qdrant + reranker run, LLM skipped).

VERSION-BASED INVALIDATION:
  A single integer "rag:version" lives in Redis.
  Both layer keys include the version.
  When ingest runs → increment_version() bumps it atomically.
  All old cached answers become unreachable instantly.
  Old keys expire naturally after their TTL — no manual deletion needed.

GRACEFUL DEGRADATION:
  If Redis is not configured or unreachable, every method is a no-op.
  The app works perfectly without Redis — just slower.
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS      = 60 * 60 * 24  # both layers: cache answers for 24 hours
_VERSION_KEY      = "rag:version"  # single integer key tracking cache generation


class AnswerCache:
    def __init__(self, redis_url: str | None):
        self.client = None
        if not redis_url:
            return
        try:
            import redis
            self.client = redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            logger.info("Redis cache enabled (two-layer: exact + LLM)")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis unavailable, caching disabled: %s", exc)
            self.client = None

    # ── version management ────────────────────────────────────────────────────

    def get_version(self) -> int:
        """Return current cache version. Defaults to 1 if Redis is unavailable."""
        if not self.client:
            return 1
        try:
            return int(self.client.get(_VERSION_KEY) or 1)
        except Exception:  # noqa: BLE001
            return 1

    def increment_version(self) -> int:
        """
        Bump the cache version by 1. Called after every ingest.
        Redis INCR is atomic — safe even if two ingests run simultaneously.
        Both Layer 1 and Layer 2 keys include version — both invalidated at once.
        Returns the new version number.
        """
        if not self.client:
            return 1
        try:
            new_version = self.client.incr(_VERSION_KEY)
            logger.info(
                "Cache version bumped to %d — all Layer 1 + Layer 2 answers invalidated",
                new_version,
            )
            return new_version
        except Exception:  # noqa: BLE001
            return 1

    # ── key builders ──────────────────────────────────────────────────────────

    def _layer1_key(self, question: str, source_url: str | None) -> str:
        """
        LAYER 1 key — based on version + question only.
        Changes when: version bumps (ingest ran).
        Prefix: rag:answer:
        """
        version = self.get_version()
        raw = f"v{version}|{question.strip().lower()}|{source_url or ''}"
        return "rag:answer:" + hashlib.sha256(raw.encode()).hexdigest()

    def _layer2_key(self, question: str, chunk_ids: list[str], source_url: str | None) -> str:
        """
        LAYER 2 key — based on version + question + chunk IDs returned by Qdrant.
        Changes when: version bumps OR Qdrant returns different chunks.
        Including chunk IDs ensures the cached LLM answer matches the
        exact context that was used to generate it.
        Prefix: rag:llm:
        """
        version = self.get_version()
        # Sort chunk IDs so order doesn't matter — same set = same key.
        chunks_part = "|".join(sorted(chunk_ids))
        raw = f"v{version}|{question.strip().lower()}|{source_url or ''}|{chunks_part}"
        return "rag:llm:" + hashlib.sha256(raw.encode()).hexdigest()

    def _semantic_key(self, chunk_ids: list[str], source_url: str | None) -> str:
        """
        SEMANTIC cache key — based ONLY on chunk IDs (no question text).
        Different questions that retrieve the same chunks = same cache key.
        This is true semantic caching: meaning-based, not text-based.
        Prefix: rag:semantic:
        """
        version = self.get_version()
        chunks_part = "|".join(sorted(chunk_ids))
        raw = f"v{version}|{source_url or ''}|{chunks_part}"
        return "rag:semantic:" + hashlib.sha256(raw.encode()).hexdigest()

    # ── LAYER 1: exact cache (question only) ──────────────────────────────────

    def get(self, question: str, source_url: str | None) -> dict | None:
        """Layer 1 read — check before Qdrant. Skips everything on hit."""
        if not self.client:
            return None
        try:
            raw = self.client.get(self._layer1_key(question, source_url))
            if raw:
                logger.debug("Layer 1 cache HIT for: %s", question[:60])
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def set(self, question: str, source_url: str | None, payload: dict) -> None:
        """Layer 1 write — store after full RAG pipeline completes."""
        if not self.client:
            return
        try:
            self.client.setex(
                self._layer1_key(question, source_url),
                _TTL_SECONDS,
                json.dumps(payload),
            )
            logger.debug("Layer 1 cache SET for: %s", question[:60])
        except Exception:  # noqa: BLE001
            pass

    # ── LAYER 2: LLM cache (question + chunk IDs) ─────────────────────────────

    def get_llm(
        self,
        question: str,
        chunk_ids: list[str],
        source_url: str | None = None,
    ) -> dict | None:
        """
        Layer 2 read — check AFTER Qdrant but BEFORE LLM.
        Returns cached answer if same question retrieved same chunks before.
        Skips only the LLM on hit (~800ms saved).
        """
        if not self.client:
            return None
        try:
            raw = self.client.get(self._layer2_key(question, chunk_ids, source_url))
            if raw:
                logger.info("Layer 2 (LLM) cache HIT for: %s", question[:60])
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def set_llm(
        self,
        question: str,
        chunk_ids: list[str],
        payload: dict,
        source_url: str | None = None,
    ) -> None:
        """
        Layer 2 write — store the LLM answer keyed by question + chunk IDs.
        Called after LLM generates answer, so next time same chunks appear
        the LLM call is skipped entirely.
        """
        if not self.client:
            return
        try:
            self.client.setex(
                self._layer2_key(question, chunk_ids, source_url),
                _TTL_SECONDS,
                json.dumps(payload),
            )
            logger.debug("Layer 2 (LLM) cache SET for: %s", question[:60])
        except Exception:  # noqa: BLE001
            pass

    # ── LAYER 3: Semantic cache (chunk IDs only, no question text) ────────────

    def get_semantic(
        self,
        chunk_ids: list[str],
        source_url: str | None = None,
    ) -> dict | None:
        """
        Semantic cache read — check AFTER Qdrant but BEFORE LLM.
        Returns cached answer if these exact chunks were seen before,
        regardless of how the question was phrased.
        True semantic caching: meaning-based, not text-based.
        """
        if not self.client:
            return None
        try:
            raw = self.client.get(self._semantic_key(chunk_ids, source_url))
            if raw:
                logger.info("Semantic cache HIT for chunks: %s", chunk_ids[:3])
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def set_semantic(
        self,
        chunk_ids: list[str],
        payload: dict,
        source_url: str | None = None,
    ) -> None:
        """
        Semantic cache write — store the LLM answer keyed only by chunk IDs.
        Any future question that retrieves these same chunks will hit this cache,
        even if the question wording is completely different.
        """
        if not self.client:
            return
        try:
            self.client.setex(
                self._semantic_key(chunk_ids, source_url),
                _TTL_SECONDS,
                json.dumps(payload),
            )
            logger.debug("Semantic cache SET for chunks: %s", chunk_ids[:3])
        except Exception:  # noqa: BLE001
            pass


cache = AnswerCache(settings.redis_url)
