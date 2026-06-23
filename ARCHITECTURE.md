# DotStark RAG Chatbot — Architecture Diagram

## Full System Architecture

```
┌──────────────────────────────────────────────────���──────────────────────────┐
│                              BROWSER (User)                                 │
│                         http://localhost:5173                               │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │ HTTP / SSE
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND  (React + Vite)                             │
│                                                                             │
│   App.jsx                                                                   │
│   └── ChatWidget.jsx          ← chat UI, SSE token streaming, sources      │
│       └── api.js              ← getStatus() | streamChat() SSE parser      │
│                                                                             │
│   vite.config.js  →  proxy  /api  →  http://localhost:8000                 │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │ /api/chat/stream  (POST)
                          │ /api/status       (GET)
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BACKEND  (FastAPI + Python)                          │
│                                                                             │
│  main.py  ──────────────────────────────────────────────────────────────   │
│  │  startup event → background thread → auto-ingest dotstark.com           │
│  │                                                                          │
│  └── api/routes.py  (HTTP layer)                                            │
│      ├── GET  /api/health                                                   │
│      ├── GET  /api/status                                                   │
│      ├── POST /api/ingest                                                   │
│      ├── POST /api/chat          ← blocking                                 │
│      └── POST /api/chat/stream   ← Server-Sent Events (SSE)                │
│              │                                                              │
│              │  Step 1: Check Redis cache                                   │
│              ▼                                                              │
│  ┌─────────────────────┐   HIT  ┌──────────────────────────────────┐       │
│  │   cache.py          │───────▶│  Return cached answer instantly   │       │
│  │  (Redis exact match)│        │  (no Qdrant, no LLM call)        │       │
│  │  SHA-256 key        │        └──────────────────────────────────┘       │
│  │  TTL = 24 hours     │                                                    │
│  └─────────┬───────────┘                                                   │
│            │ MISS                                                           │
│            ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │                    rag/pipeline.py                          │           │
│  │                   (RAGPipeline)                             │           │
│  │                                                             │           │
│  │   ┌─────────────────────────────────────────────────────┐  │           │
│  │   │              QUERY FLOW                             │  │           │
│  │   │                                                     │  │           │
│  │   │  question                                           │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  chitchat check ──── YES ──▶ LLM (no retrieval)    │  │           │
│  │   │      │ NO                                           │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  embeddings/embedder.py                             │  │           │
│  │   │  (question → 384-dim vector)                        │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  retrieval/retriever.py                             │  │           │
│  │   │  ├── Dense Search  → Qdrant vector similarity       │  │           │
│  │   │  ├── Sparse Search → BM25 keyword search            │  │           │
│  │   │  ├── RRF Fusion    → merge both ranked lists        │  │           │
│  │   │  └── Reranker      → cross-encoder precision sort   │  │           │
│  │   │      │  top 5 chunks                                │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  llm/prompts.py                                     │  │           │
│  │   │  (build system + context + question messages)       │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  llm/client.py  →  Groq API  (stream tokens)        │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  cache.py  →  Redis SAVE (24h TTL)                  │  │           │
│  │   └─────────────────────────────────────────────────────┘  │           │
│  │                                                             │           │
│  │   ┌─────────────────────────────────────────────────────┐  │           │
│  │   │              INGESTION FLOW                         │  │           │
│  │   │                                                     │  │           │
│  │   │  dotstark.com URL                                   │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  crawler/fetcher.py   → HTTP GET raw HTML           │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  crawler/extractor.py → HTML → plain text + links   │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  crawler/crawler.py   → BFS + sitemap + robots.txt  │  │           │
│  │   │      │  list of CrawledPage objects                 │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  processing/cleaner.py → remove boilerplate/noise   │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  processing/chunker.py → 800-char sliding window    │  │           │
│  │   │      │  list of Chunk objects                       │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  embeddings/embedder.py → text → 384-dim vectors    │  │           │
│  │   │      │                                              │  │           │
│  │   │      ▼                                              │  │           │
│  │   │  vectorstore/qdrant_store.py → upsert to Qdrant     │  │           │
│  │   └─────────────────────────────────────────────────────┘  │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
│  config.py  ←  .env  (API keys, model names, feature flags)                │
│  schemas.py ←  Pydantic models (ChatRequest, ChatResponse, etc.)           │
└──────────────────────┬──────────────────────┬──────────────────────────────┘
                       │                      │
                       ▼                      ▼
        ┌──────────────────────┐   ┌─────────────────────┐
        │   Qdrant Cloud       │   │   Redis Cloud        │
        │  (Vector Database)   │   │  (Answer Cache)      │
        │                      │   │                      │
        │  • stores chunk      │   │  • key: SHA-256 of   │
        │    vectors (384-dim) │   │    question          │
        │  • cosine similarity │   │  • value: answer +   │
        │    search (HNSW)     │   │    sources JSON      │
        │  • metadata filter   │   │  • TTL: 24 hours     │
        │    by source_url     │   │  • ~5 KB per entry   │
        └──────────────────────┘   └─────────────────────┘
                       │
                       ▼
        ┌──────────────────────┐
        │   Groq API           │
        │  (LLM Provider)      │
        │                      │
        │  • llama-3.3-70b     │
        │  • streaming tokens  │
        │  • temp = 0.1        │
        └──────────────────────┘
```

---

## Layer Responsibilities

```
┌─────────────────┬────────────────────────┬──────────────────────────────┐
│ Layer           │ File                   │ Single Responsibility        │
├─────────────────┼────────────────────────┼──────────────────────────────┤
│ HTTP            │ api/routes.py          │ Request/response only        │
│ Pipeline        │ rag/pipeline.py        │ Wire all layers together     │
│ Cache           │ cache.py               │ Redis read/write only        │
│ Network         │ crawler/fetcher.py     │ HTTP GET only                │
│ HTML Parsing    │ crawler/extractor.py   │ HTML → text + links only     │
│ Crawling        │ crawler/crawler.py     │ BFS + sitemap + robots only  │
│ Text Cleaning   │ processing/cleaner.py  │ Normalize text only          │
│ Chunking        │ processing/chunker.py  │ Split text only              │
│ Embedding       │ embeddings/embedder.py │ Text → vector only           │
│ Vector Store    │ vectorstore/qdrant_store│ Store + search vectors only │
│ Retrieval       │ retrieval/retriever.py │ Find relevant chunks only    │
│ Reranking       │ retrieval/reranker.py  │ Precision scoring only       │
│ LLM Client      │ llm/client.py          │ API calls only               │
│ Prompt Building │ llm/prompts.py         │ Message construction only    │
│ Config          │ config.py              │ Settings from .env only      │
│ Schemas         │ schemas.py             │ Data validation only         │
└─────────────────┴────────────────────────┴──────────────────────────────┘
```

---

## Query Flow (step by step)

```
User types: "What services does DotStark offer?"
        │
        ▼
[1] frontend/api.js
        POST /api/chat/stream

        ▼
[2] api/routes.py  →  chat_stream()
        │
        ├─ cache.get("what services does dotstark offer?")
        │       │
        │       ├── HIT  → stream cached answer → DONE (fast path)
        │       │
        │       └── MISS → continue to RAG pipeline
        ▼
[3] rag/pipeline.py  →  answer_stream()
        │
        ├─ is_chitchat("what services...") → NO
        │
        ▼
[4] embeddings/embedder.py
        "Represent this sentence for searching relevant passages: What services..."
        → [0.021, -0.043, 0.117, ... ]  (384 numbers)

        ▼
[5] retrieval/retriever.py
        ├─ Dense:  Qdrant cosine search  → top 20 chunks by meaning
        ├─ Sparse: BM25 keyword search   → top 20 chunks by keywords
        └─ RRF:    fuse both lists       → top 20 combined candidates

        ▼
[6] retrieval/reranker.py
        cross-encoder scores each (question, chunk) pair
        → top 5 most relevant chunks

        ▼
[7] llm/prompts.py
        system prompt + "[1] (Source: ...) chunk text..." + question

        ▼
[8] llm/client.py  →  Groq API
        streams tokens: "DotStark", " offers", " web", " development", ...

        ▼
[9] api/routes.py
        SSE events: sources → token → token → ... → done

        ▼
[10] cache.py  →  Redis SETEX (24h)
        key:   SHA256("what services does dotstark offer?|")
        value: {"answer": "DotStark offers...", "sources": [...]}

        ▼
[11] frontend/ChatWidget.jsx
        renders tokens one by one (typewriter effect)
```

---

## Ingestion Flow (on startup, runs once in background)

```
dotstark.com
        │
        ▼
[1] crawler/fetcher.py    HTTP GET each page (browser User-Agent)
        ▼
[2] crawler/extractor.py  strip <script> <nav> <footer> → plain text
        ▼
[3] crawler/crawler.py    BFS queue, sitemap.xml seed, robots.txt check
        │  120 pages crawled
        ▼
[4] processing/cleaner.py  normalize unicode, remove "Accept cookies" etc.
        ▼
[5] processing/chunker.py  sentence-aware sliding window
        │  800 chars per chunk, 150 char overlap
        ▼
[6] embeddings/embedder.py  batch encode (32 at a time)
        │  shape: (N, 384) float32 vectors
        ▼
[7] vectorstore/qdrant_store.py  upsert points with payload
        │  {text, source_url, title, chunk_index}
        ▼
Qdrant Cloud  →  HNSW index built automatically
```

---

## External Services

```
┌─────────────────────────────────────────────────────────┐
│  Service         │  Purpose           │  When used       │
├──────────────────┼────────────────────┼──────────────────┤
│  Qdrant Cloud    │  Vector storage    │  Ingest + Query  │
│  Redis Cloud     │  Answer cache      │  Every query     │
│  Groq API        │  LLM inference     │  Cache miss only │
│  dotstark.com    │  Content source    │  Ingestion only  │
└─────────────────────────────────────────────────────────┘
```
