"""
client.py  -- thin wrapper over the LLM provider (Groq or OpenAI).

Both Groq and OpenAI expose the SAME chat-completions interface, so one wrapper
handles both. We support:
  * generate()  -- blocking, returns the full answer string.
  * stream()    -- yields tokens as they're produced (for a typewriter UI).

The LLM is the ONLY component here that "writes" the answer; everything before
it just decides WHAT context to hand it.
"""

from __future__ import annotations

from collections.abc import Iterator


class LLMClient:
    def __init__(
        self,
        provider: str = "groq",
        groq_api_key: str | None = None,
        groq_model: str = "llama-3.3-70b-versatile",
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
    ):
        self.provider = provider.lower()
        if self.provider == "groq":
            from groq import Groq

            if not groq_api_key:
                raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
            self.client = Groq(api_key=groq_api_key)
            self.model = groq_model
        elif self.provider == "openai":
            from openai import OpenAI

            if not openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            self.client = OpenAI(api_key=openai_api_key)
            self.model = openai_model
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    def generate(self, messages: list[dict], temperature: float = 0.1) -> str:
        """Blocking call -- returns the complete answer."""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    def stream(self, messages: list[dict], temperature: float = 0.1) -> Iterator[str]:
        """Streaming call -- yields answer fragments as they arrive."""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
