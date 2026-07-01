# 🔎 Website RAG Chatbot (built from scratch)

A Retrieval-Augmented Generation chatbot that answers questions about **any
website** — built **without** LangChain, LlamaIndex, or any RAG framework. Every
component (crawler, cleaner, chunker, embeddings, vector store, retriever,
reranker, LLM client) is hand-written so you can see exactly how RAG works.

---

## 🏗️ Architecture

```
INGESTION (offline, runs once per site)
  URL ─▶ Crawl (requests + BeautifulSoup, sitemap + recursive)
      ─▶ Clean text
      ─▶ Chunk (sentence-aware, with overlap)
      ─▶ Embed (BAAI/bge-small-en-v1.5)
      ─▶ Store vectors + metadata in Qdrant

QUERY (online, every question)
  Question ─▶ Embed query
           ─▶ Retrieve:  Vector search  +  BM25  →  RRF fusion
           ─▶ Rerank (cross-encoder, precision)
           ─▶ Build prompt with numbered context
           ─▶ LLM (Groq / OpenAI) → grounded answer + [n] citations
```

### Component map

| Layer | File | Responsibility |
|---|---|---|
| Fetch | `app/crawler/fetcher.py` | HTTP GET → raw HTML |
| Extract | `app/crawler/extractor.py` | HTML → text + same-domain links |
| Crawl | `app/crawler/crawler.py` | BFS crawl, sitemap, robots.txt, politeness |
| Clean | `app/processing/cleaner.py` | normalize whitespace, drop boilerplate |
| Chunk | `app/processing/chunker.py` | sentence-aware chunks + overlap |
| Embed | `app/embeddings/embedder.py` | bge-small vectors (query vs doc) |
| Store | `app/vectorstore/qdrant_store.py` | Qdrant collection, upsert, search, filter |
| Retrieve | `app/retrieval/retriever.py` | dense + BM25 + RRF fusion |
| Rerank | `app/retrieval/reranker.py` | cross-encoder precision ranking |
| LLM | `app/llm/` | prompt building + Groq/OpenAI client (streaming) |
| Orchestrate | `app/rag/pipeline.py` | wires ingestion + query flows |
| API | `app/api/routes.py`, `app/main.py` | FastAPI endpoints + SSE streaming |
| Cache | `app/cache.py` | optional Redis three-layer answer cache (exact + LLM + semantic) |
| UI | `frontend/` | React chat interface with citations |

---

## 🚀 Setup

### 1. Backend

```bash
cd backend

# Create an isolated virtual environment (fixes the Python/pip version mix too)
python -m venv venv
source venv/Scripts/activate        # Git Bash on Windows
# .\venv\Scripts\activate           # PowerShell
# source venv/bin/activate          # macOS / Linux

pip install -r requirements.txt     # first run downloads torch — be patient

cp .env.example .env                # then edit .env and add your GROQ_API_KEY
```

Get a **free** Groq API key at https://console.groq.com/keys and paste it into `.env`.

> **Qdrant needs no Docker by default** — it runs in embedded local mode and
> persists to `./qdrant_data`. To use a real server, set `QDRANT_URL` in `.env`.

### 2. Run the API

```bash
cd backend
source venv/Scripts/activate        # Git Bash on Windows
uvicorn app.main:app --reload --port 8000
```

Open interactive docs at **http://localhost:8000/docs**.

> The first request loads the embedding + reranker models (downloaded once from
> Hugging Face). Subsequent requests are fast.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Enter a website URL, click **Ingest**, then chat.

---

## 🧪 Quick test without the frontend

```bash
cd backend
source venv/Scripts/activate

# CLI demo
python -m scripts.demo ingest https://example.com
python -m scripts.demo ask "What is this website about?"

# Or via curl
curl -X POST localhost:8000/api/ingest -H "Content-Type: application/json" \
     -d '{"url":"https://example.com","max_pages":10,"reset":true}'

curl -X POST localhost:8000/api/chat -H "Content-Type: application/json" \
     -d '{"question":"What is this site about?"}'
```

Run the lightweight unit tests (no model download needed):

```bash
python tests/test_processing.py
```

---

## ⚙️ Configuration (`.env`)

| Key | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq` or `openai` |
| `GROQ_API_KEY` | — | required for answers |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | 384-dim |
| `ENABLE_RERANKER` | `true` | cross-encoder second-stage |
| `ENABLE_HYBRID` | `true` | BM25 + vector fusion |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `150` | characters |
| `TOP_K` | `5` | chunks sent to the LLM |
| `MAX_PAGES` | `40` | crawl limit |
| `QDRANT_URL` | empty | empty = embedded local mode |
| `REDIS_URL` | empty | empty = caching disabled |

---

## 🎓 Advanced features included

- **Hybrid search** — BM25 (keyword) + dense vectors, merged with Reciprocal Rank Fusion.
- **Reranking** — cross-encoder re-scores candidates for precision.
- **Metadata filtering** — restrict retrieval to one `source_url`.
- **Streaming responses** — token-by-token via Server-Sent Events.
- **Source citations** — every answer cites `[n]` linking to the source page.
- **Three-layer Redis cache** — optional; gracefully disabled when Redis is absent.
  - **Layer 1 (exact)** — same question asked again? Skip Qdrant + reranker + LLM entirely (~50ms).
  - **Layer 2 (LLM)** — same question retrieves same chunks? Skip only the LLM (~400ms saved).
  - **Layer 3 (semantic)** — different question but same chunks retrieved? Reuse the cached answer regardless of wording.
  - **Version-based invalidation** — every ingest bumps a Redis counter; all cached answers invalidate instantly.

---

## ⚠️ Known limitation

`requests` only sees server-rendered HTML. For heavily JavaScript-rendered SPAs,
swap `app/crawler/fetcher.py` for a browser engine (Playwright / **Crawl4AI**) —
the rest of the pipeline stays unchanged thanks to the clean layering.
