"""
Lightweight tests for the pure-Python processing layer (no heavy models needed).

Run with:
    python -m pytest tests/ -v
or simply:
    python tests/test_processing.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.processing import chunk_text, clean_text  # noqa: E402


def test_clean_collapses_whitespace_and_boilerplate():
    raw = "Skip to content\n\nHello    world\n\n\n\n\nWe use cookies to improve.\nReal text."
    cleaned = clean_text(raw)
    assert "Skip to content" not in cleaned
    assert "We use cookies" not in cleaned
    assert "Hello world" in cleaned
    assert "Real text." in cleaned


def test_chunk_respects_size():
    text = " ".join([f"Sentence number {i}." for i in range(200)])
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    # No chunk should be wildly larger than chunk_size (allow sentence slack).
    assert all(len(c.text) <= 200 + 60 for c in chunks)


def test_chunk_overlap_creates_continuity():
    text = " ".join([f"Word{i}." for i in range(100)])
    chunks = chunk_text(text, chunk_size=120, overlap=40)
    # Consecutive chunks should share at least one token due to overlap.
    for a, b in zip(chunks, chunks[1:]):
        a_tail = set(a.text.split()[-5:])
        b_head = set(b.text.split()[:5])
        assert a_tail & b_head, "expected overlap between consecutive chunks"


def test_empty_input():
    assert clean_text("") == ""
    assert chunk_text("") == []


if __name__ == "__main__":
    test_clean_collapses_whitespace_and_boilerplate()
    test_chunk_respects_size()
    test_chunk_overlap_creates_continuity()
    test_empty_input()
    print("All processing tests passed [OK]")
