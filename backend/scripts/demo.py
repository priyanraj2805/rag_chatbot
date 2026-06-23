"""
demo.py  -- run the full RAG pipeline from the command line (no API/frontend).

Usage:
    python -m scripts.demo ingest https://example.com
    python -m scripts.demo ask "What is this site about?"

Handy for testing ingestion + retrieval before wiring up the web layers.
"""

from __future__ import annotations

import sys

from app.rag import get_pipeline


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command, arg = sys.argv[1], sys.argv[2]
    pipe = get_pipeline()

    if command == "ingest":
        result = pipe.ingest(arg)
        print(f"\nCrawled {result.pages_crawled} pages, stored {result.chunks_stored} chunks.")
    elif command == "ask":
        result = pipe.answer(arg)
        print("\n=== ANSWER ===")
        print(result.answer)
        print("\n=== SOURCES ===")
        for s in result.sources:
            print(f"[{s['n']}] {s['title']} ({s['url']})  score={s['score']}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
