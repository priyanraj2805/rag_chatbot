# DotStark RAG Chatbot — High Level Architecture

---

## Complete System Architecture

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                              USER'S BROWSER                                      ║
║                                                                                  ║
║   ┌─────────────────────────────────────────────────────────────────────────┐   ║
║   │                      React Chat Widget                                   │   ║
║   │                                                                           │   ║
║   │   ┌─────────────────────────┐    ┌──────────────────────────────────┐   │   ║
║   │   │      Chat Tab           │    │       Index a Website Tab         │   │   ║
║   │   │  - Type question        │    │  - Paste any URL                  │   │   ║
║   │   │  - See streaming answer │    │  - Click Start Indexing           │   │   ║
║   │   │  - See source citations │    │  - Progress shown in real time    │   │   ║
║   │   │  - Markdown rendered    │    └──────────────────────────────────┘   │   ║
║   │   └─────────────────────────┘                                            │   ║
║   └──────────────────────────────────┬──────────────────────────────────────┘   ║
╚═════════════════════════════════════╪════════════════════════════════════════════╝
                                      │
                          HTTP + SSE (streaming)
                                      │
╔═════════════════════════════════════▼════════════════════════════════════════════╗
║                            FastAPI Backend                                        ║
║                                                                                   ║
║   ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐   ║
║   │  POST /chat      │  │ POST /chat/stream │  │      POST /ingest          │   ║
║   │  (full response) │  │ (SSE streaming)  │  │  (crawl + index website)   │   ║
║   └────────┬─────────┘  └────────┬─────────┘  └─────────────┬──────────────┘   ║
║            │                     │                            │                   ║
║            └──────────┬──────────┘                           │                   ║
║                       │                                       │                   ║
║          ┌────────────▼──────────────────┐     ┌────────────▼──────────────┐   ║
║          │         QUERY PIPELINE         │     │      INGESTION PIPELINE    │   ║
║          └────────────────────────────────┘     └───────────────────────────┘   ║
╚════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Ingestion Pipeline  (runs when you index a website)

```
  URL INPUT
  (e.g. https://dotstark.com)
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│                        WEB CRAWLER                          │
│                                                             │
│  • Reads robots.txt  →  respects blocked pages             │
│  • Reads sitemap.xml →  discovers all pages instantly      │
│  • BFS crawl with 0.5s delay between requests              │
│  • Skips pages with less than 20 words                     │
│  • Returns: URL + page title + raw HTML text               │
└─────────────────────────────┬──────────────────────────────┘
                              │  up to 120 pages
                              ▼
┌────────────────────────────────────────────────────────────┐
│                       TEXT CLEANER                          │
│                                                             │
│  • Unicode normalization (NFKC standard)                   │
│  • Removes control characters and invisible chars          │
│  • Strips boilerplate: cookie banners, nav menus,          │
│    footer text, copyright notices                          │
│  • Collapses multiple blank lines into one                 │
│  • Returns: clean plain text                               │
└─────────────────────────────┬──────────────────────────────┘
                              │  clean text
                              ▼
┌────────────────────────────────────────────────────────────┐
│                       TEXT CHUNKER                          │
│                                                             │
│  • Sentence-aware sliding window algorithm                 │
│  • Chunk size: 800 characters                              │
│  • Overlap:    150 characters (context continuity)         │
│  • Never cuts a sentence in the middle                     │
│  • Splits on . ! ? and paragraph breaks                    │
│  • Returns: list of text chunks with index numbers         │
└─────────────────────────────┬──────────────────────────────┘
                              │  ~60 chunks per page
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     EMBEDDING MODEL                         │
│                      bge-small-en-v1.5                      │
│                                                             │
│  • Runs locally on your machine (free, no API cost)        │
│  • Converts each chunk into a 384-number vector            │
│  • Each number captures semantic meaning of the text       │
│  • L2-normalized (all vectors on same scale)               │
│  • Document prefix added before embedding                  │
│  • Returns: 384-dimensional float vectors                  │
└─────────────────────────────┬──────────────────────────────┘
                              │  vectors + metadata
                              ▼
┌────────────────────────────────────────────────────────────┐
│                      QDRANT CLOUD                           │
│                     (Vector Database)                       │
│                                                             │
│  • Stores each chunk as: vector + text + URL + title       │
│  • Index type: HNSW (fast approximate search)              │
│  • Distance metric: Cosine similarity                      │
│  • dotstark.com: 113 pages → 6,767 chunks stored           │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────┐
              │   Cache Version Bumped    │
              │   BM25 Index Invalidated  │
              │   (both happen after      │
              │    every ingest)          │
              └───────────────────────────┘
```

---

## Query Pipeline  (runs on every user question)

```
  USER QUESTION
  e.g. "what azure services does dotstark offer?"
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│                    GREETING DETECTOR                        │
│                                                             │
│  Regex check for: hi, hello, hey, thanks, bye,             │
│  how are you, who are you, what can you do, etc.           │
│                                                             │
│  MATCH  →  skip entire RAG pipeline                        │
│            send directly to LLM with friendly prompt       │
│  NO MATCH  →  continue                                     │
└─────────────────────────────┬──────────────────────────────┘
                              │  not a greeting
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     QUERY REWRITER                          │
│                                                             │
│  GUARD 1 — Vague pronoun check:                            │
│    "what do they offer?"     →  has "they" → rewrite       │
│    "what does dotstark offer?" →  no pronoun → SKIP        │
│    Saves ~600ms on 90% of questions                        │
│                                                             │
│  GUARD 2 — In-memory rewrite cache:                        │
│    Same vague question asked before → return instantly     │
│                                                             │
│  IF rewrite needed:                                        │
│    LLM call: "when was it founded?"                        │
│           →  "When was DotStark founded?"                  │
└─────────────────────────────┬──────────────────────────────┘
                              │  (possibly rewritten) query
                              ▼
┌────────────────────────────────────────────────────────────┐
│                   REDIS — LAYER 1                           │
│                   Exact Question Cache                      │
│                                                             │
│  Key = hash ( version + question )                         │
│                                                             │
│  HIT  →  return full answer instantly                      │
│           nothing else runs              ✅  ~50ms          │
│                                                             │
│  MISS →  continue to retrieval                             │
└─────────────────────────────┬──────────────────────────────┘
                              │  Layer 1 miss
                              ▼
┌────────────────────────────────────────────────────────────┐
│                    DENSE SEARCH                             │
│                    (Semantic / Vector)                      │
│                                                             │
│  • Query embedded with bge-small (query prefix added)      │
│  • HNSW search in Qdrant Cloud                             │
│  • Finds chunks with most similar MEANING                  │
│  • "car" matches "automobile" — synonym aware              │
│  • Returns: top 10 candidates by cosine score              │
│  • Network call: ~250ms                                    │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   │   +  (when hybrid search enabled)
                   │
┌──────────────────▼──────────────────────────────────────────┐
│                    SPARSE SEARCH                             │
│                    (BM25 Keyword)                            │
│                                                             │
│  • Tokenizes query into individual words                   │
│  • Scores all chunks by TF-IDF keyword frequency           │
│  • Finds chunks containing exact search terms              │
│  • "manoj sharma" matches chunk with just "manoj"          │
│  • Returns: top 10 candidates by keyword score             │
│  • In-memory: ~10ms                                        │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     RRF FUSION                              │
│             Reciprocal Rank Fusion  (k=60)                 │
│                                                             │
│  • Merges dense + sparse result lists into one             │
│  • Score = 1/(60 + rank) from each list                    │
│  • Chunks ranked high in EITHER list rise to top           │
│  • Best of semantic meaning + exact keyword match          │
│  • Returns: unified ranked list of top candidates          │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                      RERANKER                               │
│               Cross-Encoder (ms-marco-MiniLM)              │
│                                                             │
│  • Reads question AND chunk TOGETHER (more accurate)       │
│  • Scores each (question, chunk) pair as a unit            │
│  • Unlike embeddings which read them separately            │
│  • Candidate pool: 10 chunks in, top 5 out                 │
│  • Runs on CPU: ~250ms                                     │
│  • Returns: final top 5 most relevant chunks               │
└─────────────────────────────┬──────────────────────────────┘
                              │  top 5 chunks
                              ▼
┌────────────────────────────────────────────────────────────┐
│                   REDIS — LAYER 2                           │
│                   LLM Cache                                 │
│                                                             │
│  Key = hash ( version + question + chunk_id_1              │
│               + chunk_id_2 + chunk_id_3 ... )              │
│                                                             │
│  WHY chunk IDs in key?                                     │
│  LLM answer depends entirely on the chunks fed to it.      │
│  Same chunks = same answer → safe to cache.                │
│  Different chunks = different answer → cache MISS.         │
│                                                             │
│  HIT  →  return cached LLM answer                         │
│           LLM never called              ✅  ~600ms total    │
│                                                             │
│  MISS →  continue to LLM                                  │
└─────────────────────────────┬──────────────────────────────┘
                              │  Layer 2 miss
                              ▼
┌────────────────────────────────────────────────────────────┐
│                         LLM                                 │
│               Groq API — LLaMA 3.3 70B Versatile           │
│                                                             │
│  • System prompt: "answer only from the context below"     │
│  • Context: top 5 reranked chunks injected                 │
│  • Temperature: 0.1 (focused, not creative)                │
│  • Output: streams tokens one by one via SSE               │
│  • ~800ms to first token                                   │
└─────────────────────────────┬──────────────────────────────┘
                              │  token stream
                              ▼
┌────────────────────────────────────────────────────────────┐
│               STREAM AND CACHE SIMULTANEOUSLY               │
│                                                             │
│  Token arrives from Groq                                   │
│       │                                                     │
│       ├──→  sent to frontend immediately (user sees it)    │
│       └──→  appended to full answer list (collected)       │
│                                                             │
│  After last token:                                         │
│       ├──→  full answer stored in Redis Layer 2            │
│       └──→  full answer stored in Redis Layer 1            │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
                     ANSWER TO USER
                    (~1400ms first time)
```

---

## Redis Cache — Version Invalidation

```
  NORMAL OPERATION
  ─────────────────
  rag:version = 1

  Layer 1 key = hash("v1 | question")
  Layer 2 key = hash("v1 | question | chunk_ids")

  Both layers serve cached answers normally.


  INGEST RUNS  (new pages added to Qdrant)
  ──────────────────────────────────────────
  Redis INCR "rag:version"
       │
       ▼
  rag:version = 2   ← atomic, instant, O(1)

  Layer 1 key = hash("v2 | question")        ← NEW key, old answer unreachable
  Layer 2 key = hash("v2 | question | chunks") ← NEW key, old answer unreachable

  Old v1 keys → still in Redis but NEVER read again
              → expire naturally after 24 hours TTL
              → no manual deletion needed
```

---

## Response Time at Each Cache Layer

```
  Question arrives
       │
  ┌────▼──────────────────────────────────────────┐
  │ Layer 1 HIT                                    │──→  ~50ms   ✅
  │ (exact same question cached)                   │
  └────┬──────────────────────────────────────────┘
       │ MISS
  ┌────▼──────────────────────────────────────────┐
  │ Qdrant Search + BM25 + RRF + Reranker          │  ~550ms
  └────┬──────────────────────────────────────────┘
       │
  ┌────▼──────────────────────────────────────────┐
  │ Layer 2 HIT                                    │──→  ~600ms  ✅
  │ (same chunks retrieved, LLM skipped)           │
  └────┬──────────────────────────────────────────┘
       │ MISS
  ┌────▼──────────────────────────────────────────┐
  │ LLM (Groq — LLaMA 3.3 70B)                    │  ~800ms
  └────┬──────────────────────────────────────────┘
       │
  ┌────▼──────────────────────────────────────────┐
  │ Store in Layer 2 + Layer 1                     │
  └────┬──────────────────────────────────────────┘
       │
       ▼
  Answer to user                                      ~1400ms
```

---

## External Services

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   Qdrant Cloud  │   │   Groq API      │   │  Redis Cloud    │
│                 │   │                 │   │                 │
│  Vector storage │   │  LLM inference  │   │  Answer cache   │
│  6,767 chunks   │   │  LLaMA 3.3 70B  │   │  Two layers     │
│  HNSW index     │   │  Free tier      │   │  24h TTL        │
│  Cosine metric  │   │  Streaming      │   │  Version-based  │
│  Free tier      │   │  ~800ms         │   │  invalidation   │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## Technology Stack

```
  Frontend    →  React + Vite           (chat widget, SSE streaming)
  Backend     →  FastAPI + Python       (REST API, SSE endpoints)
  Embeddings  →  bge-small-en-v1.5     (local, free, 384-dim vectors)
  Vector DB   →  Qdrant Cloud          (HNSW, cosine, free tier)
  Keywords    →  BM25 (rank-bm25)      (in-memory, exact term matching)
  Reranker    →  ms-marco-MiniLM       (cross-encoder, runs on CPU)
  LLM         →  Groq + LLaMA 3.3 70B (free API, fastest inference)
  Cache L1    →  Redis (exact match)   (~50ms on hit)
  Cache L2    →  Redis (chunk IDs)     (~600ms on hit, LLM skipped)
  Scraping    →  requests + BS4        (no headless browser needed)
```
