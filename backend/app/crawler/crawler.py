"""
crawler.py  -- the orchestrator for the INGESTION crawl.

Given a starting URL, it walks the website (breadth-first), respecting:
  - robots.txt rules,
  - a maximum page count,
  - a politeness delay between requests,
  - the site's own sitemap.xml (a fast way to discover pages).

It returns a list of CrawledPage objects (url, title, raw text). Everything
downstream (cleaning, chunking, embedding) consumes these.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .extractor import extract_links, extract_text, extract_title
from .fetcher import DEFAULT_HEADERS, FetchError, fetch_html

logger = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    url: str
    title: str
    text: str


class WebsiteCrawler:
    def __init__(
        self,
        max_pages: int = 40,
        timeout: int = 15,
        delay: float = 0.5,
        respect_robots: bool = True,
    ):
        self.max_pages = max_pages
        self.timeout = timeout
        self.delay = delay
        self.respect_robots = respect_robots
        self._robots: RobotFileParser | None = None

    # ----- robots.txt -----------------------------------------------------
    def _load_robots(self, start_url: str) -> None:
        parsed = urlparse(start_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
            self._robots = rp
            logger.info("Loaded robots.txt from %s", robots_url)
        except Exception:  # noqa: BLE001 - robots is best-effort
            self._robots = None
            logger.warning("Could not read robots.txt at %s", robots_url)

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots or self._robots is None:
            return True
        return self._robots.can_fetch(DEFAULT_HEADERS["User-Agent"], url)

    # ----- sitemap discovery ----------------------------------------------
    def _sitemap_urls(self, start_url: str) -> list[str]:
        """
        Try to read /sitemap.xml. A sitemap is an XML list of every page the
        site WANTS indexed -- far more reliable than guessing from links.
        Handles sitemap-index files (a sitemap of sitemaps) one level deep.
        """
        parsed = urlparse(start_url)
        sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
        found: list[str] = []
        try:
            resp = requests.get(
                sitemap_url, headers=DEFAULT_HEADERS, timeout=self.timeout
            )
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "xml")

            # If this is a sitemap index, recurse one level into child sitemaps.
            child_sitemaps = [loc.get_text(strip=True) for loc in soup.select("sitemap > loc")]
            if child_sitemaps:
                for child in child_sitemaps[:10]:
                    try:
                        c = requests.get(child, headers=DEFAULT_HEADERS, timeout=self.timeout)
                        csoup = BeautifulSoup(c.text, "xml")
                        found += [loc.get_text(strip=True) for loc in csoup.select("url > loc")]
                    except requests.RequestException:
                        continue
            else:
                found = [loc.get_text(strip=True) for loc in soup.select("url > loc")]
        except requests.RequestException:
            return []

        # Keep only same-domain URLs.
        domain = parsed.netloc
        return [u for u in found if urlparse(u).netloc == domain]

    # ----- main crawl -----------------------------------------------------
    def crawl(self, start_url: str) -> list[CrawledPage]:
        """
        Breadth-first crawl starting at `start_url`.

        Strategy:
          1. Seed the queue with sitemap URLs (if any) + the start URL.
          2. Pop a URL, fetch it, extract text + links.
          3. Push newly discovered same-domain links onto the queue.
          4. Stop at max_pages.
        """
        if self.respect_robots:
            self._load_robots(start_url)

        queue: deque[str] = deque()
        seen: set[str] = set()

        # Seed with sitemap first -- usually the cleanest set of pages.
        for u in self._sitemap_urls(start_url):
            if u not in seen:
                seen.add(u)
                queue.append(u)
        if start_url not in seen:
            seen.add(start_url)
            queue.appendleft(start_url)  # always crawl the entry page first

        pages: list[CrawledPage] = []

        while queue and len(pages) < self.max_pages:
            url = queue.popleft()

            if not self._allowed(url):
                logger.info("Blocked by robots.txt: %s", url)
                continue

            try:
                html = fetch_html(url, timeout=self.timeout)
            except FetchError as exc:
                logger.warning("Skip %s (%s)", url, exc)
                continue

            text = extract_text(html)
            title = extract_title(html)

            # Skip near-empty pages (often JS-rendered shells or redirects).
            if len(text.split()) < 20:
                logger.info("Skip %s (too little text)", url)
            else:
                pages.append(CrawledPage(url=url, title=title, text=text))
                logger.info("Crawled (%d/%d): %s", len(pages), self.max_pages, url)

            # Discover more pages.
            for link in extract_links(html, url):
                if link not in seen:
                    seen.add(link)
                    queue.append(link)

            time.sleep(self.delay)  # be polite -- don't hammer the server

        return pages
