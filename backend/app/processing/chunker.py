"""
chunker.py  -- split long text into overlapping, embeddable pieces.

WHY CHUNK?
  An embedding model turns a piece of text into ONE vector. If you embed a
  whole 5,000-word page into one vector, that vector is a blurry average of
  every topic on the page -- retrieval becomes useless. So we cut the page
  into smaller, topically-focused chunks and embed each one.

WHY OVERLAP?
  A fact can sit right on a chunk boundary ("...the price is" | "$49/month").
  By letting consecutive chunks share some text (the "overlap"), we avoid
  cutting an idea in half and losing it at retrieval time.

STRATEGY (sentence-aware sliding window):
  We split into sentences, then pack sentences into a chunk until we hit
  `chunk_size` characters. When we start the next chunk, we carry over the
  last ~`overlap` characters worth of sentences. This keeps chunks readable
  (never cuts mid-sentence) while preserving continuity across boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Naive but effective sentence splitter: split after . ! ? followed by space.
# (A full NLP sentence tokenizer is overkill here and adds a heavy dependency.)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    text: str
    index: int  # position of this chunk within its source document


def _split_sentences(text: str) -> list[str]:
    # Split on paragraph breaks first, then sentences, so paragraph structure
    # is respected and we never merge across a hard paragraph boundary.
    sentences: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sent in _SENTENCE_RE.split(paragraph):
            sent = sent.strip()
            if sent:
                sentences.append(sent)
    return sentences


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[Chunk]:
    """
    Return a list of overlapping Chunks.

    chunk_size : target maximum characters per chunk.
    overlap    : characters of trailing context carried into the next chunk.
    """
    if not text.strip():
        return []
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    sentences = _split_sentences(text)
    chunks: list[Chunk] = []

    current: list[str] = []        # sentences in the chunk being built
    current_len = 0                # running character length
    index = 0

    for sentence in sentences:
        # A single sentence longer than chunk_size: hard-split it by characters
        # so it doesn't blow past the limit on its own.
        if len(sentence) > chunk_size:
            if current:
                chunks.append(Chunk(text=" ".join(current), index=index))
                index += 1
                current, current_len = [], 0
            for start in range(0, len(sentence), chunk_size - overlap):
                piece = sentence[start : start + chunk_size]
                chunks.append(Chunk(text=piece, index=index))
                index += 1
            continue

        # If adding this sentence would overflow, close the current chunk.
        if current and current_len + len(sentence) + 1 > chunk_size:
            chunks.append(Chunk(text=" ".join(current), index=index))
            index += 1

            # Build the overlap: take trailing sentences up to `overlap` chars.
            overlap_buf: list[str] = []
            overlap_len = 0
            for sent in reversed(current):
                if overlap_len + len(sent) > overlap:
                    break
                overlap_buf.insert(0, sent)
                overlap_len += len(sent) + 1
            current = overlap_buf
            current_len = overlap_len

        current.append(sentence)
        current_len += len(sentence) + 1

    if current:
        chunks.append(Chunk(text=" ".join(current), index=index))

    return chunks
