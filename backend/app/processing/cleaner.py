"""
cleaner.py  -- normalize raw extracted text.

The extractor already removed scripts/nav/footer tags. This pass fixes the
*text* itself: collapses whitespace, removes control characters, de-duplicates
blank lines, and drops obvious boilerplate lines (cookie banners, "skip to
content", etc.). Clean input = better chunks = better embeddings.
"""

from __future__ import annotations

import re
import unicodedata

# Lines that are almost always navigation/boilerplate noise.
_BOILERPLATE_PATTERNS = [
    r"^\s*skip to (main )?content\s*$",
    r"^\s*accept( all)? cookies\s*$",
    r"^\s*we use cookies.*$",
    r"^\s*all rights reserved.*$",
    r"^\s*©.*$",
    r"^\s*sign in\s*$",
    r"^\s*log ?in\s*$",
    r"^\s*subscribe\s*$",
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_PATTERNS), re.IGNORECASE)

# Matches runs of whitespace (including non-breaking spaces).
_WS_RE = re.compile(r"[ \t ]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    if not text:
        return ""

    # 1. Normalize unicode (curly quotes, accents) to a consistent form.
    text = unicodedata.normalize("NFKC", text)

    # 2. Strip control characters except newline/tab.
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )

    # 3. Process line by line: trim, drop boilerplate, collapse spaces.
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _WS_RE.sub(" ", raw_line).strip()
        if not line:
            cleaned_lines.append("")
            continue
        if _BOILERPLATE_RE.match(line):
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # 4. Collapse 3+ blank lines into a single blank line (paragraph break).
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)

    return text.strip()
