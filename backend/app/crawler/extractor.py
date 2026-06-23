"""
extractor.py  -- the "HTML -> text + links" layer.

Single responsibility: parse an HTML string and pull out
  (1) the human-readable text, and
  (2) the in-site links (so the crawler can discover more pages).

We deliberately strip tags that never contain useful prose (script, style,
nav, footer, etc.). This is the first, structural pass of cleaning; the
finer text cleaning (whitespace, boilerplate) happens in processing/cleaner.py.
"""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

# Tags whose contents are noise for a knowledge base.
_NOISE_TAGS = [
    "script", "style", "noscript", "template",
    "nav", "footer", "header", "aside", "form",
    "svg", "iframe", "button",
]


def extract_text(html: str) -> str:
    """Return readable text from an HTML document."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(_NOISE_TAGS):
        tag.decompose()  # remove the tag and everything inside it

    # separator=" " prevents words from gluing together across tags.
    return soup.get_text(separator=" ", strip=True)


def extract_title(html: str) -> str:
    """Best-effort page title (used as metadata for citations)."""
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def extract_links(html: str, base_url: str) -> list[str]:
    """
    Return absolute, same-domain links found on the page.

    - Relative links (`/about`) are resolved against base_url.
    - URL fragments (`#section`) are dropped so `/a` and `/a#x` aren't
      treated as different pages.
    - Only http/https links on the SAME domain are kept (we don't want to
      crawl the entire internet).
    """
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc

    links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href)
        absolute, _frag = urldefrag(absolute)  # strip "#..."

        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != base_domain:
            continue  # stay on the same website

        links.add(absolute)

    return sorted(links)
