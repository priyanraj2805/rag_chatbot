"""
ingest_dotstark.py  -- crawl ALL pages of dotstark.com and index them into Qdrant.

This script:
  1. Reads every URL from dotstark.com/sitemap.xml (currently 117 pages)
  2. Skips pages disallowed by robots.txt (privacy-policy, terms, /career)
  3. Fetches, cleans, and chunks each page
  4. Embeds with BAAI/bge-small-en-v1.5
  5. Stores vectors + metadata in Qdrant (local embedded mode)

Run from the backend/ folder with the venv activated:
    python -m scripts.ingest_dotstark

Or with a progress reset (wipes existing dotstark data first):
    python -m scripts.ingest_dotstark --reset
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from urllib.parse import urlparse

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TARGET = "https://dotstark.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Pages robots.txt asks us NOT to crawl (we respect this).
DISALLOWED_PREFIXES = (
    "/privacy-policy",
    "/terms-and-conditions",
    "/career",
)


def fetch_sitemap_urls(sitemap_url: str) -> list[str]:
    """Recursively expand sitemap index -> all page URLs."""
    try:
        r = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            logger.warning("Sitemap returned %d: %s", r.status_code, sitemap_url)
            return []
        xml = r.content.decode("utf-8", errors="replace")
    except requests.RequestException as exc:
        logger.warning("Could not fetch sitemap: %s", exc)
        return []

    # Sitemap index -> nested sitemaps
    child_sitemaps = re.findall(r"<sitemap>\s*<loc>(.*?)</loc>", xml)
    if child_sitemaps:
        all_urls: list[str] = []
        for child in child_sitemaps:
            all_urls.extend(fetch_sitemap_urls(child.strip()))
        return all_urls

    # Regular sitemap -> page URLs
    return [u.strip() for u in re.findall(r"<url>\s*<loc>(.*?)</loc>", xml)]


def is_allowed(url: str) -> bool:
    path = urlparse(url).path
    return not any(path.startswith(p) for p in DISALLOWED_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest dotstark.com into Qdrant")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe existing collection before indexing")
    parser.add_argument("--delay", type=float, default=0.4,
                        help="Seconds between requests (default 0.4)")
    args = parser.parse_args()

    # Import pipeline AFTER arg parsing so --help is instant.
    from app.rag.pipeline import get_pipeline
    from app.crawler.fetcher import fetch_html, FetchError
    from app.crawler.extractor import extract_text, extract_title
    from app.processing import clean_text, chunk_text
    from app.config import settings

    logger.info("Loading RAG pipeline (embedder + Qdrant)…")
    pipe = get_pipeline()

    if args.reset:
        logger.info("Resetting Qdrant collection '%s'…", settings.collection_name)
        pipe.store.recreate_collection()

    # ── Step 1: discover all pages ──────────────────────────────────────────
    logger.info("Fetching sitemap from %s/sitemap.xml…", TARGET)
    all_urls = fetch_sitemap_urls(f"{TARGET}/sitemap.xml")

    # Keep only same-domain, allowed pages, deduplicated.
    allowed = []
    seen: set[str] = set()
    for url in all_urls:
        if urlparse(url).netloc != "dotstark.com":
            continue
        if url in seen:
            continue
        seen.add(url)
        if is_allowed(url):
            allowed.append(url)

    logger.info("Found %d pages in sitemap → %d after robots.txt filter",
                len(all_urls), len(allowed))

    # ── Step 2: crawl + embed + store ───────────────────────────────────────
    total_chunks = 0
    skipped = 0

    for i, url in enumerate(allowed, start=1):
        logger.info("[%3d/%d] Fetching: %s", i, len(allowed), url)

        try:
            html = fetch_html(url, timeout=15)
        except FetchError as exc:
            logger.warning("  SKIP (fetch error): %s", exc)
            skipped += 1
            time.sleep(args.delay)
            continue

        raw_text  = extract_text(html)
        title     = extract_title(html)
        cleaned   = clean_text(raw_text)
        chunks    = chunk_text(cleaned,
                               chunk_size=settings.chunk_size,
                               overlap=settings.chunk_overlap)

        if not chunks:
            logger.info("  SKIP (no text extracted — likely JS-rendered shell)")
            skipped += 1
            time.sleep(args.delay)
            continue

        texts   = [c.text for c in chunks]
        vectors = pipe.embedder.embed_documents(texts)
        added   = pipe.store.upsert(
            vectors=vectors,
            texts=texts,
            source_url=url,
            title=title,
        )
        total_chunks += added
        logger.info("  OK  title=%r  chunks=%d  cumulative=%d", title, added, total_chunks)

        time.sleep(args.delay)   # be polite

    # Rebuild BM25 index so hybrid search uses the fresh corpus.
    pipe.retriever.invalidate_cache()

    # ── Step 3: summary ─────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  INGESTION COMPLETE")
    print("=" * 60)
    print(f"  Pages attempted  : {len(allowed)}")
    print(f"  Pages skipped    : {skipped}")
    print(f"  Pages indexed    : {len(allowed) - skipped}")
    print(f"  Chunks stored    : {total_chunks}")
    print(f"  Qdrant total     : {pipe.store.count()}")
    print("=" * 60)
    print()
    print("You can now ask questions about dotstark.com in the chat widget!")


if __name__ == "__main__":
    main()
