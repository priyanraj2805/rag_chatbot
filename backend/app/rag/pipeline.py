"""
pipeline.py  -- the conductor that wires every component into the two RAG flows.

INGESTION (offline):
    crawl -> clean -> chunk -> embed -> store in Qdrant

QUERY (online):
    question -> [greeting check] -> retrieve (hybrid + rerank) -> build prompt -> LLM -> answer
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import settings
from app.crawler import WebsiteCrawler
from app.embeddings import Embedder
from app.llm import LLMClient, build_messages
from app.processing import chunk_text, clean_text
from app.retrieval import Reranker, Retriever
from app.vectorstore import QdrantStore, StoredChunk

# ── query rewriting ───────────────────────────────────────────────────────────
# Vague pronouns like "it", "they", "this company" have no meaning on their own.
# The embedding model turns them into generic vectors that don't match any
# specific content in Qdrant. This system prompt rewrites vague queries into
# self-contained questions before retrieval.
_REWRITE_SYSTEM = (
    "You are a query rewriter for a DotStark company chatbot. "
    "Your ONLY job is to rewrite the user's question to be self-contained and specific. "
    "Rules:\n"
    "1. Replace vague pronouns ('it', 'they', 'this', 'the company') with 'DotStark'.\n"
    "2. If the question is already specific and clear, return it unchanged.\n"
    "3. Return ONLY the rewritten question — no explanation, no quotes, no extra text.\n"
    "Examples:\n"
    "  'when was it founded?' → 'When was DotStark founded?'\n"
    "  'what do they offer?' → 'What services does DotStark offer?'\n"
    "  'who is their CEO?' → 'Who is the CEO of DotStark?'\n"
    "  'What services does DotStark offer?' → 'What services does DotStark offer?'\n"
)

logger = logging.getLogger(__name__)

# ── small-talk / greeting detection ──────────────────────────────────────────
# If the user's message matches this pattern, we skip RAG retrieval entirely
# and let the LLM respond conversationally (no context injection needed).
_CHITCHAT_RE = re.compile(
    r"^\s*("
    r"hi+(\s+there)?|hello+(\s+there)?|hey+(\s+there)?|howdy|hiya|greetings|"
    r"good\s+(morning|afternoon|evening|night|day)|"
    r"what'?s\s*up|sup|yo|"
    r"how\s+are\s+you(\s+(doing|today))?|how\s+r\s+u|how\s+do\s+you\s+do|"
    r"thank(s|\s+you)(\s+so\s+much)?|thx|ty|"
    r"bye(\s+bye)?|goodbye|see\s+you|cya|"
    r"who\s+are\s+you|what\s+are\s+you|"
    r"help|what\s+can\s+you\s+do"
    r")\s*[!?.]*\s*$",
    re.IGNORECASE,
)

_CHITCHAT_SYSTEM = (
    "You are a friendly and helpful AI assistant for DotStark, a software "
    "development company specialising in Azure, CMS, AI, and web development services. "
    "You already have knowledge about dotstark.com indexed and ready to answer questions. "
    "Respond warmly and naturally to the user's greeting or small-talk. "
    "Let them know you can answer questions about DotStark's services, team, or projects. "
    "Keep your reply concise (2-3 sentences max)."
)


@dataclass
class IngestResult:
    url: str
    pages_crawled: int
    chunks_stored: int


@dataclass
class Answer:
    answer: str
    sources: list[dict] = field(default_factory=list)


class RAGPipeline:
    def __init__(self) -> None:
        logger.info("Loading embedder: %s", settings.embedding_model)
        self.embedder = Embedder(settings.embedding_model)

        self.store = QdrantStore(
            collection_name=settings.collection_name,
            embedding_dim=self.embedder.dim,
            path=settings.qdrant_path,
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )
        self.store.ensure_collection()

        reranker = None
        if settings.enable_reranker:
            logger.info("Loading reranker: %s", settings.reranker_model)
            reranker = Reranker(settings.reranker_model)

        self.retriever = Retriever(
            store=self.store,
            embedder=self.embedder,
            enable_hybrid=settings.enable_hybrid,
            reranker=reranker,
        )

        self._llm: LLMClient | None = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(
                provider=settings.llm_provider,
                groq_api_key=settings.groq_api_key,
                groq_model=settings.groq_model,
                openai_api_key=settings.openai_api_key,
                openai_model=settings.openai_model,
            )
        return self._llm

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_chitchat(text: str) -> bool:
        """Return True if the message is a greeting or small-talk."""
        return bool(_CHITCHAT_RE.match(text.strip()))

    def _chitchat_messages(self, question: str) -> list[dict]:
        return [
            {"role": "system", "content": _CHITCHAT_SYSTEM},
            {"role": "user", "content": question},
        ]

    def _rewrite_query(self, question: str) -> str:
        """
        Rewrite a vague query into a self-contained one before retrieval.

        'when was it founded?' → 'When was DotStark founded?'

        This fixes the pronoun resolution problem: vague pronouns like 'it',
        'they', 'this company' produce generic embedding vectors that don't
        match specific content in Qdrant. By replacing them with 'DotStark'
        we get a precise vector that retrieves the right chunks.

        We use a very low temperature (0.0) so the rewrite is deterministic.
        If the LLM call fails for any reason, we fall back to the original.
        """
        # Skip rewriting for chitchat — it's handled separately anyway.
        if self._is_chitchat(question):
            return question
        try:
            messages = [
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": question},
            ]
            rewritten = self.llm.generate(messages, temperature=0.0).strip()
            if rewritten and rewritten != question:
                logger.info("Query rewritten: '%s' → '%s'", question[:60], rewritten[:60])
            return rewritten or question
        except Exception as exc:
            logger.warning("Query rewrite failed (%s), using original.", exc)
            return question

    # ── ingestion ─────────────────────────────────────────────────────────────

    def ingest(self, url: str, max_pages: int | None = None, reset: bool = False) -> IngestResult:
        if reset:
            self.store.recreate_collection()

        crawler = WebsiteCrawler(
            max_pages=max_pages or settings.max_pages,
            timeout=settings.request_timeout,
            delay=settings.crawl_delay,
        )
        pages = crawler.crawl(url)
        logger.info("Crawled %d pages from %s", len(pages), url)

        total_chunks = 0
        for page in pages:
            cleaned = clean_text(page.text)
            chunks = chunk_text(
                cleaned,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )
            if not chunks:
                continue

            texts = [c.text for c in chunks]
            vectors = self.embedder.embed_documents(texts)
            added = self.store.upsert(
                vectors=vectors,
                texts=texts,
                source_url=page.url,
                title=page.title,
            )
            total_chunks += added

        self.retriever.invalidate_cache()
        return IngestResult(url=url, pages_crawled=len(pages), chunks_stored=total_chunks)

    # ── query ─────────────────────────────────────────────────────────────────

    def _retrieve(self, question: str, top_k: int | None, source_url: str | None):
        return self.retriever.retrieve(
            question, top_k=top_k or settings.top_k, source_url=source_url
        )

    @staticmethod
    def _sources_payload(chunks: list[StoredChunk]) -> list[dict]:
        sources = []
        for i, c in enumerate(chunks, start=1):
            sources.append({
                "n": i,
                "title": c.title or c.source_url,
                "url": c.source_url,
                "score": round(c.score, 4),
                "preview": c.text[:200] + ("..." if len(c.text) > 200 else ""),
            })
        return sources

    def answer(
        self,
        question: str,
        top_k: int | None = None,
        source_url: str | None = None,
    ) -> Answer:
        # 1. Greeting / small-talk -- skip retrieval, respond conversationally.
        if self._is_chitchat(question):
            text = self.llm.generate(self._chitchat_messages(question))
            return Answer(answer=text, sources=[])

        # 2. Rewrite vague queries before retrieval.
        retrieval_query = self._rewrite_query(question)

        # 3. RAG: retrieve relevant chunks using the rewritten query.
        chunks = self._retrieve(retrieval_query, top_k, source_url)
        if not chunks:
            return Answer(
                answer=(
                    "I don't have any website content indexed yet. "
                    "Please go to the **Index a Website** tab, paste a URL, and click "
                    "**Start Indexing** — then I can answer questions about it!"
                ),
                sources=[],
            )

        # 3. Build grounded prompt and call the LLM.
        messages = build_messages(question, chunks)
        text = self.llm.generate(messages)
        return Answer(answer=text, sources=self._sources_payload(chunks))

    def answer_stream(
        self,
        question: str,
        top_k: int | None = None,
        source_url: str | None = None,
    ) -> tuple[Iterator[str], list[dict]]:
        """Return (token_stream, sources). Sources arrive before tokens so the
        UI can render citations immediately while the answer streams in."""

        # 1. Greeting -- stream conversational reply, no sources.
        if self._is_chitchat(question):
            return self.llm.stream(self._chitchat_messages(question)), []

        # 2. Rewrite vague queries before retrieval.
        retrieval_query = self._rewrite_query(question)

        # 3. RAG retrieve using the rewritten query.
        chunks = self._retrieve(retrieval_query, top_k, source_url)
        if not chunks:
            def _no_index() -> Iterator[str]:
                yield (
                    "I don't have any website content indexed yet. "
                    "Please go to the **Index a Website** tab, paste a URL, and click "
                    "**Start Indexing** — then I can answer questions about it!"
                )
            return _no_index(), []

        # 3. Stream grounded answer.
        messages = build_messages(question, chunks)
        return self.llm.stream(messages), self._sources_payload(chunks)


@lru_cache
def get_pipeline() -> RAGPipeline:
    """Process-wide singleton. Heavy models load on first call only."""
    return RAGPipeline()
