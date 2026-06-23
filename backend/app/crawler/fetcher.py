"""
fetcher.py  -- the "network" layer.

Single responsibility: given a URL, return the raw HTML string.
It knows nothing about parsing, chunking, or embeddings. Keeping this isolated
means we can later swap `requests` for Crawl4AI / Playwright (for JavaScript
heavy sites) without touching the rest of the pipeline.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# Pretend to be a real browser. Many servers return 403 to the default
# "python-requests/x.y" user agent.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchError(Exception):
    """Raised when a page cannot be fetched (network error, bad status, etc.)."""


def fetch_html(url: str, timeout: int = 15) -> str:
    """
    Fetch the raw HTML for a URL.

    Raises FetchError on any problem so callers can skip a page and continue
    crawling instead of crashing the whole run.
    """
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise FetchError(f"Bad status {response.status_code} for {url}")

    # Only keep HTML pages -- skip PDFs, images, JSON endpoints, etc.
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        raise FetchError(f"Non-HTML content ({content_type}) at {url}")

    # `response.text` decodes bytes using the server-declared charset.
    return response.text
