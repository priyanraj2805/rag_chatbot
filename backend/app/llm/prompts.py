"""
prompts.py  -- prompt construction for grounded, cited answers.

This is where "Augmented" in RAG happens: we inject the retrieved chunks into
the prompt as numbered CONTEXT, and instruct the model to answer ONLY from that
context and to cite the sources by number. Good prompt discipline here is what
prevents hallucination and gives you traceable citations.
"""

from __future__ import annotations

from app.vectorstore import StoredChunk

SYSTEM_PROMPT = (
    "You are a friendly AI assistant for DotStark, a software development company. "
    "You help visitors learn about DotStark's services, team, and projects.\n"
    "Rules:\n"
    "1. Answer naturally and conversationally, like a helpful human would.\n"
    "2. Use the provided context to give accurate information.\n"
    "3. If the context doesn't contain the answer, say you don't have that information "
    "and suggest they contact DotStark directly.\n"
    "4. Be warm, professional, and concise. No bullet-point lists unless the user asks.\n"
    "5. Do NOT include source citations like [1], [2] in your response."
)


def build_context_block(chunks: list[StoredChunk]) -> str:
    """Render retrieved chunks as a numbered context the model can cite."""
    blocks = []
    for i, c in enumerate(chunks, start=1):
        source = c.title or c.source_url
        blocks.append(f"[{i}] (Source: {source})\n{c.text}")
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[StoredChunk]) -> list[dict]:
    """Return OpenAI/Groq-style chat messages for the given question + context."""
    context = build_context_block(chunks)
    user_content = (
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"Answer the question naturally using the context above."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
