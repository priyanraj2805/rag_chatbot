# DotStark Website RAG Chatbot — Complete Project Documentation

**Version:** 1.0.0
**Stack:** Python · FastAPI · React · Qdrant Cloud · Groq (LLaMA 3.3)
**Built:** From scratch — no LangChain, no LlamaIndex, no pre-built RAG framework

---

## Table of Contents

1. [What is this project?](#1-what-is-this-project)
2. [What is RAG?](#2-what-is-rag)
3. [Full Architecture Diagram](#3-full-architecture-diagram)
4. [The Two Pipelines Explained](#4-the-two-pipelines-explained)
5. [Component Deep Dive](#5-component-deep-dive)
6. [Technology Stack — Every Tool Explained](#6-technology-stack--every-tool-explained)
7. [Project Folder Structure](#7-project-folder-structure)
8. [API Endpoints Reference](#8-api-endpoints-reference)
9. [Configuration Reference](#9-configuration-reference)
10. [Data Flow — Step by Step](#10-data-flow--step-by-step)
11. [dotstark.com Ingestion Stats](#11-dotstarkcom-ingestion-stats)
12. [How to Run the Project](#12-how-to-run-the-project)
13. [Interview Questions & Answers](#13-interview-questions--answers)
14. [Known Limitations & Future Improvements](#14-known-limitations--future-improvements)

---

## 1. What is this project?

This is a **Website RAG Chatbot** — an AI assistant that can answer questions
about any website by reading and understanding its content.

**The core idea:**
Instead of asking an AI model to answer from its own (possibly outdated)
memory, we first crawl the target website, store its content in a vector
database, and at query time retrieve the most relevant pieces and hand them
to the AI as context. The AI then answers strictly from that context.

**In production:**
- The chatbot is embedded as a floating widget on dotstark.com
- It has indexed all 113 public pages of dotstark.com (6,767 chunks)
- Users can ask anything: services, pricing, case studies, team, contact info
- Every answer comes with clickable source citations

---

## 2. What is RAG?

**RAG = Retrieval-Augmented Generation**

A standard LLM is a frozen brain — it knows only what it saw during training.
It cannot know your website, your docs, or last week's news. RAG fixes this:

```
WITHOUT RAG:
  User: "What Azure services does DotStark offer?"
  LLM:  [guesses / hallucinates / says "I don't know"]

WITH RAG:
  User:  "What Azure services does DotStark offer?"
  System: [fetches the 5 most relevant chunks from dotstark.com]
  LLM:   "Based on the website, DotStark offers Azure Cloud Development,
           Azure App Development, Azure Migration Services... [1]"
```

The word "augmented" means we AUGMENT the LLM's prompt with real, retrieved
context at runtime. The LLM is then instructed to answer ONLY from that
context, which prevents hallucination and enables source citations.

---

## 3. Full Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════════════╗
║                     WEBSITE RAG CHATBOT — ARCHITECTURE                  ║
╚══════════════════════════════════════════════════════════════════════════╝

 ┌─────────────────────────────────────────────────────────────────────┐
 │              PIPELINE 1: INGESTION  (runs once per site)            │
 │                                                                     │
 │  dotstark.com/sitemap.xml                                           │
 │         │                                                           │
 │         ▼                                                           │
 │  ┌─────────────┐   HTTP GET    ┌──────────────────┐                │
 │  │   Sitemap   │ ────────────► │   WebsiteCrawler  │               │
 │  │   Parser    │               │  (BFS + robots)   │               │
 │  └─────────────┘               └────────┬─────────┘               │
 │                                         │  114 pages               │
 │                                         ▼                           │
 │                                ┌──────────────────┐                │
 │                                │    Extractor      │               │
 │                                │ (BeautifulSoup)   │               │
 │                                │ removes: script,  │               │
 │                                │ style, nav, footer│               │
 │                                └────────┬─────────┘               │
 │                                         │  raw text                │
 │                                         ▼                           │
 │                                ┌──────────────────┐                │
 │                                │     Cleaner       │               │
 │                                │ normalize unicode │               │
 │                                │ collapse spaces   │               │
 │                                │ drop boilerplate  │               │
 │                                └────────┬─────────┘               │
 │                                         │  clean text              │
 │                                         ▼                           │
 │                                ┌──────────────────┐                │
 │                                │  Chunker          │               │
 │                                │ sentence-aware    │               │
 │                                │ size=800 chars    │               │
 │                                │ overlap=150 chars │               │
 │                                └────────┬─────────┘               │
 │                                         │  chunks[]                │
 │                                         ▼                           │
 │                                ┌──────────────────┐                │
 │                                │    Embedder       │               │
 │                                │ BAAI/bge-small    │               │
 │                                │ 384-dim vectors   │               │
 │                                │ L2-normalized     │               │
 │                                └────────┬─────────┘               │
 │                                         │  vectors[]               │
 │                                         ▼                           │
 │                                ┌──────────────────┐                │
 │                                │   Qdrant Cloud    │               │
 │                                │  collection:      │               │
 │                                │  website_chunks   │               │
 │                                │  6,767 vectors    │               │
 │                                │  + metadata       │               │
 │                                └──────────────────┘               │
 └─────────────────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────────────────┐
 │              PIPELINE 2: QUERY  (runs on every user question)       │
 │                                                                     │
 │  User types: "What Azure services does DotStark offer?"             │
 │         │                                                           │
 │         ▼                                                           │
 │  ┌─────────────────────┐                                            │
 │  │  Greeting Detector  │  ── is it "hi"/"hello"? ──► LLM directly  │
 │  └──────────┬──────────┘                                            │
 │             │  not a greeting                                       │
 │             ▼                                                       │
 │  ┌─────────────────────┐                                            │
 │  │  Query Embedder     │  (bge-small + query instruction prefix)    │
 │  │  384-dim vector     │                                            │
 │  └──────────┬──────────┘                                            │
 │             │                                                       │
 │      ┌──────┴──────────────────────────┐                            │
 │      ▼                                 ▼                            │
 │  ┌──────────────┐             ┌──────────────────┐                 │
 │  │ Dense Search │             │  BM25 / Sparse   │                 │
 │  │  (Qdrant     │             │  Search (keyword) │                │
 │  │   cosine)    │             │  rank-bm25 lib    │                │
 │  │  top-20      │             │  top-20           │                │
 │  └──────┬───────┘             └────────┬─────────┘                │
 │         │                              │                            │
 │         └──────────────┬───────────────┘                           │
 │                        ▼                                            │
 │              ┌──────────────────┐                                   │
 │              │  RRF Fusion      │  Reciprocal Rank Fusion           │
 │              │  score = Σ       │  merges both ranked lists         │
 │              │  1/(k + rank)    │  k=60 (standard default)          │
 │              └────────┬─────────┘                                   │
 │                       │  top-20 fused candidates                    │
 │                       ▼                                             │
 │              ┌──────────────────┐                                   │
 │              │  Cross-Encoder   │  ms-marco-MiniLM-L-6-v2           │
 │              │  Reranker        │  reads query+chunk TOGETHER        │
 │              │                  │  much more precise scoring         │
 │              └────────┬─────────┘                                   │
 │                       │  top-5 most relevant chunks                 │
 │                       ▼                                             │
 │              ┌──────────────────┐                                   │
 │              │  Prompt Builder  │                                   │
 │              │  [CONTEXT]       │  numbered chunks 1..5             │
 │              │  [QUESTION]      │  + system instructions            │
 │              │  [INSTRUCTIONS]  │                                   │
 │              └────────┬─────────┘                                   │
 │                       │                                             │
 │                       ▼                                             │
 │              ┌──────────────────┐                                   │
 │              │   Groq API       │  LLaMA 3.3 70B Versatile          │
 │              │   (LLM)          │  streaming tokens                 │
 │              └────────┬─────────┘                                   │
 │                       │                                             │
 │                       ▼                                             │
 │  "DotStark offers Azure Cloud Development, Azure App                │
 │   Development, Azure Migration Services... [1]"                     │
 │   + sources: [1] dotstark.com/services/azure...                     │
 └─────────────────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────────────────┐
 │                     SYSTEM LAYERS                                   │
 │                                                                     │
 │   React UI (Vite :5173)                                             │
 │        │  /api/*  (Vite proxies to :8000 in dev)                   │
 │        ▼                                                            │
 │   FastAPI  (:8000)                                                  │
 │        │  POST /api/ingest   POST /api/chat   POST /api/chat/stream │
 │        ▼                                                            │
 │   RAGPipeline  (Python singleton — models load once)               │
 │        │                                                            │
 │        ├── Embedder       (bge-small, local CPU)                   │
 │        ├── QdrantStore    (Qdrant Cloud, us-east-1)                │
 │        ├── Retriever      (dense + BM25 + RRF)                     │
 │        ├── Reranker       (ms-marco cross-encoder, local CPU)      │
 │        └── LLMClient      (Groq API, cloud)                        │
 │                                                                     │
 │   Optional: Redis Cache (disabled — REDIS_URL not set)             │
 └─────────────────────────────────────────────────────────────────────┘
```

---

## 4. The Two Pipelines Explained

### Pipeline 1 — Ingestion (offline, runs once)

This pipeline runs when you want to index a new website. It is slow (minutes)
because it crawls many pages and runs the embedding model over thousands of
text chunks.

```
Step 1:  Discover pages        sitemap.xml → 117 URLs → 114 after robots.txt
Step 2:  Fetch each page       requests.get() → raw HTML
Step 3:  Extract text          BeautifulSoup → strips scripts, nav, footer
Step 4:  Clean text            unicode normalize, collapse whitespace, drop boilerplate
Step 5:  Chunk text            sentence-aware sliding window, 800 chars, 150 overlap
Step 6:  Embed chunks          BAAI/bge-small-en-v1.5 → 384-dim float32 vectors
Step 7:  Store in Qdrant       vector + payload (text, url, title, chunk_index)
```

**Why each step matters:**
- **Sitemap first**: faster discovery than recursive link-following, gets clean canonical URLs
- **robots.txt**: ethical and legal compliance, avoids getting IP-blocked
- **Cleaning before chunking**: dirty text = dirty chunks = dirty embeddings = bad retrieval
- **Chunking with overlap**: prevents a fact from being split across a boundary and lost
- **384-dim vectors**: small enough to be fast, large enough to capture meaning

### Pipeline 2 — Query (online, runs on every question)

This pipeline runs in milliseconds when a user sends a message.

```
Step 1:  Greeting check        regex match → chitchat? → direct LLM, skip retrieval
Step 2:  Embed the question    bge-small with query-instruction prefix
Step 3:  Dense search          cosine similarity in Qdrant → top-20 candidates
Step 4:  Sparse search         BM25 keyword match → top-20 candidates  [if hybrid=on]
Step 5:  RRF fusion            merge both ranked lists → top-20 unified  [if hybrid=on]
Step 6:  Rerank                cross-encoder scores each (question, chunk) pair → top-5
Step 7:  Build prompt          system instructions + numbered context + question
Step 8:  LLM call              Groq API (LLaMA 3.3 70B) → streaming tokens
Step 9:  Return answer + sources
```

**Why two search strategies?**
- Dense (vector) search: understands MEANING. "cheap" matches "affordable pricing".
- Sparse (BM25) search: finds EXACT words. "error code 0x80004005" found precisely.
- Together: almost nothing slips through.

---

## 5. Component Deep Dive

### 5.1 Crawler (`app/crawler/`)

**fetcher.py**
- Single job: given a URL, return raw HTML as a string
- Sends real browser User-Agent so servers don't block the request
- Sets a 15-second timeout (without this, one slow server hangs the whole crawl)
- Raises `FetchError` for non-200 responses and non-HTML content types
- Why isolated: later we can swap `requests` for Playwright (for JS-rendered sites)
  by changing ONLY this file — everything else stays the same

**extractor.py**
- Single job: parse HTML → readable text + same-domain links
- Removes `<script>`, `<style>`, `<nav>`, `<footer>`, `<aside>`, `<form>`, etc.
- `get_text(separator=" ")` prevents words from gluing together across tags
- `extract_links()` resolves relative URLs, strips fragments (#), stays on same domain
- Why important: without tag removal, your chunks would contain JavaScript code and
  CSS rules mixed with real content — completely ruining embeddings

**crawler.py**
- Orchestrates the full crawl using Breadth-First Search (BFS)
- Seeds the queue from sitemap.xml first (fastest, most reliable discovery)
- Falls back to recursive link extraction if sitemap is unavailable
- Respects robots.txt using Python's built-in `RobotFileParser`
- Adds `crawl_delay=0.4s` between requests (politeness — avoids IP bans)
- Skips pages with fewer than 20 words (JS-rendered empty shells)

### 5.2 Processing (`app/processing/`)

**cleaner.py**
- Unicode NFKC normalization (curly quotes, accented chars → standard form)
- Removes control characters (except newline and tab)
- Collapses multiple spaces into one
- Drops boilerplate lines: "Skip to content", "Accept cookies", "© All rights reserved"
- Collapses 3+ blank lines into one paragraph break
- Why this matters: every character of noise in a chunk wastes embedding capacity
  and can shift the vector away from the real topic

**chunker.py**
- Splits text into overlapping windows of ~800 characters
- Sentence-aware: never cuts mid-sentence
- Overlap of 150 characters: last ~2 sentences of chunk N become first sentences of chunk N+1
- Handles edge cases: single sentences longer than chunk_size are hard-split
- Why overlap exists: imagine "The price is [chunk boundary] $49/month." Without overlap,
  your embedding model never sees the complete fact.
- Why 800 chars: the bge-small model handles up to 512 tokens (~1200-1500 chars), but
  800 chars gives focused, topically-coherent chunks that embed well

### 5.3 Embeddings (`app/embeddings/`)

**embedder.py**
- Model: `BAAI/bge-small-en-v1.5` (HuggingFace)
- Output: 384-dimensional float32 vectors, L2-normalized (length = 1)
- Two separate methods:
  - `embed_documents(texts)`: for chunks at ingestion time
  - `embed_query(text)`: prepends "Represent this sentence for searching relevant passages: "
    because bge models were trained this way — query and document use different representations
- L2 normalization: with unit-length vectors, dot product = cosine similarity
  (no division needed, slightly faster at search time)
- Why bge-small: strong multilingual retrieval performance at tiny size (33M params),
  runs fast on CPU, no GPU required

### 5.4 Vector Store (`app/vectorstore/`)

**qdrant_store.py**
- Connects to Qdrant Cloud (your us-east-1 AWS cluster)
- Collection: `website_chunks`, distance metric: COSINE
- Each stored point has:
  - `id`: UUID (auto-generated)
  - `vector`: 384 float32 values
  - `payload`: text, source_url, title, chunk_index
- `search()`: returns top-K nearest vectors + their payloads
- `scroll_all()`: streams every chunk text (used to build BM25 index)
- `upsert()`: insert or overwrite points (idempotent)
- Why Qdrant: uses HNSW index (Hierarchical Navigable Small World graph) —
  approximate nearest-neighbor search in O(log n) instead of O(n).
  Searching 6,767 vectors takes < 5ms.

### 5.5 Retrieval (`app/retrieval/`)

**retriever.py** — the most complex component
```
Dense search:
  query vector  ──►  Qdrant cosine search  ──►  top-20 chunks

Sparse search (BM25):
  query tokens  ──►  BM25Okapi.get_scores()  ──►  top-20 chunks
  (BM25 index is built LAZILY from all chunk texts on first query,
   then cached in memory — rebuilds when new content is ingested)

RRF Fusion:
  For each chunk in either list:
    score += 1 / (60 + rank_in_list)
  Chunks appearing in both lists get a double boost
  Result: top-20 unified candidates

Final: pass top-20 to reranker → top-5 returned to pipeline
```

**Why BM25 is still relevant in 2025:**
Dense vectors are great at semantics but terrible at exact matches.
If a user asks about "KenticoXperience 13 EOS", BM25 finds it immediately
because it matches exact tokens. Dense search might return something about
"CMS platform migration" — correct topic but missing the specific version.

**reranker.py**
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- A cross-encoder reads query AND chunk text together (not separately)
- Produces a single relevance score per (query, chunk) pair
- Much more accurate than bi-encoder cosine similarity
- But 20x slower per pair — hence only run on the top-20, not all 6,767
- Loaded with `device="cpu"` explicitly to fix PyTorch 2.x meta tensor bug

### 5.6 LLM Layer (`app/llm/`)

**prompts.py** — controls what the LLM sees
```
System prompt:
  "You are a friendly AI assistant for DotStark...
   Answer naturally from the context.
   If context doesn't contain the answer, say so.
   Be warm, professional, concise."

User message:
  "[1] (Source: Azure Services Page)
   DotStark provides Azure Cloud Development, Azure App Development...

   [2] (Source: Solutions Page)
   Our Azure Migration Services include...

   QUESTION: What Azure services does DotStark offer?
   Answer the question naturally using the context above."
```
Numbered context blocks enable the model to cite `[1]`, `[2]` in the answer,
which the frontend renders as clickable links.

**client.py**
- Supports two providers: Groq (default) and OpenAI
- Both use the same `chat.completions.create` interface
- `generate()`: blocking call, returns full answer string
- `stream()`: generator that yields tokens as they arrive (< 100ms to first token with Groq)
- Temperature=0.1: low randomness, consistent factual answers

### 5.7 RAG Pipeline (`app/rag/pipeline.py`)

The conductor that wires everything together.

```python
class RAGPipeline:
    # Loaded ONCE when the process starts:
    embedder  = Embedder("BAAI/bge-small-en-v1.5")
    store     = QdrantStore(url=QDRANT_CLOUD_URL)
    reranker  = Reranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    retriever = Retriever(store, embedder, reranker)
    llm       = LLMClient(provider="groq")    # lazy — first query only

    def ingest(url):     # Pipeline 1
        crawl → clean → chunk → embed → store

    def answer(question):  # Pipeline 2 (blocking)
        if greeting: return llm.generate(chitchat_prompt)
        chunks = retrieve(question, top_k=5)
        if not chunks: return "no content indexed"
        return llm.generate(build_messages(question, chunks))

    def answer_stream(question):  # Pipeline 2 (streaming)
        # Returns (token_generator, sources_list) simultaneously
        # Sources are ready before the first token — sent to UI immediately
```

**Singleton pattern**: `@lru_cache` on `get_pipeline()` ensures models load
exactly once per process. Loading bge-small + cross-encoder takes ~8 seconds
on CPU — you do NOT want this on every request.

### 5.8 FastAPI App (`app/api/routes.py`, `app/main.py`)

Four endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Liveness probe (returns `{"status":"ok"}`) |
| `/api/status` | GET | Collection info, chunk count, config |
| `/api/ingest` | POST | Crawl + index a website |
| `/api/chat` | POST | Ask a question (blocking response) |
| `/api/chat/stream` | POST | Ask a question (Server-Sent Events stream) |

**CORS**: configured to allow `localhost:5173` (Vite dev server) and
`localhost:3000` (alternative React port).

**SSE (Server-Sent Events) format:**
```
event: sources
data: [{"n":1,"title":"Azure Services","url":"...","score":0.87}]

event: token
data: "DotStark"

event: token
data: " offers"

event: done
data: {}
```
The UI receives sources BEFORE the first token, so citations appear
instantly at the top of the answer while text is still streaming.

### 5.9 Cache (`app/cache.py`)

Optional Redis answer cache.
- Cache key: SHA-256 hash of `(question + source_url_filter)`
- TTL: 1 hour
- On cache hit: answer returned in < 1ms (vs 1-3 seconds for full RAG)
- Graceful degradation: if Redis is unavailable, all methods are no-ops
- Currently DISABLED (REDIS_URL not set in .env)

### 5.10 React Frontend (`frontend/src/`)

**ChatWidget.jsx** — floating chat widget (always visible, bottom-right)
- Fixed-position circular launcher button (purple, 60×60px)
- Click to open/close a 380×580px panel with spring animation
- Two tabs:
  - **Chat**: streaming answer display with markdown rendering + source links
  - **Index a Website**: URL input form for triggering ingestion
- `useRef(false)` streaming guard prevents React's concurrent renderer from
  double-firing the stream handler
- `ReactMarkdown` renders `**bold**`, `*lists*`, `` `code` `` properly

**api.js** — all HTTP calls in one place
- `safeFetch()` wrapper: converts `ECONNREFUSED` (backend not running) into a
  clear human-readable error instead of "Unexpected end of JSON input"
- `streamChat()`: manually parses SSE stream from a `fetch()` response body
  (using `ReadableStream` + `TextDecoder`), no `EventSource` needed

---

## 6. Technology Stack — Every Tool Explained

### Backend

| Tool | Version | Why we use it |
|---|---|---|
| **Python** | 3.11.4 | Industry standard for AI/ML — best library ecosystem |
| **FastAPI** | 0.115.6 | Async-native, auto-generates OpenAPI docs, faster than Flask |
| **Uvicorn** | 0.34.0 | ASGI server for FastAPI, supports streaming responses |
| **Pydantic** | 2.10.4 | Request/response validation, type safety, .env parsing |
| **pydantic-settings** | 2.7.1 | Type-validated config from .env files |

### Crawling

| Tool | Version | Why we use it |
|---|---|---|
| **requests** | 2.32.3 | Simple HTTP client — fetches HTML from any URL |
| **BeautifulSoup4** | 4.12.3 | HTML parser — extracts text and links from HTML tree |
| **lxml** | 5.3.0 | Fast XML/HTML parser backend for BeautifulSoup |

### AI / ML

| Tool | Version | Why we use it |
|---|---|---|
| **sentence-transformers** | 3.3.1 | High-level wrapper for embedding + cross-encoder models |
| **BAAI/bge-small-en-v1.5** | — | Embedding model: 384-dim, fast on CPU, top retrieval benchmark scores |
| **cross-encoder/ms-marco-MiniLM-L-6-v2** | — | Reranker: trained on 500k MS MARCO passage pairs, very precise |
| **torch** | 2.12.1 | Backend for running transformer models locally |
| **transformers** | 4.57.6 | HuggingFace model loading |
| **rank-bm25** | 0.2.2 | BM25Okapi implementation for keyword search |
| **numpy** | 1.26.4 | Vector math (cosine similarity, array operations) |

### Vector Database

| Tool | Version | Why we use it |
|---|---|---|
| **Qdrant Cloud** | — | Production vector DB: HNSW index, metadata filtering, REST API |
| **qdrant-client** | 1.12.1 | Python SDK for Qdrant (local embedded or cloud mode) |

**Why Qdrant over alternatives:**
- **vs Pinecone**: open source, self-hostable, better payload filtering
- **vs Chroma**: production-grade, handles millions of vectors efficiently
- **vs Weaviate**: simpler API, Python-native, no schema definition needed
- **vs FAISS**: has metadata storage, filtering, REST API — FAISS is just the index

### LLM Provider

| Tool | Version | Why we use it |
|---|---|---|
| **Groq** | 0.13.1 | Runs LLaMA 3.3 70B at ~800 tokens/sec — extremely fast streaming |
| **LLaMA 3.3 70B Versatile** | — | Best open-weight model for Q&A, instruction following, citations |
| **openai** | 1.59.6 | Fallback option if switching to GPT-4o-mini |

**Why Groq over OpenAI for this use case:**
- 10-50x faster token generation (LPU hardware vs GPU)
- Free tier available (10M tokens/day)
- LLaMA 3.3 70B matches GPT-4o quality on RAG tasks
- First token arrives in < 100ms (vs ~500ms for OpenAI)

### Frontend

| Tool | Version | Why we use it |
|---|---|---|
| **React** | 18.3.1 | Component model, hooks for streaming state management |
| **Vite** | 6.0.7 | Instant HMR dev server, proxy configuration for API calls |
| **react-markdown** | 10.1.0 | Renders LLM markdown output as proper HTML |

### Optional / Infrastructure

| Tool | Why we use it |
|---|---|
| **Redis** | Answer cache — identical questions return in < 1ms (optional) |
| **Qdrant Cloud (AWS us-east-1)** | Persistent vector storage, accessible from anywhere |

---

## 7. Project Folder Structure

```
chatbot_dotstark/
│
├── README.md                          ← Quick start guide
├── PROJECT_DOCUMENTATION.md           ← This file
│
├── backend/
│   ├── requirements.txt               ← All Python dependencies
│   ├── .env                           ← Your secrets (Groq key, Qdrant URL)
│   ├── .env.example                   ← Template for new developers
│   ├── .gitignore                     ← Excludes venv/, .env, qdrant_data/
│   │
│   ├── venv/                          ← Python virtual environment (local only)
│   │
│   ├── app/                           ← Main application package
│   │   ├── config.py                  ← All settings via pydantic-settings
│   │   ├── schemas.py                 ← Pydantic request/response models
│   │   ├── cache.py                   ← Optional Redis answer cache
│   │   ├── main.py                    ← FastAPI app creation, CORS, router mount
│   │   │
│   │   ├── crawler/
│   │   │   ├── fetcher.py             ← HTTP GET → raw HTML
│   │   │   ├── extractor.py           ← HTML → text + links
│   │   │   └── crawler.py             ← BFS orchestrator (sitemap + recursive)
│   │   │
│   │   ├── processing/
│   │   │   ├── cleaner.py             ← Normalize + drop boilerplate
│   │   │   └── chunker.py             ← Sentence-aware chunking with overlap
│   │   │
│   │   ├── embeddings/
│   │   │   └── embedder.py            ← bge-small wrapper (doc vs query)
│   │   │
│   │   ├── vectorstore/
│   │   │   └── qdrant_store.py        ← Qdrant CRUD + search + scroll
│   │   │
│   │   ├── retrieval/
│   │   │   ├── retriever.py           ← Dense + BM25 + RRF fusion
│   │   │   └── reranker.py            ← Cross-encoder second stage
│   │   │
│   │   ├── llm/
│   │   │   ├── client.py              ← Groq/OpenAI (blocking + streaming)
│   │   │   └── prompts.py             ← System prompt + context builder
│   │   │
│   │   ├── rag/
│   │   │   └── pipeline.py            ← Orchestrates ingestion + query
│   │   │
│   │   └── api/
│   │       └── routes.py              ← All FastAPI route handlers
│   │
│   ├── scripts/
│   │   ├── demo.py                    ← CLI test (no frontend needed)
│   │   └── ingest_dotstark.py         ← Full dotstark.com ingestion script
│   │
│   └── tests/
│       └── test_processing.py         ← Unit tests for cleaner + chunker
│
└── frontend/
    ├── package.json                   ← Node dependencies
    ├── vite.config.js                 ← Proxy /api → localhost:8000
    ├── index.html                     ← App entry point
    └── src/
        ├── main.jsx                   ← React root mount
        ├── App.jsx                    ← Root component (renders ChatWidget)
        ├── ChatWidget.jsx             ← Floating chat widget (all UI logic)
        ├── api.js                     ← All backend HTTP calls
        └── styles.css                 ← Widget + markdown styles
```

---

## 8. API Endpoints Reference

### GET /api/health
```json
Response: { "status": "ok" }
```
Used by load balancers and monitoring tools. Always fast.

---

### GET /api/status
```json
Response:
{
  "collection": "website_chunks",
  "indexed_chunks": 6767,
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "llm_provider": "groq",
  "hybrid_search": false,
  "reranker": true
}
```

---

### POST /api/ingest
```json
Request:
{
  "url": "https://dotstark.com",
  "max_pages": 120,
  "reset": true
}

Response:
{
  "url": "https://dotstark.com",
  "pages_crawled": 113,
  "chunks_stored": 3332,
  "message": "Indexed 3332 chunks from 113 pages."
}
```

---

### POST /api/chat
```json
Request:
{
  "question": "What Azure services does DotStark offer?",
  "top_k": 5,
  "source_url": null
}

Response:
{
  "answer": "DotStark offers Azure Cloud Development, Azure App Development, Azure Migration Services, and Azure Consulting Services [1].",
  "sources": [
    {
      "n": 1,
      "title": "Microsoft Azure Development Company | DotStark",
      "url": "https://dotstark.com/services/azure-development-services",
      "score": 10.227,
      "preview": "DotStark provides a comprehensive range of Azure services..."
    }
  ],
  "cached": false
}
```

---

### POST /api/chat/stream
```
Request: same as /api/chat

Response: text/event-stream (SSE)

event: sources
data: [{"n":1,"title":"Azure Services","url":"...","score":10.227}]

event: token
data: "DotStark"

event: token
data: " offers"

event: token
data: " Azure"

event: done
data: {}
```

---

## 9. Configuration Reference

All values live in `backend/.env`:

| Key | Current Value | Description |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `groq` or `openai` |
| `GROQ_API_KEY` | `gsk_...` | Free at console.groq.com/keys |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Best open model for Q&A |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | 33M params, 384-dim |
| `EMBEDDING_DIM` | `384` | Must match the model output |
| `ENABLE_RERANKER` | `true` | Cross-encoder second stage |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 6-layer MiniLM |
| `QDRANT_URL` | `https://be869c65-...qdrant.io` | Your Qdrant Cloud cluster |
| `QDRANT_API_KEY` | `eyJhbGci...` | Qdrant Cloud JWT token |
| `COLLECTION_NAME` | `website_chunks` | Qdrant collection name |
| `CHUNK_SIZE` | `800` | Max chars per chunk |
| `CHUNK_OVERLAP` | `150` | Chars shared between consecutive chunks |
| `TOP_K` | `5` | Chunks sent to the LLM |
| `ENABLE_HYBRID` | `false` | BM25 + vector fusion (enable for better recall) |
| `MAX_PAGES` | `120` | Crawl limit per ingestion run |
| `REQUEST_TIMEOUT` | `15` | Seconds before giving up on a page |
| `CRAWL_DELAY` | `0.5` | Seconds between requests (politeness) |
| `REDIS_URL` | *(empty)* | Set to enable answer caching |

---

## 10. Data Flow — Step by Step

### When a user says "What Kentico services does DotStark offer?"

```
1. User types in ChatWidget.jsx input box

2. handleAsk() fires:
   - streamingRef.current = true  (prevents double-fire)
   - Adds user bubble to messages[]
   - Adds empty assistant bubble to messages[]

3. streamChat() in api.js:
   - POST /api/chat/stream
   - { question: "What Kentico services does DotStark offer?" }

4. FastAPI routes.py:
   - pipe = get_pipeline()  (singleton, already loaded)
   - calls pipe.answer_stream(question)

5. pipeline.py:
   - _is_chitchat("What Kentico services...") → False
   - embed_query("Represent this sentence for searching...: What Kentico...")
     → [0.023, -0.041, 0.107, ... ] (384 numbers)

6. retriever.py:
   - Dense: Qdrant search → top-20 chunks by cosine similarity
   - (BM25 disabled: ENABLE_HYBRID=false)
   - Reranker: cross-encoder scores each (question, chunk) pair
   - Returns top-5 chunks

7. prompts.py:
   - Builds: [1](Source: Kentico Migration Page) "DotStark is a Kentico Silver Partner..."
             [2](Source: Solutions Page) "Kentico Xperience upgrade services include..."
             ... + 3 more chunks
   - System prompt: "Answer naturally from context..."

8. LLMClient.stream():
   - POST to Groq API (LLaMA 3.3 70B)
   - Stream returns tokens: "DotStark", " offers", " Kentico", " Xperience", ...

9. routes.py SSE generator:
   - First: event: sources\ndata: [{n:1, title:...}]\n\n
   - Then:  event: token\ndata: "DotStark"\n\n
   - Then:  event: token\ndata: " offers"\n\n
   - ... (for every token)
   - Finally: event: done\ndata: {}\n\n

10. api.js streamChat():
    - onSources([...]) → setMessages updates sources on last bubble
    - onToken("DotStark") → setMessages appends to last bubble content
    - onToken(" offers") → setMessages appends again
    - onDone() → setStreaming(false)

11. React re-renders after each token:
    - User sees text appear word by word
    - Source links visible from the start (before first token)
```

Total time: ~300-800ms for first token, ~2-4 seconds for full answer.

---

## 11. dotstark.com Ingestion Stats

**Run date:** June 2026
**Script:** `scripts/ingest_dotstark.py --reset`

| Metric | Value |
|---|---|
| Pages in sitemap | 117 |
| Pages after robots.txt filter | 114 |
| Pages successfully crawled | 113 |
| Pages skipped (empty/JS-only) | 1 |
| Total chunks stored | 3,332 (this run) |
| Total vectors in Qdrant Cloud | 6,767 |
| Embedding model | BAAI/bge-small-en-v1.5 |
| Vector dimensions | 384 |
| Qdrant collection | website_chunks |

**Breakdown by page type:**

| Section | Pages | Approx. Chunks |
|---|---|---|
| `/blogs/` | 40 | ~1,600 (long articles, 40-60 chunks each) |
| `/services/` | 29 | ~600 |
| `/case-study/` | 28 | ~700 |
| `/solutions/` | 6 | ~200 |
| Other pages | 10 | ~230 |

**Disallowed pages** (robots.txt — not indexed):
- `/privacy-policy`
- `/terms-and-conditions`
- `/career`

---

## 12. How to Run the Project

### Prerequisites
- Python 3.11+
- Node.js 18+
- A free Groq API key: https://console.groq.com/keys

### Backend Setup (run once)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt        # ~5 minutes first time (downloads torch)
copy .env.example .env                 # edit .env, add GROQ_API_KEY
```

### Start the Backend (Terminal 1 — keep open)

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Wait for: `Uvicorn running on http://127.0.0.1:8000`
API docs: http://localhost:8000/docs

### Start the Frontend (Terminal 2 — keep open)

```powershell
cd frontend
npm install          # first time only
npm run dev
```

Open: http://localhost:5173

### Re-index dotstark.com (optional — data already in Qdrant Cloud)

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m scripts.ingest_dotstark --reset
```

### Test without the frontend

```powershell
python -m scripts.demo ingest https://example.com
python -m scripts.demo ask "What is this site about?"
```

---

## 13. Interview Questions & Answers

**Q: What is RAG and why not just fine-tune the model?**
Fine-tuning changes model BEHAVIOUR (style, tone, following instructions better).
It doesn't reliably inject new FACTS — models still hallucinate fine-tuned facts.
RAG injects facts at inference time, is updatable without retraining (just re-index),
and gives you traceable citations. Fine-tuning a 70B model costs thousands of dollars
and takes days. Re-indexing a website takes minutes and is free.

**Q: What is chunking and why do we overlap chunks?**
Chunking splits long documents into pieces that fit the embedding model's context
window. We overlap (share text between consecutive chunks) because a fact can sit
right on a chunk boundary — "The price is [CUT] $49/month." Without overlap,
the complete fact is never in any single chunk.

**Q: What is the difference between a bi-encoder and a cross-encoder?**
A bi-encoder (like bge-small) encodes query and document SEPARATELY into two vectors,
then compares them with cosine similarity. Fast, scalable to millions of docs.
A cross-encoder reads both together — it sees "query: X [SEP] doc: Y" as one input.
Produces a single relevance score. Much more accurate but O(n) per query, so only
practical as a re-ranker on the top-20 candidates from the bi-encoder.

**Q: Why use Reciprocal Rank Fusion instead of score normalization?**
RRF only uses RANKS, not raw scores. BM25 scores and cosine scores are on completely
different scales — you can't average them. RRF sidesteps this: a chunk ranked #1 in
BM25 and #1 in dense gets the highest combined score regardless of the raw numbers.
It's parameter-simple (only k=60), robust, and proven in information retrieval research.

**Q: What is a vector database and why not just use PostgreSQL with pgvector?**
A vector database uses an Approximate Nearest Neighbor (ANN) index — specifically
HNSW (Hierarchical Navigable Small World) — which finds the nearest vectors in
O(log n) time. pgvector does exact nearest-neighbor in O(n) — fine for 10,000 vectors,
too slow for 10,000,000. Qdrant also has native payload filtering, letting you restrict
search to specific source URLs without a second roundtrip.

**Q: How does your system handle questions the website doesn't answer?**
The prompt instructs the LLM: "If the context does not contain the answer, say you
don't have that information." The LLM is given ONLY the retrieved chunks as context —
it cannot use its training knowledge to fill gaps. This is what prevents hallucination.
Additionally, if retrieval returns zero results (e.g., empty index), the pipeline
short-circuits with a "please index a website first" message before even calling the LLM.

**Q: What is Server-Sent Events and why use it instead of WebSockets?**
SSE is a one-way HTTP stream (server → client). WebSockets are bidirectional.
For LLM token streaming, we only need server → client push. SSE works over standard
HTTP/1.1, passes through firewalls and proxies automatically, and reconnects
automatically. WebSockets require a persistent TCP connection upgrade and more
infrastructure complexity. SSE is the right tool for streaming text generation.

**Q: How would you scale this to 1 million users?**
1. Move Qdrant to a distributed cluster (Qdrant already supports sharding)
2. Deploy multiple FastAPI workers behind a load balancer (stateless — pipeline is a
   per-process singleton, each worker loads its own copy)
3. Enable Redis cache — cache hit rate of 30-40% is typical for a company chatbot
   (many users ask the same questions)
4. Move embedding computation to GPU or use a hosted embedding API
5. Use Groq's batch API for non-streaming requests
6. CDN-cache the frontend build

---

## 14. Known Limitations & Future Improvements

### Current Limitations

**JavaScript-rendered pages:**
`requests` only fetches server-rendered HTML. Pages that build content with
JavaScript after loading (Next.js, React SPAs) appear as empty shells.
The crawler detects and skips these (< 20 words). Dotstark.com is Kentico
(server-rendered) so this wasn't an issue, but it will be for some sites.

**No conversation memory:**
Each question is answered independently. The LLM doesn't remember what
was said earlier in the chat. Adding conversation history means appending
previous (question, answer) pairs to the prompt — this increases token cost.

**BM25 index is in-memory:**
The BM25 index is rebuilt from all Qdrant chunks on the first query after
ingestion. With 6,767 chunks this takes < 2 seconds. At 100,000 chunks it
would take longer and use significant RAM. Fix: use Qdrant's built-in sparse
vector support instead.

**Single collection, multiple sites:**
All sites share one `website_chunks` collection. Use the `source_url` metadata
filter to scope queries to one site. A cleaner architecture would be one
collection per site.

### Planned Improvements

| Feature | Description |
|---|---|
| **Crawl4AI** | Replace `requests` for JS-rendered sites (headless browser) |
| **Conversation history** | Append last N turns to the prompt for follow-up questions |
| **Qdrant sparse vectors** | Native BM25 in Qdrant — no in-memory index needed |
| **Multi-site support** | Collection-per-site with automatic routing |
| **Redis cache** | Enable `REDIS_URL` in .env — identical questions instant |
| **Streaming ingest progress** | SSE endpoint for real-time crawl progress in the UI |
| **Auto re-index** | Scheduled job to detect changed pages and re-embed |
| **Source deduplication** | Merge sources from the same URL in the citations list |
