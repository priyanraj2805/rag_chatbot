"""
cache.py  -- optional Redis answer cache.

If REDIS_URL is set, identical questions (same question + filter) return a
cached answer instantly instead of re-running retrieval + LLM. If Redis is not
configured or unreachable, every method becomes a no-op so the app still works.
This "graceful degradation" pattern keeps an optional dependency truly optional.
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60 * 60 * 24  # cache answers for 24 hours


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

    @staticmethod
    def _key(question: str, source_url: str | None) -> str:
        raw = f"{question.strip().lower()}|{source_url or ''}"
        return "rag:answer:" + hashlib.sha256(raw.encode()).hexdigest()

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
