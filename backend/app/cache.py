"""
cache.py  -- optional Redis answer cache with version-based invalidation.

If REDIS_URL is set, identical questions (same question + filter) return a
cached answer instantly instead of re-running retrieval + LLM. If Redis is not
configured or unreachable, every method becomes a no-op so the app still works.

Version-based invalidation:
  - A single integer key "rag:version" lives in Redis.
  - Every cache key includes the current version number in its hash.
  - When ingest runs, increment_version() bumps the version atomically.
  - All old keys become unreachable instantly (wrong version in hash).
  - Old keys expire naturally after 24h TTL — no manual deletion needed.
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60 * 60 * 24  # cache answers for 24 hours
_VERSION_KEY = "rag:version"  # single integer key that tracks cache generation


class AnswerCache:
    def __init__(self, redis_url: str | None):
        self.client = None
        if not redis_url:
            return
        try:
            import redis

            self.client = redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            logger.info("Redis cache enabled")
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
        Returns the new version number.
        """
        if not self.client:
            return 1
        try:
            new_version = self.client.incr(_VERSION_KEY)
            logger.info("Cache version bumped to %d — all previous answers invalidated", new_version)
            return new_version
        except Exception:  # noqa: BLE001
            return 1

    # ── key generation ────────────────────────────────────────────────────────

    def _key(self, question: str, source_url: str | None) -> str:
        """
        Build a Redis key that includes the current version number.
        When the version changes, this produces a completely different hash,
        making all old cached answers unreachable without deleting anything.
        """
        version = self.get_version()
        raw = f"v{version}|{question.strip().lower()}|{source_url or ''}"
        return "rag:answer:" + hashlib.sha256(raw.encode()).hexdigest()

    # ── cache read / write ────────────────────────────────────────────────────

    def get(self, question: str, source_url: str | None) -> dict | None:
        if not self.client:
            return None
        try:
            raw = self.client.get(self._key(question, source_url))
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    def set(self, question: str, source_url: str | None, payload: dict) -> None:
        if not self.client:
            return
        try:
            self.client.setex(
                self._key(question, source_url), _TTL_SECONDS, json.dumps(payload)
            )
        except Exception:  # noqa: BLE001
            pass


cache = AnswerCache(settings.redis_url)
